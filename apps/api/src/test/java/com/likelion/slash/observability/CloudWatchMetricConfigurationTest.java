package com.likelion.slash.observability;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import software.amazon.awssdk.services.cloudwatch.CloudWatchClient;

class CloudWatchMetricConfigurationTest {

    @Test
    void createsNeitherAwsClientNorPublisherWithoutExplicitOptIn() {
        new ApplicationContextRunner()
                .withUserConfiguration(CloudWatchMetricConfiguration.class)
                .run(context -> {
                    assertThat(context).doesNotHaveBean(CloudWatchClient.class);
                    assertThat(context).doesNotHaveBean(CloudWatchMetricPublisher.class);
                });
    }

    @Test
    void rejectsCloudWatchExportWithoutDbQueryInstrumentation() {
        new ApplicationContextRunner()
                .withUserConfiguration(CloudWatchMetricConfiguration.class)
                .withPropertyValues(
                        "slash.observability.cloudwatch.enabled=true",
                        "slash.observability.cloudwatch.environment=test")
                .run(context -> {
                    assertThat(context).hasFailed();
                    assertThat(context.getStartupFailure())
                            .hasRootCauseInstanceOf(IllegalStateException.class)
                            .hasMessageContaining("CloudWatch metric export requires");
                });
    }
}
