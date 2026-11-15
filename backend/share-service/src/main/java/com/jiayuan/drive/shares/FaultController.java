package com.jiayuan.drive.shares;

import jakarta.servlet.http.HttpServletRequest;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RestController;

/** Explicitly enabled local experiment hook; never forwarded through the frontend. */
@RestController
@ConditionalOnProperty(name = "EXPERIMENT_FAULTS_ENABLED", havingValue = "true")
class FaultController {
    private static final Logger LOG = LoggerFactory.getLogger(FaultController.class);
    private final byte[] credential;

    FaultController(@Value("${INTERNAL_API_TOKEN}") String credential) {
        this.credential = credential.getBytes(StandardCharsets.UTF_8);
    }

    @PostMapping("/internal/test/exit")
    void exit(@RequestHeader(value = "X-Internal-Token", required = false) String supplied,
              HttpServletRequest request) {
        if (supplied == null || !MessageDigest.isEqual(credential, supplied.getBytes(StandardCharsets.UTF_8))) {
            throw new ApiError(403, "INVALID_INTERNAL_TOKEN", "内部凭证无效");
        }
        LOG.warn("controlled_exit requestId={} exitCode=17", request.getAttribute("requestId"));
        Runtime.getRuntime().halt(17);
    }
}
