package com.jiayuan.drive.shares;

import java.time.Instant;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Component;

/** Authorization order preserves protected-file privacy even when the source is gone. */
@Component
class ShareAccess {
    private final ShareStore store;
    private final FileClient files;
    private final CodeAttempts attempts;
    private final BCryptPasswordEncoder passwords = new BCryptPasswordEncoder(12);

    ShareAccess(ShareStore store, FileClient files, CodeAttempts attempts) {
        this.store = store; this.files = files; this.attempts = attempts;
    }

    Details details(String token) {
        ShareStore.Share share = active(token);
        if (share.accessType() == 1) { return new Details(true, null, null, share.expireTime()); }
        return details(share, files.metadata(share.userId(), share.fileId()));
    }

    Details verify(String token, String code) {
        ShareStore.Share share = authorized(token, code);
        return details(share, files.metadata(share.userId(), share.fileId()));
    }

    ShareStore.Share authorized(String token, String code) {
        ShareStore.Share share = active(token);
        if (share.accessType() == 1 && (code == null || !code.matches("[0-9]{6}")
                || !passwords.matches(code, share.extractCodeHash()))) {
            attempts.wrong(share.token());
        }
        return share;
    }

    private ShareStore.Share active(String token) {
        if (!token.matches("[A-Za-z0-9_-]{22}")) { throw ShareStore.missing(); }
        ShareStore.Share share = store.find(token);
        if (share.status() != 0) { throw new ApiError(410, "SHARE_CANCELLED", "分享已取消"); }
        if (share.expireTime() != null && !share.expireTime().isAfter(Instant.now())) {
            throw new ApiError(410, "SHARE_EXPIRED", "分享已过期");
        }
        return share;
    }

    private Details details(ShareStore.Share share, FileClient.Metadata file) {
        if (file.isDirectory()) { throw FileClient.missing(); }
        return new Details(share.accessType() == 1, file.originalName(), file.fileSize(), share.expireTime());
    }

    record Details(boolean requiresCode, String fileName, Long fileSize, Instant expireTime) { }
}
