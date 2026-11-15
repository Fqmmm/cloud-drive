package com.jiayuan.drive.shares;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class CodeAttemptsTest {
    @Test
    void wrongAttemptsShareAWindowAndReset() throws Exception {
        CodeAttempts attempts = new CodeAttempts(2, 1);
        assertEquals(403, assertThrows(ApiError.class, () -> attempts.wrong("token-a")).status);
        assertEquals(403, assertThrows(ApiError.class, () -> attempts.wrong("token-a")).status);
        assertEquals(429, assertThrows(ApiError.class, () -> attempts.wrong("token-a")).status);
        assertEquals(403, assertThrows(ApiError.class, () -> attempts.wrong("token-b")).status);
        Thread.sleep(1050);
        assertEquals(403, assertThrows(ApiError.class, () -> attempts.wrong("token-a")).status);
    }
}
