package com.likelion.slash.observability;

import org.jooq.DSLContext;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Repository;

/** Runs only a bounded, parameterized PostgreSQL delay for the M1 experiment. */
@Repository
@Profile("local & m1")
@ConditionalOnProperty(name = "slash.observability.faults.enabled", havingValue = "true")
public class M1QueryRepository {

    private final DSLContext dsl;

    public M1QueryRepository(DSLContext dsl) {
        this.dsl = dsl;
    }

    public void sleep(int delayMs) {
        dsl.fetch("select pg_sleep(?)", delayMs / 1000.0);
    }
}
