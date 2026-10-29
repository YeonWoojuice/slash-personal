package com.likelion.slash.observability;

import com.fasterxml.jackson.annotation.JsonInclude;
import tools.jackson.core.JacksonException;
import tools.jackson.databind.ObjectMapper;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.time.Clock;
import java.time.Instant;
import java.util.Enumeration;
import java.util.UUID;
import java.util.function.Consumer;
import java.util.function.LongSupplier;
import java.util.regex.Pattern;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.web.filter.OncePerRequestFilter;

/** Request correlation for the synchronous personal /me probe, without response buffering. */
public final class PersonalRequestTimingFilter extends OncePerRequestFilter {
    static final String PROBE_HEADER = "X-Slash-Probe-Id";
    static final String REQUEST_HEADER = "X-Slash-Request-Id";
    static final String GATEWAY_HEADER = "X-Slash-Gateway-Request-Id";
    private static final String ROUTE = "/api/v1/me";
    private static final Pattern CANONICAL_UUID = Pattern.compile(
            "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}");
    private static final Pattern GATEWAY_ID = Pattern.compile("[A-Za-z0-9+/_-]{8,126}={0,2}");
    private static final Logger log = LoggerFactory.getLogger(PersonalRequestTimingFilter.class);
    private final int applicationPort;
    private final Clock clock;
    private final LongSupplier nanoTime;
    private final Consumer<TimingEvent> eventSink;

    public PersonalRequestTimingFilter(int applicationPort, ObjectMapper objectMapper) {
        this(applicationPort, Clock.systemUTC(), System::nanoTime, event -> {
            try {
                // The record contains only fixed labels, generated/validated IDs and timings.
                log.info("{}", objectMapper.writeValueAsString(event));
            } catch (JacksonException ignored) {
                // Do not let telemetry serialization replace the application result or expose data.
                log.warn("personal_request_timing_serialization_failed");
            }
        });
    }

    PersonalRequestTimingFilter(int applicationPort, Clock clock, LongSupplier nanoTime,
                                Consumer<TimingEvent> eventSink) {
        this.applicationPort = applicationPort;
        this.clock = clock;
        this.nanoTime = nanoTime;
        this.eventSink = eventSink;
    }

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        return request.getLocalPort() != applicationPort
                || !"GET".equals(request.getMethod())
                || !ROUTE.equals(request.getRequestURI());
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response,
                                    FilterChain filterChain) throws ServletException, IOException {
        String serverRequestId = UUID.randomUUID().toString();
        String probeId = validatedHeader(request, PROBE_HEADER, CANONICAL_UUID);
        String gatewayId = validatedHeader(request, GATEWAY_HEADER, GATEWAY_ID);
        long started = nanoTime.getAsLong();
        response.setHeader(REQUEST_HEADER, serverRequestId);
        boolean returned = false;
        try {
            filterChain.doFilter(request, response);
            returned = true;
        } finally {
            double durationMs = Math.max(0L, nanoTime.getAsLong() - started) / 1_000_000.0;
            // An escaping exception may be turned into a response by the container later.
            // Do not claim that the default status 200 is that final response.
            Integer status = returned || response.isCommitted() ? response.getStatus() : null;
            try {
                eventSink.accept(new TimingEvent("personal_request_timing", Instant.now(clock).toString(),
                        ROUTE, probeId, serverRequestId, gatewayId, status, durationMs));
            } catch (RuntimeException ignored) {
                log.warn("personal_request_timing_record_failed");
            }
        }
    }

    private static String validatedHeader(HttpServletRequest request, String name, Pattern pattern) {
        Enumeration<String> values = request.getHeaders(name);
        if (values == null || !values.hasMoreElements()) return null;
        String value = values.nextElement();
        if (values.hasMoreElements() || value == null || !pattern.matcher(value).matches()) {
            return null;
        }
        return value;
    }

    /** IDs are correlation hints, never authentication or ownership evidence. */
    @JsonInclude(JsonInclude.Include.ALWAYS)
    record TimingEvent(String event, String timestamp, String route, String clientProbeId,
                       String appRequestId, String gatewayRequestId, Integer status, double durationMs) { }
}
