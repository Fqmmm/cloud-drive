package com.jiayuan.drive.shares;

import java.util.concurrent.ConcurrentHashMap;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/** Per-instance wrong-code counter shared by verify/download. Correct codes bypass it. */
@Component
class CodeAttempts {
    private final int limit;
    private final long windowMillis;
    private final ConcurrentHashMap<String, Window> windows = new ConcurrentHashMap<>();

    CodeAttempts(@Value("${SHARE_CODE_MAX_FAILURES:5}") int limit,
                 @Value("${SHARE_CODE_WINDOW_SECONDS:60}") long seconds) {
        if (limit < 1 || seconds < 1 || seconds > 86400) { throw new IllegalArgumentException("Invalid code attempt limits"); }
        this.limit = limit; this.windowMillis = seconds * 1000;
    }

    void wrong(String token) {
        long now = System.currentTimeMillis();
        windows.entrySet().removeIf(entry -> now - entry.getValue().started >= windowMillis);
        Window window = windows.compute(token, (key, previous) -> previous == null
                ? new Window(now, 1) : new Window(previous.started, Math.min(limit + 1, previous.failures + 1)));
        if (window.failures > limit) { throw new ApiError(429, "SHARE_CODE_RATE_LIMITED", "尝试过于频繁，请稍后再试"); }
        throw new ApiError(403, "SHARE_CODE_INVALID", "请输入正确提取码");
    }

    private record Window(long started, int failures) { }
}
