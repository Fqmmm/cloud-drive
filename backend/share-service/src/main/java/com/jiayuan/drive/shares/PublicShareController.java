package com.jiayuan.drive.shares;

import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import com.fasterxml.jackson.databind.JsonNode;
import org.springframework.web.bind.annotation.*;

@RestController
class PublicShareController {
    private final ShareAccess access;
    private final FileClient files;

    PublicShareController(ShareAccess access, FileClient files) { this.access = access; this.files = files; }

    @GetMapping("/api/v1/s/{token}")
    ApiResult<ShareAccess.Details> details(@PathVariable String token) { return ApiResult.ok(access.details(token)); }

    @PostMapping("/api/v1/s/{token}/verify")
    ApiResult<ShareAccess.Details> verify(@PathVariable String token, @RequestBody(required = false) Access request) {
        return ApiResult.ok(access.verify(token, request == null ? null : request.code()));
    }

    @PostMapping("/api/v1/s/{token}/download")
    void download(@PathVariable String token, @RequestBody(required = false) Access request,
                  HttpServletResponse response) throws IOException {
        ShareStore.Share share = access.authorized(token, request == null ? null : request.code());
        FileClient.Metadata file = files.metadata(share.userId(), share.fileId());
        if (file.isDirectory()) { throw FileClient.missing(); }
        files.stream(share.userId(), share.fileId(), file.originalName(), response);
    }

    record Access(JsonNode extractCode) {
        String code() { return extractCode != null && extractCode.isTextual() ? extractCode.asText() : null; }
    }
}
