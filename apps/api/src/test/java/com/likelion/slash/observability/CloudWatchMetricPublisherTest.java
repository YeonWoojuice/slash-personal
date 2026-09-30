package com.likelion.slash.observability;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import io.micrometer.core.instrument.Gauge;
import io.micrometer.core.instrument.Timer;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.Function;
import java.util.stream.Collectors;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import software.amazon.awssdk.services.cloudwatch.CloudWatchClient;
import software.amazon.awssdk.services.cloudwatch.model.MetricDatum;
import software.amazon.awssdk.services.cloudwatch.model.PutMetricDataRequest;
import software.amazon.awssdk.services.cloudwatch.model.PutMetricDataResponse;
import software.amazon.awssdk.services.cloudwatch.model.StandardUnit;

class CloudWatchMetricPublisherTest {

    private final SimpleMeterRegistry registry = new SimpleMeterRegistry();
    private final CloudWatchClient client = mock(CloudWatchClient.class);
    private final CloudWatchMetricProperties properties = properties();
    private final CloudWatchMetricPublisher publisher = new CloudWatchMetricPublisher(
            registry, client, properties, Clock.fixed(Instant.parse("2026-09-30T00:00:00Z"), ZoneOffset.UTC));

    @Test
    void publishesOnlySixReviewedMetricsWithServiceAndEnvironmentDimensions() {
        recordHttp("/api/v1/me", "200", 400);
        recordHttp("/internal/m1/error", "500", 1200);
        recordHttp("/actuator/health", "200", 20);
        Timer.builder("slash.db.query").tag("sql", "must-not-export")
                .register(registry).record(Duration.ofMillis(300));
        AtomicInteger active = new AtomicInteger(3);
        Gauge.builder("hikaricp.connections.active", active, AtomicInteger::get)
                .tag("pool", "must-not-export").register(registry);

        publisher.publish();

        PutMetricDataRequest request = captureRequests(1)[0];
        assertThat(request.namespace()).isEqualTo("LambdaOps/Slash");
        Map<String, MetricDatum> data = metrics(request);
        assertThat(data).containsOnlyKeys(
                "RequestCount", "ServerErrorCount", "RequestDurationMsTotal",
                "DBQueryCount", "DBQueryDurationMsTotal", "DBConnectionsActive");
        assertThat(data.get("RequestCount").value()).isEqualTo(2);
        assertThat(data.get("ServerErrorCount").value()).isEqualTo(1);
        assertThat(data.get("RequestDurationMsTotal").value()).isEqualTo(1600);
        assertThat(data.get("DBQueryCount").value()).isEqualTo(1);
        assertThat(data.get("DBQueryDurationMsTotal").value()).isEqualTo(300);
        assertThat(data.get("DBConnectionsActive").value()).isEqualTo(3);
        assertThat(data.get("RequestCount").unit()).isEqualTo(StandardUnit.COUNT);
        assertThat(data.get("RequestDurationMsTotal").unit()).isEqualTo(StandardUnit.MILLISECONDS);
        assertThat(request.metricData()).allSatisfy(datum -> {
            assertThat(datum.dimensions()).hasSize(2);
            assertThat(datum.dimensions()).extracting("name").containsExactly("Service", "Environment");
            assertThat(datum.dimensions()).extracting("value").containsExactly("slash-api", "test");
            assertThat(datum.timestamp()).isEqualTo(Instant.parse("2026-09-30T00:00:00Z"));
        });
    }

    @Test
    void samplesActiveConnectionsEvenInAnIdleInterval() {
        AtomicInteger firstPool = new AtomicInteger(2);
        AtomicInteger secondPool = new AtomicInteger(3);
        Gauge.builder("hikaricp.connections.active", firstPool, AtomicInteger::get)
                .tag("pool", "first").register(registry);
        Gauge.builder("hikaricp.connections.active", secondPool, AtomicInteger::get)
                .tag("pool", "second").register(registry);

        publisher.publish();
        firstPool.set(1);
        secondPool.set(1);
        publisher.publish();

        PutMetricDataRequest[] requests = captureRequests(2);
        assertThat(requests[0].metricData()).hasSize(6);
        assertThat(metrics(requests[0]).get("DBConnectionsActive").value()).isEqualTo(5);
        assertThat(metrics(requests[1]).get("DBConnectionsActive").value()).isEqualTo(2);
        assertThat(metrics(requests[1]).get("DBConnectionsActive").dimensions()).hasSize(2);
    }

    @Test
    void sendsZerosInQuietIntervalsAndOnlyNewDeltasAfterSuccess() {
        publisher.publish();
        recordHttp("/api/v1/me", "200", 100);
        publisher.publish();
        publisher.publish();
        recordHttp("/api/v1/me", "200", 250);
        publisher.publish();

        PutMetricDataRequest[] requests = captureRequests(4);
        assertThat(requests[0].metricData()).hasSize(5);
        assertThat(requests[0].metricData()).allSatisfy(datum -> assertThat(datum.value()).isZero());
        assertThat(metrics(requests[1]).get("RequestCount").value()).isEqualTo(1);
        assertThat(metrics(requests[1]).get("ServerErrorCount").value()).isZero();
        assertThat(metrics(requests[1]).get("RequestDurationMsTotal").value()).isEqualTo(100);
        assertThat(requests[2].metricData()).allSatisfy(datum -> assertThat(datum.value()).isZero());
        assertThat(metrics(requests[3]).get("RequestCount").value()).isEqualTo(1);
        assertThat(metrics(requests[3]).get("ServerErrorCount").value()).isZero();
        assertThat(metrics(requests[3]).get("RequestDurationMsTotal").value()).isEqualTo(250);
        assertThat(requests[3].metricData()).hasSize(5);
    }

    @Test
    void retriesTheOriginalIntervalBeforeAdvancingAcceptedCounters() {
        when(client.putMetricData(any(PutMetricDataRequest.class)))
                .thenThrow(new IllegalStateException("temporary CloudWatch failure"))
                .thenReturn(PutMetricDataResponse.builder().build());
        recordHttp("/api/v1/me", "200", 100);
        publisher.publish();

        recordHttp("/api/v1/me", "200", 200);
        publisher.publish();
        publisher.publish();

        PutMetricDataRequest[] requests = captureRequests(3);
        assertThat(requests[1]).isEqualTo(requests[0]);
        assertThat(metrics(requests[2]).get("RequestCount").value()).isEqualTo(1);
        assertThat(metrics(requests[2]).get("RequestDurationMsTotal").value()).isEqualTo(200);
    }

    private void recordHttp(String route, String status, long milliseconds) {
        Timer.builder("http.server.requests")
                .tag("uri", route)
                .tag("status", status)
                .tag("version", "should-not-export")
                .register(registry)
                .record(Duration.ofMillis(milliseconds));
    }

    private PutMetricDataRequest[] captureRequests(int count) {
        ArgumentCaptor<PutMetricDataRequest> captor = ArgumentCaptor.forClass(PutMetricDataRequest.class);
        verify(client, times(count)).putMetricData(captor.capture());
        return captor.getAllValues().toArray(PutMetricDataRequest[]::new);
    }

    private Map<String, MetricDatum> metrics(PutMetricDataRequest request) {
        return request.metricData().stream()
                .collect(Collectors.toMap(MetricDatum::metricName, Function.identity()));
    }

    private static CloudWatchMetricProperties properties() {
        CloudWatchMetricProperties properties = new CloudWatchMetricProperties();
        properties.setEnvironment("test");
        return properties;
    }
}
