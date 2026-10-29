package com.likelion.slash.observability;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import ch.qos.logback.classic.Logger;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.read.ListAppender;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import com.likelion.slash.common.error.ApiAccessDeniedHandler;
import com.likelion.slash.common.error.ApiAuthenticationEntryPoint;
import com.likelion.slash.common.error.ErrorCode;
import com.likelion.slash.common.error.GlobalExceptionHandler;
import com.likelion.slash.common.error.SlashException;
import java.util.Map;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Import;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.oauth2.jwt.BadJwtException;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.ContextConfiguration;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RestController;

@WebMvcTest(properties = "personal.request-timing.enabled=true")
@ContextConfiguration(classes = PersonalRequestTimingSecurityTest.TestConfig.class)
@ActiveProfiles("personal")
class PersonalRequestTimingSecurityTest {
    @Autowired MockMvc mvc;
    @Autowired ObjectMapper objectMapper;
    private final Logger logger = (Logger) LoggerFactory.getLogger(PersonalRequestTimingFilter.class);
    private final ListAppender<ILoggingEvent> appender = new ListAppender<>();

    @BeforeEach void capture() { appender.start(); logger.addAppender(appender); }
    @AfterEach void release() { logger.detachAppender(appender); appender.stop(); }

    @Configuration
    @Import({PersonalRequestTimingConfiguration.class, Endpoint.class,
            ApiAuthenticationEntryPoint.class, ApiAccessDeniedHandler.class, GlobalExceptionHandler.class})
    static class TestConfig {
        @Bean SecurityFilterChain security(HttpSecurity http, ApiAuthenticationEntryPoint entryPoint,
                                          ApiAccessDeniedHandler deniedHandler, JwtDecoder decoder) throws Exception {
            return http.authorizeHttpRequests(auth -> auth.anyRequest().hasAuthority("SCOPE_read"))
                    .exceptionHandling(errors -> errors.authenticationEntryPoint(entryPoint)
                            .accessDeniedHandler(deniedHandler))
                    .oauth2ResourceServer(oauth -> oauth.authenticationEntryPoint(entryPoint)
                            .jwt(jwt -> jwt.decoder(decoder)))
                    .build();
        }

        @Bean JwtDecoder decoder() {
            var decoder = mock(JwtDecoder.class);
            when(decoder.decode("valid-reader")).thenReturn(jwt("valid-reader", "read"));
            when(decoder.decode("no-scope")).thenReturn(jwt("no-scope", ""));
            when(decoder.decode("bad-token")).thenThrow(new BadJwtException("private-invalid-token-detail"));
            return decoder;
        }

        private static Jwt jwt(String token, String scope) {
            return Jwt.withTokenValue(token).header("alg", "RS256")
                    .claim("sub", "private-user-id").claim("scope", scope).build();
        }
    }

    @RestController static class Endpoint {
        @GetMapping("/api/v1/me") Map<String, Boolean> me(
                @RequestHeader(value = "X-Test-Failure", defaultValue = "false") boolean failure) {
            if (failure) throw new SlashException(ErrorCode.INTERNAL_ERROR);
            return Map.of("ok", true);
        }
    }

    @Test void recordsMissingToken401BeforeSecurityShortCircuits() throws Exception {
        mvc.perform(get("/api/v1/me").with(r -> { r.setLocalPort(8080); return r; }))
                .andExpect(status().isUnauthorized()).andExpect(header().exists("X-Slash-Request-Id"));
        assertEvent(401);
    }

    @Test void recordsInvalidJwt401WithoutExceptionOrTokenText() throws Exception {
        mvc.perform(get("/api/v1/me").header("Authorization", "Bearer bad-token")
                        .with(r -> { r.setLocalPort(8080); return r; }))
                .andExpect(status().isUnauthorized()).andExpect(header().exists("X-Slash-Request-Id"));
        assertEvent(401);
    }

    @Test void recordsForbidden403WithTheOriginalResponseStatus() throws Exception {
        mvc.perform(get("/api/v1/me").header("Authorization", "Bearer no-scope")
                        .with(r -> { r.setLocalPort(8080); return r; }))
                .andExpect(status().isForbidden()).andExpect(header().exists("X-Slash-Request-Id"));
        assertEvent(403);
    }

    @Test void recordsAuthenticated200AndMatchesTheServerResponseId() throws Exception {
        var result = mvc.perform(get("/api/v1/me").header("Authorization", "Bearer valid-reader")
                        .header("X-Slash-Probe-Id", "f328c97b-779a-4c05-9d4b-7852b58c369d")
                        .header("X-Slash-Gateway-Request-Id", "Gateway_1234=")
                        .with(r -> { r.setLocalPort(8080); return r; }))
                .andExpect(status().isOk()).andExpect(header().doesNotExist("Server-Timing")).andReturn();
        var event = assertEvent(200);
        assertThat(event.get("appRequestId").asText()).isEqualTo(result.getResponse().getHeader("X-Slash-Request-Id"));
        assertThat(event.get("clientProbeId").asText()).isEqualTo("f328c97b-779a-4c05-9d4b-7852b58c369d");
        assertThat(event.get("gatewayRequestId").asText()).isEqualTo("Gateway_1234=");
    }

    @Test void recordsHandled500AfterControllerAdvice() throws Exception {
        mvc.perform(get("/api/v1/me").header("Authorization", "Bearer valid-reader")
                        .header("X-Test-Failure", "true")
                        .with(r -> { r.setLocalPort(8080); return r; }))
                .andExpect(status().isInternalServerError()).andExpect(header().exists("X-Slash-Request-Id"));
        assertEvent(500);
    }

    private JsonNode assertEvent(int status) throws Exception {
        assertThat(appender.list).hasSize(1);
        String message = appender.list.getFirst().getFormattedMessage();
        assertThat(message).doesNotContain("Bearer", "valid-reader", "bad-token", "no-scope",
                "private-user-id", "private-invalid-token-detail");
        var event = objectMapper.readTree(message);
        assertThat(event.properties()).hasSize(8);
        assertThat(event.get("event").asText()).isEqualTo("personal_request_timing");
        assertThat(event.get("status").asInt()).isEqualTo(status);
        assertThat(event.get("durationMs").asDouble()).isGreaterThanOrEqualTo(0.0);
        return event;
    }
}
