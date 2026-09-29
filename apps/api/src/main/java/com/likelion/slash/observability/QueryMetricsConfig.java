package com.likelion.slash.observability;

import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import java.util.Arrays;
import org.jooq.ExecuteContext;
import org.jooq.ExecuteListener;
import org.jooq.ExecuteListenerProvider;
import org.jooq.impl.DefaultExecuteListenerProvider;
import org.springframework.boot.autoconfigure.jooq.DefaultConfigurationCustomizer;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;

/** Times jOOQ queries without recording SQL text, bind values, or user identifiers. */
@Configuration
@Profile("local & m1")
public class QueryMetricsConfig {

    @Bean
    DefaultConfigurationCustomizer queryMetricsCustomizer(MeterRegistry registry) {
        Timer timer = Timer.builder("slash.db.query")
                .description("Elapsed time for a jOOQ query, including result fetch")
                .publishPercentileHistogram()
                .register(registry);

        ExecuteListener listener = new ExecuteListener() {
            private static final String SAMPLE_KEY = "slash.observability.query.timer";

            @Override
            public void start(ExecuteContext context) {
                context.data(SAMPLE_KEY, Timer.start(registry));
            }

            @Override
            public void end(ExecuteContext context) {
                Object value = context.data(SAMPLE_KEY);
                if (value instanceof Timer.Sample sample) {
                    sample.stop(timer);
                }
            }
        };

        return configuration -> {
            ExecuteListenerProvider[] existing = configuration.executeListenerProviders();
            ExecuteListenerProvider[] providers = Arrays.copyOf(existing, existing.length + 1);
            providers[existing.length] = new DefaultExecuteListenerProvider(listener);
            configuration.set(providers);
        };
    }
}
