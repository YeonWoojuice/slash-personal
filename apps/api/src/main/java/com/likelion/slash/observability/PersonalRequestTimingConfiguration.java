package com.likelion.slash.observability;

import tools.jackson.databind.ObjectMapper;
import jakarta.servlet.DispatcherType;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.security.autoconfigure.web.servlet.SecurityFilterProperties;
import org.springframework.boot.web.servlet.FilterRegistrationBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;

/** Opt-in measurements for the bounded personal request probe. */
@Configuration(proxyBeanMethods = false)
@Profile("personal")
@ConditionalOnProperty(name = "personal.request-timing.enabled", havingValue = "true")
public class PersonalRequestTimingConfiguration {
    @Bean
    FilterRegistrationBean<PersonalRequestTimingFilter> personalRequestTimingRegistration(
            ObjectMapper objectMapper, @Value("${server.port:8080}") int applicationPort,
            @Value("${spring.security.filter.order:" + SecurityFilterProperties.DEFAULT_FILTER_ORDER + "}")
            int securityFilterOrder) {
        var registration = new FilterRegistrationBean<>(
                new PersonalRequestTimingFilter(applicationPort, objectMapper));
        registration.setName("personalRequestTiming");
        registration.setOrder(Math.subtractExact(securityFilterOrder, 1));
        registration.setDispatcherTypes(DispatcherType.REQUEST);
        registration.addUrlPatterns("/api/v1/me");
        return registration;
    }
}
