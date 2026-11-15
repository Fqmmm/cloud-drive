package com.jiayuan.drive.shares;

import java.sql.Statement;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.stereotype.Component;

/** Only share_db is queried. File ownership is checked by the HTTP client before insertion. */
@Component
class ShareStore {
    private final JdbcTemplate jdbc;
    private static final RowMapper<Share> ROW = (rs, row) -> new Share(rs.getString("id"), rs.getString("user_id"),
            rs.getString("file_id"), rs.getString("file_name"), rs.getString("share_token"), rs.getInt("access_type"),
            rs.getString("extract_code_hash"), rs.getTimestamp("expire_time") == null ? null : rs.getTimestamp("expire_time").toInstant(),
            rs.getInt("status"), rs.getTimestamp("create_time").toInstant());

    ShareStore(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    String insert(String owner, String fileId, String name, String token, int accessType, String hash, Instant expiry) {
        GeneratedKeyHolder key = new GeneratedKeyHolder();
        jdbc.update(connection -> {
            var statement = connection.prepareStatement("""
                    INSERT INTO sys_share (user_id, file_id, file_name, share_token, access_type, extract_code_hash, expire_time)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, Statement.RETURN_GENERATED_KEYS);
            statement.setString(1, owner); statement.setString(2, fileId); statement.setString(3, name);
            statement.setString(4, token); statement.setInt(5, accessType); statement.setString(6, hash);
            statement.setTimestamp(7, expiry == null ? null : Timestamp.from(expiry));
            return statement;
        }, key);
        return key.getKey().toString();
    }

    List<Share> list(String owner) {
        return jdbc.query("SELECT * FROM sys_share WHERE user_id=? ORDER BY create_time DESC, id DESC", ROW, owner);
    }

    void cancel(String owner, String id) {
        Integer count = jdbc.queryForObject("SELECT COUNT(*) FROM sys_share WHERE user_id=? AND id=?", Integer.class, owner, id);
        if (count == null || count == 0) { throw missing(); }
        jdbc.update("UPDATE sys_share SET status=1 WHERE user_id=? AND id=? AND status=0", owner, id);
    }

    Share find(String token) {
        return jdbc.query("SELECT * FROM sys_share WHERE share_token=?", ROW, token).stream().findFirst().orElseThrow(ShareStore::missing);
    }

    static ApiError missing() { return new ApiError(404, "SHARE_NOT_FOUND", "分享不存在"); }

    record Share(String id, String userId, String fileId, String fileName, String token, int accessType,
                 String extractCodeHash, Instant expireTime, int status, Instant createTime) { }
}
