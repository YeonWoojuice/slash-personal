package com.likelion.slash.config;

import java.util.Arrays;
import org.springframework.beans.factory.InitializingBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;
import org.springframework.core.env.Environment;
import org.springframework.security.oauth2.jwt.JwtDecoder;

/** Fail closed before serving the personal AWS environment. */
@Configuration(proxyBeanMethods = false)
@Profile("personal")
public class PersonalRuntimeConfig {
    public PersonalRuntimeConfig(Environment environment) {
        validate(environment);
    }

    static void validate(Environment env) {
        if (Arrays.stream(env.getActiveProfiles()).anyMatch(p -> !p.equals("personal"))) {
            throw new IllegalStateException("personal must run alone; local/m1/dev/demo profiles are forbidden");
        }
        for (String property : new String[] {
                "spring.security.oauth2.resourceserver.jwt.issuer-uri",
                "slash.auth.cognito.client-id", "slash.auth.cognito.user-info-uri"}) {
            if (env.getProperty(property, "").isBlank()) {
                throw new IllegalStateException("Missing personal authentication setting: " + property);
            }
        }
        if (env.getProperty("slash.auth.local-dev-token.enabled", Boolean.class, false)
                || env.getProperty("slash.observability.faults.enabled", Boolean.class, false)) {
            throw new IllegalStateException("Personal runtime forbids local authentication and fault injection");
        }
        if (env.getProperty("management.server.port", Integer.class, 0) != 9091
                || env.getProperty("server.port", Integer.class, 8080) != 8080) {
            throw new IllegalStateException("Personal runtime requires API 8080 and internal management 9091");
        }
    }

    // Requiring this bean prevents a missing decoder from becoming a partially authenticated runtime.
    @Bean
    InitializingBean personalJwtRequired(JwtDecoder decoder) {
        return () -> { };
    }
}
