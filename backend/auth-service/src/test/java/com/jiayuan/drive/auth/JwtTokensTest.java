package com.jiayuan.drive.auth;

import io.jsonwebtoken.Jwts;
import java.time.Instant;
import java.util.Date;
import java.util.UUID;
import javax.crypto.spec.SecretKeySpec;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class JwtTokensTest {
    private final String secret = UUID.randomUUID().toString() + UUID.randomUUID();
    private final JwtTokens tokens = new JwtTokens(secret, "issuer", "audience", 7200);

    @Test
    void roundTripAndIncompleteOrForgedClaims() {
        String valid = tokens.issue("9007199254740993", "2");
        assertEquals("9007199254740993", tokens.verify("Bearer " + valid).userId());
        assertThrows(ApiError.class, () -> tokens.verify(null));
        assertThrows(ApiError.class, () -> tokens.verify("Bearer " + valid + "x"));
        assertThrows(ApiError.class, () -> new JwtTokens(secret, "issuer", "wrong", 7200).verify("Bearer " + valid));
        assertThrows(ApiError.class, () -> new JwtTokens(secret, "wrong", "audience", 7200).verify("Bearer " + valid));
        for (int mode = 0; mode < 4; mode++) {
            Instant now = Instant.now();
            var builder = Jwts.builder().subject("1").issuer("issuer").audience().add("audience").and();
            if (mode != 0) { builder.claim("accountId", "2"); }
            if (mode != 1) { builder.issuedAt(Date.from(now.plusSeconds(mode == 2 ? 300 : -60))); }
            builder.expiration(Date.from(now.plusSeconds(mode == 3 ? -1 : 7200)));
            String invalid = builder.signWith(new SecretKeySpec(secret.getBytes(java.nio.charset.StandardCharsets.UTF_8),
                    "HmacSHA256"), Jwts.SIG.HS256).compact();
            assertThrows(ApiError.class, () -> tokens.verify("Bearer " + invalid));
        }
    }
}
