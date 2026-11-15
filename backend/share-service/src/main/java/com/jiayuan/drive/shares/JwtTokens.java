package com.jiayuan.drive.shares;

import io.jsonwebtoken.Claims;
import io.jsonwebtoken.JwtException;
import io.jsonwebtoken.JwtParser;
import io.jsonwebtoken.Jwts;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Date;
import javax.crypto.SecretKey;
import javax.crypto.spec.SecretKeySpec;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/** Local HS256 verification: raw UTF-8 key, decimal IDs, zero clock skew, no remote lookup. */
@Component
class JwtTokens {
    private final SecretKey key;
    private final JwtParser parser;
    private final String issuer;
    private final String audience;
    private final long lifetime;

    JwtTokens(@Value("${JWT_SECRET}") String secret, @Value("${JWT_ISSUER}") String issuer,
              @Value("${JWT_AUDIENCE}") String audience, @Value("${JWT_TTL_SECONDS:7200}") long lifetime) {
        byte[] bytes = secret.getBytes(StandardCharsets.UTF_8);
        if (bytes.length < 32 || issuer.isBlank() || audience.isBlank() || lifetime < 1) {
            throw new IllegalArgumentException("Invalid JWT configuration");
        }
        this.key = new SecretKeySpec(bytes, "HmacSHA256");
        this.parser = Jwts.parser().verifyWith(key).requireIssuer(issuer).build();
        this.issuer = issuer;
        this.audience = audience;
        this.lifetime = lifetime;
    }

    Identity verify(String authorization) {
        try {
            if (authorization != null && authorization.startsWith("Bearer ")) {
                var signed = parser.parseSignedClaims(authorization.substring(7));
                Claims claims = signed.getPayload();
                String user = claims.getSubject();
                String account = String.valueOf(claims.get("accountId"));
                Date issued = claims.getIssuedAt();
                Date expires = claims.getExpiration();
                if ("HS256".equals(signed.getHeader().getAlgorithm()) && validId(user) && validId(account)
                        && issued != null && expires != null && !issued.after(new Date())
                        && expires.after(issued) && claims.getAudience() != null
                        && claims.getAudience().contains(audience)) {
                    return new Identity(user, account);
                }
            }
        } catch (JwtException | IllegalArgumentException invalid) {
            // Collapse malformed, forged, expired and incomplete tokens to one public error.
        }
        throw new ApiError(401, "UNAUTHORIZED", "登录凭证无效，请重新登录");
    }

    private boolean validId(String id) {
        return id != null && id.matches("[1-9][0-9]{0,18}") && Long.parseLong(id) > 0;
    }

    record Identity(String userId, String accountId) { }
}
