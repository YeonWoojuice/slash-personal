package com.likelion.slash.observability;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.mockStatic;
import static org.mockito.Mockito.verify;

import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import java.io.IOException;
import java.time.Duration;
import java.util.HashMap;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.boot.context.properties.bind.validation.BindValidationException;
import org.springframework.boot.env.YamlPropertySourceLoader;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.core.env.StandardEnvironment;
import org.springframework.core.env.SystemEnvironmentPropertySource;
import org.springframework.core.io.ClassPathResource;
import software.amazon.awssdk.services.cloudwatch.CloudWatchClient;
import software.amazon.awssdk.services.cloudwatch.model.PutMetricDataRequest;

class PersonalCloudWatchConfigurationTest {

    @Test
    void personalProfileDoesNotPublishUnlessEcsExplicitlyEnablesIt() {
        personalContext(Map.of()).run(context -> {
            assertThat(context).hasNotFailed();
            assertThat(context).doesNotHaveBean(CloudWatchClient.class);
            assertThat(context).doesNotHaveBean(CloudWatchMetricPublisher.class);
        });
    }

    @Test
    void ecsEnvironmentOverridesPersonalDefaultsAndPublishesTheM2Contract() {
        CloudWatchClient client = mock(CloudWatchClient.class);
        try (var awsClientFactory = mockStatic(CloudWatchClient.class)) {
            awsClientFactory.when(CloudWatchClient::create).thenReturn(client);

            personalContext(ecsEnvironment()).run(context -> {
                assertThat(context).hasNotFailed();
                assertThat(context).hasSingleBean(CloudWatchMetricPublisher.class);
                CloudWatchMetricProperties properties = context.getBean(CloudWatchMetricProperties.class);
                assertThat(properties.getNamespace()).isEqualTo("LambdaOps/Slash");
                assertThat(properties.getService()).isEqualTo("slash-api");
                assertThat(properties.getEnvironment()).isEqualTo("dev");
                assertThat(properties.getPublishIntervalMs()).isEqualTo(60000);
                assertThat(context.getEnvironment().getProperty("management.metrics.tags.environment"))
                        .isEqualTo("personal");

                MeterRegistry registry = context.getBean(MeterRegistry.class);
                Timer.builder("http.server.requests")
                        .tag("uri", "/api/v1/me")
                        .tag("status", "200")
                        .register(registry)
                        .record(Duration.ofMillis(25));
                context.getBean(CloudWatchMetricPublisher.class).publish();

                ArgumentCaptor<PutMetricDataRequest> request = ArgumentCaptor.forClass(PutMetricDataRequest.class);
                verify(client).putMetricData(request.capture());
                assertThat(request.getValue().namespace()).isEqualTo("LambdaOps/Slash");
                assertThat(request.getValue().metricData()).hasSize(5).allSatisfy(datum -> {
                    assertThat(datum.dimensions()).extracting("name")
                            .containsExactly("Service", "Environment");
                    assertThat(datum.dimensions()).extracting("value")
                            .containsExactly("slash-api", "dev");
                });
            });
        }
    }

    @Test
    void enabledExportRejectsMissingCloudWatchEnvironment() {
        Map<String, Object> environment = ecsEnvironment();
        environment.remove("SLASH_OBSERVABILITY_CLOUDWATCH_ENVIRONMENT");

        try (var awsClientFactory = mockStatic(CloudWatchClient.class)) {
            personalContext(environment).run(context -> {
                assertThat(context).hasFailed();
                assertThat(context.getStartupFailure()).hasRootCauseInstanceOf(BindValidationException.class);
                assertThat(context.getStartupFailure()).hasStackTraceContaining("environment");
            });
            awsClientFactory.verifyNoInteractions();
        }
    }

    @Test
    void enabledExportRejectsSubMinuteIntervalFromEcsEnvironment() {
        Map<String, Object> environment = ecsEnvironment();
        environment.put("SLASH_OBSERVABILITY_CLOUDWATCH_PUBLISHINTERVALMS", "1000");

        try (var awsClientFactory = mockStatic(CloudWatchClient.class)) {
            personalContext(environment).run(context -> {
                assertThat(context).hasFailed();
                assertThat(context.getStartupFailure()).hasRootCauseInstanceOf(BindValidationException.class);
                assertThat(context.getStartupFailure()).hasStackTraceContaining("publishIntervalMs");
            });
            awsClientFactory.verifyNoInteractions();
        }
    }

    private ApplicationContextRunner personalContext(Map<String, Object> environment) {
        return new ApplicationContextRunner()
                .withInitializer(context -> {
                    var sources = context.getEnvironment().getPropertySources();
                    sources.remove(StandardEnvironment.SYSTEM_ENVIRONMENT_PROPERTY_SOURCE_NAME);
                    sources.addFirst(new SystemEnvironmentPropertySource(
                            StandardEnvironment.SYSTEM_ENVIRONMENT_PROPERTY_SOURCE_NAME, environment));
                    try {
                        var yaml = new YamlPropertySourceLoader().load(
                                "personal", new ClassPathResource("application-personal.yml"));
                        yaml.forEach(sources::addLast);
                    } catch (IOException e) {
                        throw new IllegalStateException("Cannot load personal profile configuration", e);
                    }
                })
                .withUserConfiguration(CloudWatchMetricConfiguration.class)
                .withBean(MeterRegistry.class, SimpleMeterRegistry::new);
    }

    private Map<String, Object> ecsEnvironment() {
        return new HashMap<>(Map.of(
                "SLASH_OBSERVABILITY_CLOUDWATCH_ENABLED", "true",
                "SLASH_OBSERVABILITY_CLOUDWATCH_NAMESPACE", "LambdaOps/Slash",
                "SLASH_OBSERVABILITY_CLOUDWATCH_SERVICE", "slash-api",
                "SLASH_OBSERVABILITY_CLOUDWATCH_ENVIRONMENT", "dev",
                "SLASH_OBSERVABILITY_CLOUDWATCH_PUBLISHINTERVALMS", "60000",
                "SLASH_OBSERVABILITY_QUERYMETRICS_ENABLED", "true"));
    }
}
