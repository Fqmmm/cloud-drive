package com.jiayuan.drive.files;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.multipart.MultipartFile;

import java.sql.Statement;
import java.time.Instant;
import java.util.ArrayDeque;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

@Service
final class FileCatalog {
    record Item(String id, String originalName, long fileSize, String mimeType,
                Instant createTime, boolean isDirectory, String parentId) {}
    record Crumb(String id, String name) {}
    record Listing(List<Crumb> breadcrumb, List<Item> items) {}
    record Quota(long totalBytes, long usedBytes) {}
    record Stored(Item item, String key) {}

    private static final Logger LOG = LoggerFactory.getLogger(FileCatalog.class);
    private static final String ACTIVE = " FROM sys_file WHERE user_id=? AND is_deleted=0";
    private static final RowMapper<Stored> ENTRY = (row, index) -> new Stored(
            new Item(row.getString("id"), row.getString("original_name"), row.getLong("file_size"),
                    row.getString("mime_type"), row.getTimestamp("create_time").toInstant(),
                    row.getBoolean("is_directory"), row.getString("parent_id")),
            row.getString("object_key"));

    private final JdbcTemplate db;
    private final TransactionTemplate transaction;
    private final ObjectStorage storage;
    private final long defaultQuota;
    private final long maxFile;
    private final Set<String> uploading = ConcurrentHashMap.newKeySet();

    FileCatalog(JdbcTemplate db, TransactionTemplate transaction, ObjectStorage storage,
                @Value("${file-service.quota}") long defaultQuota,
                @Value("${file-service.max-file}") long maxFile) {
        if (defaultQuota < 0 || maxFile < 1) {
            throw new IllegalArgumentException("Invalid file size or quota configuration");
        }
        this.db = db;
        this.transaction = transaction;
        this.storage = storage;
        this.defaultQuota = defaultQuota;
        this.maxFile = maxFile;
    }

    Listing list(long owner, long parent) {
        return transaction.execute(status -> {
            var crumbs = new ArrayDeque<Crumb>();
            long current = parent;
            while (current != 0) {
                Item directory = requireKind(owner, current, true).item();
                crumbs.addFirst(new Crumb(directory.id(), directory.originalName()));
                current = Long.parseLong(directory.parentId());
            }
            crumbs.addFirst(new Crumb("0", "根目录"));
            List<Item> items = db.query("SELECT *" + ACTIVE + " AND parent_id=? ORDER BY is_directory DESC, id",
                    ENTRY, owner, parent).stream().map(Stored::item).toList();
            return new Listing(List.copyOf(crumbs), items);
        });
    }

    Stored get(long owner, long id) {
        return db.query("SELECT *" + ACTIVE + " AND id=?", ENTRY, owner, id)
                .stream().findFirst().orElseThrow(ApiError::missing);
    }

    Stored requireKind(long owner, long id, boolean directory) {
        Stored entry = get(owner, id);
        if (entry.item().isDirectory() != directory) {
            throw ApiError.missing();
        }
        return entry;
    }

    private void initializeQuota(long owner) {
        db.update("""
                INSERT INTO user_quota (user_id, total_quota) VALUES (?, ?)
                ON DUPLICATE KEY UPDATE user_id = user_id
                """, owner, defaultQuota);
    }

    Quota quota(long owner) {
        initializeQuota(owner);
        return readQuota(owner, false);
    }

    private Quota readQuota(long owner, boolean lock) {
        String query = "SELECT total_quota, used_space FROM user_quota WHERE user_id=?";
        return db.queryForObject(lock ? query + " FOR UPDATE" : query,
                (row, index) -> new Quota(row.getLong(1), row.getLong(2)), owner);
    }

    private Quota lockOwner(long owner) {
        initializeQuota(owner);
        return readQuota(owner, true);
    }

    private void validateParent(long owner, long parent) {
        if (parent != 0) {
            requireKind(owner, parent, true);
        }
    }

    private static String validateName(String raw) {
        String name = raw == null ? "" : raw.strip();
        if (name.isEmpty() || name.codePointCount(0, name.length()) > 255
                || name.equals(".") || name.equals("..") || name.indexOf('/') >= 0
                || name.indexOf(92) >= 0 || name.codePoints().anyMatch(Character::isISOControl)) {
            throw new ApiError(400, "INVALID_FILE_NAME", "文件或目录名称无效");
        }
        return name;
    }

    private static void requireSpace(Quota quota, long size) {
        if (size > quota.totalBytes() - quota.usedBytes()) {
            throw new ApiError(409, "QUOTA_EXCEEDED", "可用容量不足");
        }
    }

    private static ApiError nameConflict() {
        return new ApiError(409, "NAME_CONFLICT", "当前目录已存在同名文件或目录");
    }

    Item createDirectory(long owner, long parent, String rawName) {
        String name = validateName(rawName);
        return transaction.execute(status -> {
            lockOwner(owner);
            validateParent(owner, parent);
            return insert(owner, parent, name, 0, null, null, true);
        });
    }

    Item upload(long owner, long parent, MultipartFile file) {
        String name = validateName(file.getOriginalFilename());
        long size = file.getSize();
        if (size > maxFile) {
            throw new ApiError(413, "FILE_TOO_LARGE", "文件超过单文件大小限制");
        }
        validateParent(owner, parent);
        requireSpace(quota(owner), size);
        String mime = file.getContentType();
        if (mime != null && mime.length() > 128) {
            mime = null;
        }
        String contentType = mime;
        String key = UUID.randomUUID().toString();
        uploading.add(key);
        try {
            // The durable intent covers a crash between writing MinIO and committing metadata.
            enqueue(key, "UNCOMMITTED_UPLOAD");
            try {
                storage.ensureBucket();
                storage.put(key, file);
            } catch (Exception failure) {
                throw ApiError.dependency();
            }
            return transaction.execute(status -> {
                requireSpace(lockOwner(owner), size);
                validateParent(owner, parent);
                Item created = insert(owner, parent, name, size, contentType, key, false);
                db.update("UPDATE user_quota SET used_space=used_space+? WHERE user_id=?", size, owner);
                db.update("DELETE FROM object_cleanup WHERE object_key=?", key);
                return created;
            });
        } finally {
            uploading.remove(key);
        }
    }

    private Item insert(long owner, long parent, String name, long size, String mime, String key,
                        boolean directory) {
        var generated = new GeneratedKeyHolder();
        try {
            db.update(connection -> {
                var statement = connection.prepareStatement("""
                        INSERT INTO sys_file
                            (user_id, parent_id, original_name, file_size, mime_type, object_key, is_directory)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, Statement.RETURN_GENERATED_KEYS);
                statement.setLong(1, owner);
                statement.setLong(2, parent);
                statement.setString(3, name);
                statement.setLong(4, size);
                statement.setString(5, mime);
                statement.setString(6, key);
                statement.setBoolean(7, directory);
                return statement;
            }, generated);
        } catch (DuplicateKeyException conflict) {
            throw nameConflict();
        }
        return get(owner, generated.getKey().longValue()).item();
    }

    Item rename(long owner, long id, boolean directory, String rawName) {
        String name = validateName(rawName);
        return transaction.execute(status -> {
            lockOwner(owner);
            requireKind(owner, id, directory);
            try {
                db.update("UPDATE sys_file SET original_name=? WHERE user_id=? AND id=?", name, owner, id);
            } catch (DuplicateKeyException conflict) {
                throw nameConflict();
            }
            return get(owner, id).item();
        });
    }

    void delete(long owner, long id, boolean directory) {
        transaction.executeWithoutResult(status -> {
            lockOwner(owner);
            Stored entry = requireKind(owner, id, directory);
            if (directory && !db.queryForList("SELECT id" + ACTIVE + " AND parent_id=? LIMIT 1",
                    Long.class, owner, id).isEmpty()) {
                throw new ApiError(409, "DIRECTORY_NOT_EMPTY", "请先删除目录中的内容");
            }
            db.update("UPDATE sys_file SET is_deleted=1 WHERE user_id=? AND id=?", owner, id);
            if (!directory) {
                db.update("UPDATE user_quota SET used_space=used_space-? WHERE user_id=?",
                        entry.item().fileSize(), owner);
                enqueue(entry.key(), "FILE_DELETED");
            }
        });
    }

    private void enqueue(String key, String reason) {
        db.update("INSERT INTO object_cleanup (object_key, reason) VALUES (?, ?)", key, reason);
    }

    @Scheduled(fixedDelay = 15000)
    void cleanPending() {
        try {
            storage.ensureBucket();
            List<String> pending = db.queryForList("""
                    SELECT object_key FROM object_cleanup
                    WHERE next_attempt_at <= CURRENT_TIMESTAMP ORDER BY next_attempt_at, object_key LIMIT 20
                    """, String.class);
            for (String key : pending) {
                if (uploading.contains(key) || db.queryForObject(
                        "SELECT COUNT(*) FROM object_cleanup WHERE object_key=?", Integer.class, key) == 0) {
                    continue;
                }
                try {
                    // A failed deletion remains queued. Removing a missing object is safe.
                    storage.delete(key);
                    db.update("DELETE FROM object_cleanup WHERE object_key=?", key);
                } catch (Exception failure) {
                    db.update("""
                            UPDATE object_cleanup SET attempts=attempts+1, last_error=?,
                                next_attempt_at=CURRENT_TIMESTAMP + INTERVAL 1 MINUTE
                            WHERE object_key=?
                            """, failure.getClass().getSimpleName(), key);
                }
            }
        } catch (Exception unavailable) {
            LOG.debug("Object cleanup deferred ({})", unavailable.getClass().getSimpleName());
        }
    }

    boolean ready() {
        try {
            db.queryForObject("SELECT MAX(version) FROM schema_version", Integer.class);
            storage.ensureBucket();
            return true;
        } catch (Exception unavailable) {
            return false;
        }
    }
}
