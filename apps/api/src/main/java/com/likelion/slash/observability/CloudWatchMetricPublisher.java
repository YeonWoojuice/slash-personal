package com.likelion.slash.observability;

import io.micrometer.core.instrument.Gauge;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import java.time.Clock;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.TimeUnit;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import software.amazon.awssdk.services.cloudwatch.CloudWatchClient;
import software.amazon.awssdk.services.cloudwatch.model.Dimension;
import software.amazon.awssdk.services.cloudwatch.model.MetricDatum;
import software.amazon.awssdk.services.cloudwatch.model.PutMetricDataRequest;
import software.amazon.awssdk.services.cloudwatch.model.StandardUnit;

/**
 * Sends only six reviewed series. Micrometer's route/status/version/pool labels are never
 * copied to CloudWatch, and histogram buckets are never exported as custom metrics.
 */
public class CloudWatchMetricPublisher {

    private static final Logger log = LoggerFactory.getLogger(CloudWatchMetricPublisher.class);

    private final MeterRegistry registry;
    private final CloudWatchClient client;
    private final CloudWatchMetricProperties properties;
    private final Clock clock;
    private Totals accepted = Totals.ZERO;
    private Pending pending;

    CloudWatchMetricPublisher(
            MeterRegistry registry,
            CloudWatchClient client,
            CloudWatchMetricProperties properties,
            Clock clock) {
        this.registry = registry;
        this.client = client;
        this.properties = properties;
        this.clock = clock;
    }

    @Scheduled(
            initialDelayString = "${slash.observability.cloudwatch.publish-interval-ms:60000}",
            fixedDelayString = "${slash.observability.cloudwatch.publish-interval-ms:60000}")
    public synchronized void publish() {
        if (pending == null) {
            Totals current = readTotals();
            Totals delta = current.since(accepted);
            List<MetricDatum> data = toMetricData(delta, readActiveConnections(), clock.instant());
            pending = new Pending(current, PutMetricDataRequest.builder()
                    .namespace(properties.getNamespace())
                    .metricData(data)
                    .build());
        }

        try {
            client.putMetricData(pending.request());
            accepted = pending.totals();
            pending = null;
        } catch (RuntimeException e) {
            // Retry the exact same time-stamped interval on the next tick. Do not advance the
            // accepted counters until PutMetricData succeeds.
            log.warn("CloudWatch metric publication failed; will retry the same interval", e);
        }
    }

    private Totals readTotals() {
        long requests = 0;
        long serverErrors = 0;
        double requestDurationMs = 0;
        for (Timer timer : registry.find("http.server.requests").timers()) {
            String route = timer.getId().getTag("uri");
            if (route != null && route.startsWith("/actuator")) {
                continue;
            }
            long count = timer.count();
            requests += count;
            requestDurationMs += timer.totalTime(TimeUnit.MILLISECONDS);
            String status = timer.getId().getTag("status");
            if (status != null && status.startsWith("5")) {
                serverErrors += count;
            }
        }

        long dbQueries = 0;
        double dbDurationMs = 0;
        for (Timer timer : registry.find("slash.db.query").timers()) {
            dbQueries += timer.count();
            dbDurationMs += timer.totalTime(TimeUnit.MILLISECONDS);
        }
        return new Totals(requests, serverErrors, requestDurationMs, dbQueries, dbDurationMs);
    }

    private Double readActiveConnections() {
        double active = 0;
        boolean found = false;
        for (Gauge gauge : registry.find("hikaricp.connections.active").gauges()) {
            double value = gauge.value();
            if (Double.isFinite(value) && value >= 0) {
                active += value;
                found = true;
            }
        }
        return found ? active : null;
    }

    private List<MetricDatum> toMetricData(Totals delta, Double activeConnections, Instant timestamp) {
        List<MetricDatum> data = new ArrayList<>(6);
        // Zeroes mark an observed quiet interval rather than missing telemetry.
        data.add(datum("RequestCount", delta.requests(), StandardUnit.COUNT, timestamp));
        data.add(datum("ServerErrorCount", delta.serverErrors(), StandardUnit.COUNT, timestamp));
        data.add(datum("RequestDurationMsTotal", delta.requestDurationMs(), StandardUnit.MILLISECONDS, timestamp));
        data.add(datum("DBQueryCount", delta.dbQueries(), StandardUnit.COUNT, timestamp));
        data.add(datum("DBQueryDurationMsTotal", delta.dbDurationMs(), StandardUnit.MILLISECONDS, timestamp));
        if (activeConnections != null) {
            data.add(datum("DBConnectionsActive", activeConnections, StandardUnit.COUNT, timestamp));
        }
        return data;
    }

    private MetricDatum datum(String name, double value, StandardUnit unit, Instant timestamp) {
        return MetricDatum.builder()
                .metricName(name)
                .dimensions(
                        Dimension.builder().name("Service").value(properties.getService()).build(),
                        Dimension.builder().name("Environment").value(properties.getEnvironment()).build())
                .timestamp(timestamp)
                .unit(unit)
                .value(value)
                .build();
    }

    private record Pending(Totals totals, PutMetricDataRequest request) {}

    private record Totals(
            long requests, long serverErrors, double requestDurationMs,
            long dbQueries, double dbDurationMs) {
        private static final Totals ZERO = new Totals(0, 0, 0, 0, 0);

        private Totals since(Totals previous) {
            return new Totals(
                    difference(requests, previous.requests),
                    difference(serverErrors, previous.serverErrors),
                    difference(requestDurationMs, previous.requestDurationMs),
                    difference(dbQueries, previous.dbQueries),
                    difference(dbDurationMs, previous.dbDurationMs));
        }

        private static long difference(long current, long previous) {
            return current >= previous ? current - previous : current;
        }

        private static double difference(double current, double previous) {
            return current >= previous ? current - previous : current;
        }
    }
}
