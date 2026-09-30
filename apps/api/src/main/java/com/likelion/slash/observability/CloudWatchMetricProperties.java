package com.likelion.slash.observability;

import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.validation.annotation.Validated;

/** Explicit CloudWatch export settings. No AWS credentials are stored here. */
@Validated
@ConfigurationProperties(prefix = "slash.observability.cloudwatch")
public class CloudWatchMetricProperties {

    @NotBlank
    private String namespace = "LambdaOps/Slash";

    @NotBlank
    private String service = "slash-api";

    @NotBlank
    private String environment;

    @Min(60000)
    private long publishIntervalMs = 60000;

    public String getNamespace() {
        return namespace;
    }

    public void setNamespace(String namespace) {
        this.namespace = namespace;
    }

    public String getService() {
        return service;
    }

    public void setService(String service) {
        this.service = service;
    }

    public String getEnvironment() {
        return environment;
    }

    public void setEnvironment(String environment) {
        this.environment = environment;
    }

    public long getPublishIntervalMs() {
        return publishIntervalMs;
    }

    public void setPublishIntervalMs(long publishIntervalMs) {
        this.publishIntervalMs = publishIntervalMs;
    }
}
