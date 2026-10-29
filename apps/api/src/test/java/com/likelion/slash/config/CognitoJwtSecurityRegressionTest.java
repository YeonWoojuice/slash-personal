package com.likelion.slash.config;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.nimbusds.jose.JWSAlgorithm;
import com.nimbusds.jose.JWSHeader;
import com.nimbusds.jose.crypto.RSASSASigner;
import com.nimbusds.jose.jwk.JWKSet;
import com.nimbusds.jose.jwk.RSAKey;
import com.nimbusds.jose.jwk.gen.RSAKeyGenerator;
import com.nimbusds.jwt.JWTClaimsSet;
import com.nimbusds.jwt.SignedJWT;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Date;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.Consumer;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.security.oauth2.jwt.JwtException;

/** Production decoder wiring, including discovery, signatures and combined validators. */
class CognitoJwtSecurityRegressionTest {
    private static final String CLIENT_ID = "security-regression-client";
    private static final AtomicInteger discoveryRequests = new AtomicInteger();
    private static final AtomicInteger jwksRequests = new AtomicInteger();
    private static HttpServer issuerServer;
    private static String issuer;
    private static RSAKey trustedKey;
    private static RSAKey untrustedKey;
    private static JwtDecoder decoder;

    @BeforeAll
    static void startLoopbackIssuer() throws Exception {
        trustedKey = new RSAKeyGenerator(2048).keyID("regression-key").generate();
        // The same key ID prevents rejection merely because the key cannot be found.
        untrustedKey = new RSAKeyGenerator(2048).keyID("regression-key").generate();
        issuerServer = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        issuer = "http://127.0.0.1:" + issuerServer.getAddress().getPort() + "/issuer";
        issuerServer.createContext("/issuer/.well-known/openid-configuration", exchange -> {
            discoveryRequests.incrementAndGet();
            respond(exchange, "{\"issuer\":\"" + issuer + "\",\"jwks_uri\":\""
                    + issuer + "/jwks\",\"id_token_signing_alg_values_supported\":[\"RS256\"]}");
        });
        issuerServer.createContext("/issuer/jwks", exchange -> {
            jwksRequests.incrementAndGet();
            respond(exchange, new JWKSet(trustedKey.toPublicJWK()).toString());
        });
        issuerServer.start();
        try {
            decoder = new CognitoJwtConfig().jwtDecoder(issuer, CLIENT_ID, issuer + "/userinfo");
        } catch (Exception failure) {
            issuerServer.stop(0);
            throw failure;
        }
    }

    @AfterAll
    static void stopLoopbackIssuer() {
        if (issuerServer != null) issuerServer.stop(0);
    }

    @Test
    void acceptsAnAccessTokenSignedByTheDiscoveredIssuer() throws Exception {
        var decoded = decoder.decode(token(trustedKey, claims -> {}));

        assertThat(decoded.getSubject()).isEqualTo("regression-user");
        assertThat(discoveryRequests.get()).isPositive();
        assertThat(jwksRequests.get()).isPositive();
    }

    @Test
    void rejectsADifferentSignatureEvenWithThePublishedKeyId() throws Exception {
        assertRejected(token(untrustedKey, claims -> {}));
    }

    @Test
    void rejectsTheWrongIssuerEvenWithATrustedSignature() throws Exception {
        assertRejected(token(trustedKey, claims -> claims.issuer(issuer + "/other")));
    }

    @Test
    void rejectsAnExpiredTokenBeyondTheClockSkewAllowance() throws Exception {
        assertRejected(token(trustedKey, claims -> claims
                .issueTime(Date.from(Instant.now().minusSeconds(600)))
                .expirationTime(Date.from(Instant.now().minusSeconds(300)))));
    }

    @Test
    void rejectsATokenWhoseNotBeforeTimeIsStillInTheFuture() throws Exception {
        assertRejected(token(trustedKey, claims -> claims
                .notBeforeTime(Date.from(Instant.now().plusSeconds(300)))
                .expirationTime(Date.from(Instant.now().plusSeconds(600)))));
    }

    @Test
    void rejectsASignedIdTokenThroughTheProductionDecoder() throws Exception {
        assertRejected(token(trustedKey, claims -> claims.claim("token_use", "id")));
    }

    @Test
    void rejectsASignedAccessTokenForAnotherClient() throws Exception {
        assertRejected(token(trustedKey, claims -> claims.claim("client_id", "other-client")));
    }

    private static String token(RSAKey signingKey, Consumer<JWTClaimsSet.Builder> customize)
            throws Exception {
        Instant now = Instant.now();
        var claims = new JWTClaimsSet.Builder()
                .issuer(issuer).subject("regression-user")
                .issueTime(Date.from(now.minusSeconds(5)))
                .expirationTime(Date.from(now.plusSeconds(300)))
                .claim("token_use", "access").claim("client_id", CLIENT_ID);
        customize.accept(claims);
        var signed = new SignedJWT(new JWSHeader.Builder(JWSAlgorithm.RS256)
                .keyID(signingKey.getKeyID()).build(), claims.build());
        signed.sign(new RSASSASigner(signingKey));
        return signed.serialize();
    }

    private static void assertRejected(String token) {
        assertThatThrownBy(() -> decoder.decode(token)).isInstanceOf(JwtException.class);
    }

    private static void respond(HttpExchange exchange, String json) throws IOException {
        byte[] body = json.getBytes(StandardCharsets.UTF_8);
        try {
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.sendResponseHeaders(200, body.length);
            exchange.getResponseBody().write(body);
        } finally {
            exchange.close();
        }
    }
}
