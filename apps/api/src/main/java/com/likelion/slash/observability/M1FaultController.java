package com.likelion.slash.observability;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import java.util.Map;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Profile;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** Bounded, opt-in fault scenarios. These routes do not exist outside local + m1. */
@RestController
@RequestMapping("/internal/m1")
@Validated
@Profile("local & m1")
@ConditionalOnProperty(name = "slash.observability.faults.enabled", havingValue = "true")
public class M1FaultController {

    private final M1QueryRepository queryRepository;

    public M1FaultController(M1QueryRepository queryRepository) {
        this.queryRepository = queryRepository;
    }

    @GetMapping("/error")
    public ResponseEntity<Map<String, String>> error() {
        return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                .body(Map.of("scenario", "m1-api-error"));
    }

    @GetMapping("/latency")
    public Map<String, Object> latency(@RequestParam(defaultValue = "1500") @Min(0) @Max(5000) int delayMs)
            throws InterruptedException {
        Thread.sleep(delayMs);
        return Map.of("scenario", "m1-api-latency", "delayMs", delayMs);
    }

    @GetMapping("/db-latency")
    public Map<String, Object> dbLatency(@RequestParam(defaultValue = "1500") @Min(0) @Max(5000) int delayMs) {
        queryRepository.sleep(delayMs);
        return Map.of("scenario", "m1-db-latency", "delayMs", delayMs);
    }
}
