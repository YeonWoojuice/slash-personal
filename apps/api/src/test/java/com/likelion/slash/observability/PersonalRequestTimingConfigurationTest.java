package com.likelion.slash.observability;

import static org.assertj.core.api.Assertions.assertThat;

import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.json.JsonMapper;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.boot.security.autoconfigure.web.servlet.SecurityFilterProperties;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.boot.web.servlet.FilterRegistrationBean;
import org.springframework.core.env.StandardEnvironment;
import org.springframework.core.env.SystemEnvironmentPropertySource;

class PersonalRequestTimingConfigurationTest {
    private final ApplicationContextRunner context = new ApplicationContextRunner()
            .withUserConfiguration(PersonalRequestTimingConfiguration.class)
            .withBean(ObjectMapper.class, () -> JsonMapper.builder().configureForJackson2().build());

    @Test void remainsOffWithoutExplicitEnablement() {
        context.withPropertyValues("spring.profiles.active=personal").run(c ->
                assertThat(c).doesNotHaveBean(FilterRegistrationBean.class));
    }

    @Test void remainsOffOutsidePersonalEvenWhenEnabled() {
        context.withPropertyValues("personal.request-timing.enabled=true").run(c ->
                assertThat(c).doesNotHaveBean(FilterRegistrationBean.class));
    }

    @Test void registersOnceBeforeSecurityAndOnlyForTheProbePath() {
        context.withPropertyValues("spring.profiles.active=personal", "personal.request-timing.enabled=true")
                .run(c -> {
                    assertThat(c).hasSingleBean(FilterRegistrationBean.class);
                    var registration = c.getBean(FilterRegistrationBean.class);
                    assertThat(registration.getOrder()).isEqualTo(SecurityFilterProperties.DEFAULT_FILTER_ORDER - 1);
                    assertThat(registration.getUrlPatterns()).containsExactly("/api/v1/me");
                    // The filter is deliberately not also a separately auto-registered bean.
                    assertThat(c).doesNotHaveBean(PersonalRequestTimingFilter.class);
                });
    }

    @Test void honorsTheConfiguredSecurityOrderAndEcsEnvironmentSwitch() {
        context.withInitializer(c -> c.getEnvironment().getPropertySources().addFirst(
                        new SystemEnvironmentPropertySource(StandardEnvironment.SYSTEM_ENVIRONMENT_PROPERTY_SOURCE_NAME,
                                Map.of("PERSONAL_REQUEST_TIMING_ENABLED", "true"))))
                .withPropertyValues("spring.profiles.active=personal", "spring.security.filter.order=-150")
                .run(c -> {
                    assertThat(c).hasSingleBean(FilterRegistrationBean.class);
                    assertThat(c.getBean(FilterRegistrationBean.class).getOrder()).isEqualTo(-151);
                });
    }
}
