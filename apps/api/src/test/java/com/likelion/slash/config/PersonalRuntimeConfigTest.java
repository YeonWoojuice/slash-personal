package com.likelion.slash.config;

import org.junit.jupiter.api.Test;
import org.springframework.mock.env.MockEnvironment;
import static org.assertj.core.api.Assertions.*;

class PersonalRuntimeConfigTest {
    private MockEnvironment valid() {
        var env = new MockEnvironment()
                .withProperty("spring.security.oauth2.resourceserver.jwt.issuer-uri", "https://example.test/pool")
                .withProperty("slash.auth.cognito.client-id", "test-client")
                .withProperty("slash.auth.cognito.user-info-uri", "https://example.test/userInfo")
                .withProperty("management.server.port", "9091");
        env.setActiveProfiles("personal");
        return env;
    }
    @Test void validPersonalConfiguration() {
        assertThatCode(() -> PersonalRuntimeConfig.validate(valid())).doesNotThrowAnyException();
    }
    @Test void rejectsLocalProfileEvenWhenPersonalIsActive() {
        var env=valid(); env.setActiveProfiles("personal", "local", "m1");
        assertThatThrownBy(() -> PersonalRuntimeConfig.validate(env)).isInstanceOf(IllegalStateException.class);
    }
    @Test void rejectsMissingAuthentication() {
        for (String key : new String[]{"spring.security.oauth2.resourceserver.jwt.issuer-uri", "slash.auth.cognito.client-id", "slash.auth.cognito.user-info-uri"}) {
            var env=valid().withProperty(key, "");
            assertThatThrownBy(() -> PersonalRuntimeConfig.validate(env)).isInstanceOf(IllegalStateException.class);
        }
    }
    @Test void rejectsFaultInjectionAndLocalTokens() {
        for (String key : new String[]{"slash.auth.local-dev-token.enabled", "slash.observability.faults.enabled"}) {
            var env=valid().withProperty(key, "true");
            assertThatThrownBy(() -> PersonalRuntimeConfig.validate(env)).isInstanceOf(IllegalStateException.class);
        }
    }
    @Test void rejectsSharedManagementPort() {
        var env=valid().withProperty("management.server.port", "8080");
        assertThatThrownBy(() -> PersonalRuntimeConfig.validate(env)).isInstanceOf(IllegalStateException.class);
    }
}
