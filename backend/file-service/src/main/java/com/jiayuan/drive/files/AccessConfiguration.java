package com.jiayuan.drive.files;

import io.jsonwebtoken.Claims;
import io.jsonwebtoken.JwtException;
import io.jsonwebtoken.JwtParser;
import io.jsonwebtoken.Jwts;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.HandlerInterceptor;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

@Configuration
class AccessConfiguration implements WebMvcConfigurer {
    private final JwtParser parser;
    private final String audience;
    private final byte[] internalToken;

    AccessConfiguration(@Value("${file-service.jwt-secret}") String secret,
                        @Value("${file-service.jwt-issuer}") String issuer,
                        @Value("${file-service.jwt-audience}") String audience,
                        @Value("${file-service.internal-token}") String token) {
        byte[] bytes = secret.getBytes(StandardCharsets.UTF_8);
        if (bytes.length < 32 || token.isBlank() || token.equals(secret)
                || issuer.isBlank() || audience.isBlank()) {
            throw new IllegalArgumentException("Invalid JWT or internal token configuration");
        }
        this.parser = Jwts.parser().verifyWith(new SecretKeySpec(bytes, "HmacSHA256"))
                .requireIssuer(issuer).build();
        this.audience = audience;
        this.internalToken = token.getBytes(StandardCharsets.UTF_8);
    }

    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        registry.addInterceptor(new HandlerInterceptor() {
            @Override
            public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) {
                request.setAttribute("fileOwner", owner(request.getHeader("Authorization")));
                return true;
            }
        }).addPathPatterns("/api/v1/**");

        registry.addInterceptor(new HandlerInterceptor() {
            @Override
            public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) {
                String token = request.getHeader("X-Internal-Token");
                if (token == null || !MessageDigest.isEqual(internalToken, token.getBytes(StandardCharsets.UTF_8))) {
                    throw new ApiError(403, "INVALID_INTERNAL_TOKEN", "内部凭证无效");
                }
                return true;
            }
        }).addPathPatterns("/internal/**");
    }

    private long owner(String authorization) {
        try {
            if (authorization != null && authorization.startsWith("Bearer ")) {
                var signed = parser.parseSignedClaims(authorization.substring(7));
                Claims claims = signed.getPayload();
                long owner = Long.parseLong(claims.getSubject());
                if ("HS256".equals(signed.getHeader().getAlgorithm()) && owner > 0
                        && claims.getIssuedAt() != null && claims.getExpiration() != null
                        && !claims.getIssuedAt().after(new java.util.Date())
                        && claims.getExpiration().after(claims.getIssuedAt())
                        && claims.getAudience() != null && claims.getAudience().contains(audience)
                        && Long.parseLong(String.valueOf(claims.get("accountId"))) > 0) {
                    return owner;
                }
            }
        } catch (JwtException | IllegalArgumentException invalid) {
            // Return the same response for invalid, malformed, and expired tokens.
        }
        throw new ApiError(401, "UNAUTHORIZED", "登录凭证无效");
    }
}
