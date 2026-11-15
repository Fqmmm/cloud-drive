package com.jiayuan.drive.shares;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import java.net.URI;
import java.security.SecureRandom;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.Base64;
import java.util.List;
import java.util.Locale;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Component;

@Component
class ShareManagement {
    private final ShareStore store;
    private final FileClient files;
    private final String publicBase;
    private final SecureRandom random = new SecureRandom();
    private final BCryptPasswordEncoder passwords = new BCryptPasswordEncoder(12);

    ShareManagement(ShareStore store, FileClient files,
                    @Value("${PUBLIC_BASE_URL:http://localhost:8080}") String publicBase) {
        URI uri = URI.create(publicBase);
        if (!("http".equals(uri.getScheme()) || "https".equals(uri.getScheme())) || uri.getHost() == null
                || uri.getQuery() != null || uri.getFragment() != null || uri.getUserInfo() != null) {
            throw new IllegalArgumentException("Invalid public base URL");
        }
        this.store = store; this.files = files; this.publicBase = publicBase.replaceAll("/+$", "");
    }

    Created create(String owner, Creation request) {
        if (request.expireDays() != null && !List.of(1, 7, 30).contains(request.expireDays())) {
            throw new ApiError(400, "INVALID_REQUEST", "有效期只能为 1、7、30 天或永久");
        }
        FileClient.Metadata file = files.metadata(owner, request.fileId());
        if (file.isDirectory()) { throw new ApiError(400, "DIRECTORY_SHARE_UNSUPPORTED", "只能分享单个普通文件"); }
        byte[] bytes = new byte[16]; random.nextBytes(bytes);
        String token = Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
        String code = request.accessType() == 1 ? String.format(Locale.ROOT, "%06d", random.nextInt(1000000)) : null;
        Instant expiry = request.expireDays() == null ? null : Instant.now().plus(request.expireDays(), ChronoUnit.DAYS);
        String id = store.insert(owner, request.fileId(), file.originalName(), token, request.accessType(),
                code == null ? null : passwords.encode(code), expiry);
        return new Created(id, token, url(token), code, expiry);
    }

    List<Entry> list(String owner) {
        return store.list(owner).stream().map(share -> new Entry(share.id(), share.fileId(), share.fileName(),
                share.token(), url(share.token()), share.accessType(), share.expireTime(), share.createTime(),
                share.status() != 0 ? "CANCELLED" : share.expireTime() != null && !share.expireTime().isAfter(Instant.now()) ? "EXPIRED" : "ACTIVE")).toList();
    }

    void cancel(String owner, String id) { store.cancel(owner, id); }
    private String url(String token) { return publicBase + "/#/s/" + token; }

    record Creation(@NotBlank @Pattern(regexp = "[1-9][0-9]{0,18}") String fileId,
                    @NotNull @Min(0) @Max(1) Integer accessType, Integer expireDays) { }
    record Created(String id, String shareToken, String shareUrl, String extractCode, Instant expireTime) { }
    record Entry(String id, String fileId, String fileName, String shareToken, String shareUrl,
                 int accessType, Instant expireTime, Instant createTime, String status) { }
}
