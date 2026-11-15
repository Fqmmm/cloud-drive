package com.jiayuan.drive.auth;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Base64;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Component;

/** SHA-256 prehash preserves all 64 Unicode characters beyond BCrypt's 72-byte limit. */
@Component
class AccountPasswords {
    private static final String PREFIX = "{bcrypt-sha256}";
    private final BCryptPasswordEncoder encoder = new BCryptPasswordEncoder(12);

    String encode(String password) {
        return PREFIX + encoder.encode(prehash(password));
    }

    boolean matches(String password, String encoded) {
        return encoded != null && encoded.startsWith(PREFIX)
                && encoder.matches(prehash(password), encoded.substring(PREFIX.length()));
    }

    private String prehash(String password) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256").digest(password.getBytes(StandardCharsets.UTF_8));
            return Base64.getEncoder().encodeToString(digest);
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException("SHA-256 unavailable", impossible);
        }
    }
}
