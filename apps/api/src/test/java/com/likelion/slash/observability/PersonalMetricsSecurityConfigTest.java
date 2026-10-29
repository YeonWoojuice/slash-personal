package com.likelion.slash.observability;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Import;
import org.springframework.core.annotation.Order;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.ContextConfiguration;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest
@ContextConfiguration(classes = PersonalMetricsSecurityConfigTest.TestConfig.class)
@ActiveProfiles("personal")
class PersonalMetricsSecurityConfigTest {
    @Autowired MockMvc mvc;
    @Configuration
    @Import({PersonalMetricsSecurityConfig.class, Endpoint.class})
    static class TestConfig {
        @Bean @Order(10) SecurityFilterChain fallback(HttpSecurity http) throws Exception {
            return http.authorizeHttpRequests(a -> a.anyRequest().denyAll()).build();
        }
    }
    @RestController static class Endpoint {
        @GetMapping({"/actuator/prometheus", "/actuator/health/liveness", "/api/v1/me"})
        String endpoint() { return "ok"; }
    }
    @Test void metricsAreAllowedOnlyOnManagementPort() throws Exception {
        mvc.perform(get("/actuator/prometheus").with(r -> {r.setLocalPort(9091);return r;})).andExpect(status().isOk());
        mvc.perform(get("/actuator/prometheus").with(r -> {r.setLocalPort(8080);return r;})).andExpect(status().isForbidden());
    }
    @Test void managementPortDoesNotExposeBusinessRoutes() throws Exception {
        mvc.perform(get("/api/v1/me").with(r -> {r.setLocalPort(9091);return r;})).andExpect(status().isForbidden());
    }
    @Test void spoofedForwardedPortDoesNotOpenMetrics() throws Exception {
        mvc.perform(get("/actuator/prometheus").header("X-Forwarded-Port","9091")
                .with(r -> {r.setLocalPort(8080);return r;})).andExpect(status().isForbidden());
    }
    @Test void albLivenessIsAllowedOnManagementPort() throws Exception {
        mvc.perform(get("/actuator/health/liveness").with(r -> {r.setLocalPort(9091);return r;})).andExpect(status().isOk());
    }
}
