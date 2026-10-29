package com.likelion.slash.config;

import static org.assertj.core.api.Assertions.assertThat;
import static org.hamcrest.Matchers.containsString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.likelion.slash.common.error.ApiAccessDeniedHandler;
import com.likelion.slash.common.error.ApiAuthenticationEntryPoint;
import com.likelion.slash.common.error.ErrorCode;
import com.likelion.slash.common.error.GlobalExceptionHandler;
import com.likelion.slash.common.error.SlashException;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.boot.test.context.TestComponent;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.security.oauth2.jwt.BadJwtException;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.ContextConfiguration;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.ResultActions;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

/** Verify response protection through the application's actual SecurityFilterChain. */
@WebMvcTest
@ContextConfiguration(classes = {SecurityConfig.class,
        SecurityResponseHeadersRegressionTest.TestConfig.class})
@ActiveProfiles("personal")
class SecurityResponseHeadersRegressionTest {
    @Autowired MockMvc mvc;

    @TestConfiguration(proxyBeanMethods = false)
    @Import({CorsConfig.class, Endpoint.class,
            ApiAuthenticationEntryPoint.class, ApiAccessDeniedHandler.class, GlobalExceptionHandler.class})
    static class TestConfig {
        @Bean JwtDecoder decoder() {
            // Signature verification is exercised separately by CognitoJwtSecurityRegressionTest.
            var decoder = mock(JwtDecoder.class);
            when(decoder.decode("valid-token")).thenReturn(Jwt.withTokenValue("valid-token")
                    .header("alg", "RS256").subject("regression-user").build());
            when(decoder.decode("invalid-token")).thenThrow(new BadJwtException("invalid signature"));
            return decoder;
        }
    }

    @RestController
    @TestComponent
    static class Endpoint {
        @GetMapping("/api/v1/regression/ok")
        Map<String, Boolean> ok() {
            return Map.of("ok", true);
        }

        @GetMapping("/api/v1/regression/forbidden")
        void forbidden() {
            throw new SlashException(ErrorCode.FORBIDDEN);
        }

        @GetMapping("/api/v1/regression/failure")
        void failure() {
            throw new SlashException(ErrorCode.INTERNAL_ERROR);
        }

        @GetMapping("/api/v1/regression/committed")
        void committed(HttpServletResponse response) throws IOException {
            response.setContentType("application/json");
            response.getWriter().write("{\"ok\":true}");
            response.flushBuffer();
        }
    }

    @Test
    void protectsAnAuthenticatedResponseWithoutCreatingASession() throws Exception {
        var result = protectedResponse(mvc.perform(get("/api/v1/regression/ok")
                        .header("Authorization", "Bearer valid-token")))
                .andExpect(status().isOk()).andReturn();

        assertThat(result.getRequest().getSession(false)).isNull();
        assertThat(result.getResponse().getHeaders("Set-Cookie")).isEmpty();
    }

    @Test
    void protectsTheMissingTokenResponseProducedBeforeTheController() throws Exception {
        protectedResponse(mvc.perform(get("/api/v1/regression/ok")))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.error.code").value("AUTH_REQUIRED"));
    }

    @Test
    void protectsAnInvalidJwtResponseFromTheResourceServerEntryPoint() throws Exception {
        protectedResponse(mvc.perform(get("/api/v1/regression/ok")
                        .header("Authorization", "Bearer invalid-token")))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.error.code").value("AUTH_REQUIRED"));
    }

    @Test
    void protectsAForbiddenResponseFromTheApplication() throws Exception {
        protectedResponse(mvc.perform(get("/api/v1/regression/forbidden")
                        .header("Authorization", "Bearer valid-token")))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.error.code").value("FORBIDDEN"));
    }

    @Test
    void protectsAnErrorResponseHandledByTheControllerAdvice() throws Exception {
        protectedResponse(mvc.perform(get("/api/v1/regression/failure")
                        .header("Authorization", "Bearer valid-token")))
                .andExpect(status().isInternalServerError())
                .andExpect(jsonPath("$.error.code").value("INTERNAL_ERROR"));
    }

    @Test
    void writesProtectionHeadersBeforeTheResponseIsCommitted() throws Exception {
        var result = protectedResponse(mvc.perform(get("/api/v1/regression/committed")
                        .header("Authorization", "Bearer valid-token")))
                .andExpect(status().isOk()).andReturn();

        assertThat(result.getResponse().isCommitted()).isTrue();
    }

    @Test
    void writesHstsForASecureRequestEvenWhenAuthenticationFails() throws Exception {
        protectedResponse(mvc.perform(get("/api/v1/regression/ok").secure(true)))
                .andExpect(status().isUnauthorized())
                .andExpect(header().string("Strict-Transport-Security", containsString("max-age=")))
                .andExpect(header().string("Strict-Transport-Security", containsString("includeSubDomains")));
    }

    @Test
    void doesNotTreatAnUntrustedForwardedHeaderAsASecureConnection() throws Exception {
        protectedResponse(mvc.perform(get("/api/v1/regression/ok")
                        .header("Authorization", "Bearer valid-token")
                        .header("X-Forwarded-Proto", "https")))
                .andExpect(status().isOk())
                .andExpect(header().doesNotExist("Strict-Transport-Security"));
    }

    private static ResultActions protectedResponse(ResultActions result) throws Exception {
        return result.andExpect(header().string("X-Content-Type-Options", "nosniff"))
                .andExpect(header().string("X-Frame-Options", "DENY"))
                .andExpect(header().string("Cache-Control", containsString("no-store")))
                .andExpect(header().string("Cache-Control", containsString("no-cache")))
                .andExpect(header().string("Pragma", "no-cache"))
                .andExpect(header().string("Expires", "0"));
    }
}
