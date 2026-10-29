package com.likelion.slash.observability;

import static org.mockito.Mockito.mock;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.jwt;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.likelion.slash.common.error.GlobalExceptionHandler;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Import;
import org.springframework.security.config.Customizer;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.test.context.ContextConfiguration;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.bind.annotation.RestController;

@WebMvcTest
@ContextConfiguration(classes = MissingEndpointContractTest.TestConfig.class)
class MissingEndpointContractTest {
    @Autowired MockMvc mvc;

    @Configuration
    @Import({GlobalExceptionHandler.class, EmptyController.class})
    static class TestConfig {
        @Bean SecurityFilterChain security(HttpSecurity http) throws Exception {
            return http.authorizeHttpRequests(auth -> auth.anyRequest().authenticated())
                    .oauth2ResourceServer(oauth -> oauth.jwt(Customizer.withDefaults()))
                    .build();
        }
        @Bean JwtDecoder jwtDecoder() { return mock(JwtDecoder.class); }
    }

    @RestController static class EmptyController { }

    @Test
    void authenticatedMissingResourceReturns404() throws Exception {
        // The management endpoint is absent from the application listener.
        mvc.perform(get("/actuator/prometheus").with(jwt()))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.error.code").value("RESOURCE_NOT_FOUND"))
                .andExpect(jsonPath("$.error.message").value("대상을 찾을 수 없습니다."));
    }

    @Test
    void missingResourceStillRequiresAuthentication() throws Exception {
        mvc.perform(get("/actuator/prometheus"))
                .andExpect(status().isUnauthorized());
    }

    @Test
    void missingHandlerAlsoReturns404WithoutAStaticResourceMapping() throws Exception {
        var withoutResources = MockMvcBuilders.standaloneSetup(new EmptyController())
                .setControllerAdvice(new GlobalExceptionHandler()).build();
        withoutResources.perform(get("/unknown-endpoint"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.error.code").value("RESOURCE_NOT_FOUND"))
                .andExpect(jsonPath("$.error.message").value("대상을 찾을 수 없습니다."));
    }
}
