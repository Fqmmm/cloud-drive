package com.jiayuan.drive.shares;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

/** Correlate status/duration without logging URI tokens, bodies, identities or credentials. */
@Component
class RequestObservation extends OncePerRequestFilter {
    private static final Logger LOG = LoggerFactory.getLogger(RequestObservation.class);
    private final String version;
    private final String instance;

    RequestObservation(@Value("${APP_VERSION:course-v1}") String version,
                       @Value("${INSTANCE_ID:${HOSTNAME:local}}") String instance) {
        if (!version.matches("[A-Za-z0-9._-]{1,80}") || !instance.matches("[A-Za-z0-9._-]{1,80}")) {
            throw new IllegalArgumentException("Invalid instance/version labels");
        }
        this.version = version; this.instance = instance;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        String supplied = request.getHeader("X-Request-Id");
        String id = supplied != null && supplied.matches("[A-Za-z0-9_-]{1,64}") ? supplied : UUID.randomUUID().toString();
        request.setAttribute("requestId", id);
        response.setHeader("X-Request-Id", id);
        response.setHeader("X-App-Version", version);
        response.setHeader("X-Instance-Id", instance);
        MDC.put("requestId", id);
        long started = System.nanoTime();
        boolean interrupted = false;
        try { chain.doFilter(request, response); }
        catch (IOException failure) { interrupted = true; throw failure; }
        finally {
            String path = request.getRequestURI();
            String category = path.startsWith("/api/v1/auth/") ? "authentication"
                    : path.startsWith("/api/v1/s/") ? "anonymous-share"
                    : path.startsWith("/api/v1/shares") ? "share-management"
                    : path.startsWith("/health/") ? "health" : "other";
            LOG.info("request id={} category={} status={} durationMs={} interrupted={} instance={}",
                    id, category, response.getStatus(), (System.nanoTime() - started) / 1000000, interrupted, instance);
            MDC.remove("requestId");
        }
    }
}
