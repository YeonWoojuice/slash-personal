package com.likelion.slash.observability;

import io.micrometer.core.instrument.MeterRegistry;
import java.time.Clock;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import software.amazon.awssdk.services.cloudwatch.CloudWatchClient;

/** Creates an AWS client only when explicit metric export is enabled. */
@Configuration(proxyBeanMethods = false)
@ConditionalOnProperty(name = "slash.observability.cloudwatch.enabled", havingValue = "true")
@EnableConfigurationProperties(CloudWatchMetricProperties.class)
public class CloudWatchMetricConfiguration {

    @Bean(destroyMethod = "close")
    CloudWatchClient cloudWatchMetricClient(
            CloudWatchMetricProperties properties,
            @Value("${slash.observability.query-metrics.enabled:false}") boolean queryMetricsEnabled) {
        if (!queryMetricsEnabled) {
            throw new IllegalStateException(
                    "CloudWatch metric export requires slash.observability.query-metrics.enabled=true");
        }
        if (properties.getNamespace().startsWith("AWS/")) {
            throw new IllegalArgumentException("CloudWatch custom metric namespace cannot start with AWS/");
        }
        return CloudWatchClient.create();
    }

    @Bean
    CloudWatchMetricPublisher cloudWatchMetricPublisher(
            MeterRegistry meterRegistry,
            CloudWatchClient cloudWatchMetricClient,
            CloudWatchMetricProperties properties) {
        return new CloudWatchMetricPublisher(meterRegistry, cloudWatchMetricClient, properties, Clock.systemUTC());
    }
}
