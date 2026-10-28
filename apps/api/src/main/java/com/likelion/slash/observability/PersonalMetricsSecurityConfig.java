package com.likelion.slash.observability;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;
import org.springframework.core.annotation.Order;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.web.SecurityFilterChain;

/** Management listener is reachable only from ALB health checks and the monitoring SG. */
@Configuration(proxyBeanMethods = false)
@Profile("personal")
public class PersonalMetricsSecurityConfig {
    @Bean
    @Order(-1)
    SecurityFilterChain personalMetricsSecurityFilterChain(HttpSecurity http) throws Exception {
        http.securityMatcher(request -> request.getLocalPort() == 9091)
                .csrf(csrf -> csrf.disable())
                .sessionManagement(session -> session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                .httpBasic(basic -> basic.disable())
                .formLogin(form -> form.disable())
                .logout(logout -> logout.disable())
                .authorizeHttpRequests(auth -> auth
                        .requestMatchers("/actuator/prometheus", "/actuator/health", "/actuator/health/**").permitAll()
                        .anyRequest().denyAll());
        return http.build();
    }
}
