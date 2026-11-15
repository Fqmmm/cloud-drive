package com.jiayuan.drive.shares;

import jakarta.validation.Valid;
import java.util.List;
import org.springframework.web.bind.annotation.*;

@RestController
class ShareController {
    private final ShareManagement management;
    private final JwtTokens tokens;

    ShareController(ShareManagement management, JwtTokens tokens) { this.management = management; this.tokens = tokens; }

    @PostMapping("/api/v1/shares")
    ApiResult<ShareManagement.Created> create(@RequestHeader(value = "Authorization", required = false) String authorization,
                                             @Valid @RequestBody ShareManagement.Creation request) {
        return ApiResult.ok(management.create(tokens.verify(authorization).userId(), request));
    }

    @GetMapping("/api/v1/shares")
    ApiResult<List<ShareManagement.Entry>> list(@RequestHeader(value = "Authorization", required = false) String authorization) {
        return ApiResult.ok(management.list(tokens.verify(authorization).userId()));
    }

    @DeleteMapping("/api/v1/shares/{id:[1-9][0-9]{0,18}}")
    ApiResult<Void> cancel(@RequestHeader(value = "Authorization", required = false) String authorization, @PathVariable String id) {
        management.cancel(tokens.verify(authorization).userId(), id);
        return ApiResult.ok(null);
    }
}
