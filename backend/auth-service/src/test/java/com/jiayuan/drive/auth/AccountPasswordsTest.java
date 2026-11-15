package com.jiayuan.drive.auth;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class AccountPasswordsTest {
    @Test
    void saltsHashesAndPreservesLongUnicodePasswords() {
        AccountPasswords passwords = new AccountPasswords();
        String first = "密".repeat(63) + "甲";
        String second = "密".repeat(63) + "乙";
        String encoded = passwords.encode(first);
        assertTrue(passwords.matches(first, encoded));
        assertFalse(passwords.matches(second, encoded));
        assertNotEquals(encoded, passwords.encode(first));
        assertFalse(encoded.contains(first));
    }
}
