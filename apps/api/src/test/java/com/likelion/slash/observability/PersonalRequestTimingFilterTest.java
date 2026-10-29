package com.likelion.slash.observability;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import tools.jackson.databind.json.JsonMapper;
import com.fasterxml.jackson.annotation.JsonInclude;
import jakarta.servlet.ServletException;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ConcurrentLinkedQueue;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicLong;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

class PersonalRequestTimingFilterTest {
    private static final String PROBE = "f328c97b-779a-4c05-9d4b-7852b58c369d";
    private final Clock clock = Clock.fixed(Instant.parse("2026-10-29T00:00:00Z"), ZoneOffset.UTC);
    private final List<PersonalRequestTimingFilter.TimingEvent> events = new ArrayList<>();
    private final AtomicLong ticks = new AtomicLong();
    private final PersonalRequestTimingFilter filter = new PersonalRequestTimingFilter(
            8080, clock, () -> ticks.getAndAdd(25_000_000L), events::add);

    private MockHttpServletRequest request() {
        var request = new MockHttpServletRequest("GET", "/api/v1/me");
        request.setLocalPort(8080);
        return request;
    }

    @Test
    void correlatesACompletedResponseWithoutRecordingSecretsOrQueryData() throws Exception {
        var request = request();
        request.addHeader("X-Slash-Probe-Id", PROBE);
        request.addHeader("Authorization", "Bearer private-token");
        request.addHeader("X-Forwarded-For", "198.51.100.17");
        request.setQueryString("email=private@example.test");
        request.setContent("private-body".getBytes());
        var response = new MockHttpServletResponse();
        filter.doFilter(request, response, (req, res) -> {
            assertThat(response.getHeader("X-Slash-Request-Id")).isNotBlank();
            response.getWriter().write("unchanged-body");
        });

        assertThat(response.getContentAsString()).isEqualTo("unchanged-body");
        assertThat(response.getHeader("Server-Timing")).isNull();
        assertThat(events).hasSize(1);
        var event = events.getFirst();
        assertThat(event.clientProbeId()).isEqualTo(PROBE);
        assertThat(event.appRequestId()).isEqualTo(response.getHeader("X-Slash-Request-Id"));
        assertThat(event.appRequestId()).isNotEqualTo(PROBE);
        assertThat(event.status()).isEqualTo(200);
        assertThat(event.durationMs()).isEqualTo(25.0);
        var json = JsonMapper.builder().configureForJackson2().build().writeValueAsString(event);
        assertThat(json).doesNotContain("private-token", "private@example", "private-body", "198.51.100.17");
        assertThat(JsonMapper.builder().configureForJackson2().build().readTree(json).properties()).hasSize(8);
        assertThat(event.timestamp()).isEqualTo("2026-10-29T00:00:00Z");
    }

    @Test
    void ignoresMissingMalformedDuplicateAndNonCanonicalProbeIds() throws Exception {
        List<String> malformed = List.of("", "private@example.test", "a\r\nsecret", "a".repeat(4096),
                PROBE.toUpperCase(), "1-1-1-1-1", PROBE + "," + PROBE);
        for (String value : malformed) {
            var request = request();
            request.addHeader("X-Slash-Probe-Id", value);
            filter.doFilter(request, new MockHttpServletResponse(), (req, res) -> { });
        }
        var duplicate = request();
        duplicate.addHeader("X-Slash-Probe-Id", PROBE);
        duplicate.addHeader("X-Slash-Probe-Id", PROBE);
        filter.doFilter(duplicate, new MockHttpServletResponse(), (req, res) -> { });
        filter.doFilter(request(), new MockHttpServletResponse(), (req, res) -> { });
        assertThat(events).hasSize(malformed.size() + 2).allSatisfy(event -> {
            assertThat(event.clientProbeId()).isNull();
            assertThat(event.appRequestId()).matches("[0-9a-f-]{36}");
        });
    }

    @Test
    void recordsErrorsAndDoesNotGuessTheContainerStatusForAnEscapingException() throws Exception {
        var response = new MockHttpServletResponse();
        assertThatThrownBy(() -> filter.doFilter(request(), response, (req, res) -> {
            throw new ServletException("private failure detail");
        })).isInstanceOf(ServletException.class).hasMessage("private failure detail");
        assertThat(events).hasSize(1);
        assertThat(events.getFirst().status()).isNull();
        assertThat(events.getFirst().durationMs()).isEqualTo(25.0);
        var mapper = JsonMapper.builder().configureForJackson2()
                .changeDefaultPropertyInclusion(inclusion -> inclusion.withValueInclusion(JsonInclude.Include.NON_NULL))
                .build();
        String serialized = mapper.writeValueAsString(events.getFirst());
        assertThat(serialized).doesNotContain("private failure detail");
        assertThat(mapper.readTree(serialized).get("status").isNull()).isTrue();

        filter.doFilter(request(), new MockHttpServletResponse(), (req, res) -> {
            ((MockHttpServletResponse) res).setStatus(500);
        });
        assertThat(events.get(1).status()).isEqualTo(500);
    }

    @Test
    void keepsAnAlreadyCommittedStatusEvenWhenWritingLaterFails() throws Exception {
        var response = new MockHttpServletResponse();
        assertThatThrownBy(() -> filter.doFilter(request(), response, (req, res) -> {
            response.setStatus(503);
            response.flushBuffer();
            throw new ServletException("not logged");
        })).isInstanceOf(ServletException.class);
        assertThat(events.getFirst().status()).isEqualTo(503);
    }

    @Test
    void excludesOtherMethodsRoutesAndTheManagementPortEvenWithForwardedHeaders() throws Exception {
        var management = request(); management.setLocalPort(9091); management.addHeader("X-Forwarded-Port", "8080");
        var otherRoute = request(); otherRoute.setRequestURI("/api/v1/users/private-user");
        var post = request(); post.setMethod("POST");
        var actuator = request(); actuator.setRequestURI("/actuator/prometheus");
        for (var request : List.of(management, otherRoute, post, actuator)) {
            var response = new MockHttpServletResponse();
            filter.doFilter(request, response, (req, res) -> response.getWriter().write("unchanged"));
            assertThat(response.getContentAsString()).isEqualTo("unchanged");
            assertThat(response.getHeader("X-Slash-Request-Id")).isNull();
        }
        assertThat(events).isEmpty();
    }

    @Test
    void telemetryFailureDoesNotReplaceTheApplicationResponse() throws Exception {
        var failingSink = new PersonalRequestTimingFilter(8080, clock, System::nanoTime, event -> {
            throw new IllegalStateException("must not be logged");
        });
        var response = new MockHttpServletResponse();
        failingSink.doFilter(request(), response, (req, res) -> response.setStatus(403));
        assertThat(response.getStatus()).isEqualTo(403);
    }

    @Test
    void concurrentRequestsGetSeparateServerIdsWithoutThreadLocalState() throws Exception {
        var recorded = new ConcurrentLinkedQueue<PersonalRequestTimingFilter.TimingEvent>();
        var concurrentFilter = new PersonalRequestTimingFilter(8080, clock, System::nanoTime, recorded::add);
        try (var executor = Executors.newVirtualThreadPerTaskExecutor()) {
            var tasks = new ArrayList<java.util.concurrent.Future<String>>();
            for (int i = 0; i < 20; i++) tasks.add(executor.submit(() -> {
                var response = new MockHttpServletResponse();
                concurrentFilter.doFilter(request(), response, (req, res) -> { });
                return response.getHeader("X-Slash-Request-Id");
            }));
            var responseIds = new ArrayList<String>();
            for (var task : tasks) responseIds.add(task.get());
            assertThat(responseIds).doesNotHaveDuplicates();
            assertThat(recorded).hasSize(20);
            assertThat(recorded).extracting(PersonalRequestTimingFilter.TimingEvent::appRequestId)
                    .containsExactlyInAnyOrderElementsOf(responseIds);
        }
    }

    @Test
    void recordsOnlyASingleBoundedGatewayId() throws Exception {
        var valid = request(); valid.addHeader("X-Slash-Gateway-Request-Id", "Abcd_0123+/-=");
        filter.doFilter(valid, new MockHttpServletResponse(), (req, res) -> { });
        assertThat(events.getFirst().gatewayRequestId()).isEqualTo("Abcd_0123+/-=");
        for (String value : List.of("short", "a".repeat(129), "abc defgh", "abc\r\ndefgh",
                "eyJhbGci.eyJzdWI.signature", "private@example.test", "Abcd_0123+/=-")) {
            var bad = request(); bad.addHeader("X-Slash-Gateway-Request-Id", value);
            filter.doFilter(bad, new MockHttpServletResponse(), (req, res) -> { });
        }
        var duplicate = request();
        duplicate.addHeader("X-Slash-Gateway-Request-Id", "Abcd_0123+/-=");
        duplicate.addHeader("X-Slash-Gateway-Request-Id", "Abcd_0123+/-=");
        filter.doFilter(duplicate, new MockHttpServletResponse(), (req, res) -> { });
        assertThat(events.subList(1, events.size())).allSatisfy(event ->
                assertThat(event.gatewayRequestId()).isNull());
    }
}
