package com.jiayuan.drive.auth;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import java.util.Locale;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

@Component
class AccountLogin {
    private final JdbcTemplate jdbc;
    private final AccountPasswords passwords;
    private final JwtTokens tokens;
    private final String dummyHash;

    AccountLogin(JdbcTemplate jdbc, AccountPasswords passwords, JwtTokens tokens) {
        this.jdbc = jdbc;
        this.passwords = passwords;
        this.tokens = tokens;
        this.dummyHash = passwords.encode(java.util.UUID.randomUUID().toString());
    }

    LoginResult login(LoginRequest request) {
        var rows = jdbc.query("""
                SELECT u.id, a.id AS account_id, u.nickname, u.email, a.account_name, a.password,
                       u.status AS user_status, a.status AS account_status
                FROM sys_account a JOIN sys_user u ON a.user_id=u.id
                WHERE a.account_name=? AND a.account_type='personal' AND NOT a.is_deleted AND NOT u.is_deleted
                """, (rs, row) -> new Account(new Profile(rs.getString("id"), rs.getString("account_id"),
                        rs.getString("nickname"), rs.getString("account_name"), rs.getString("email")),
                        rs.getString("password"), rs.getInt("user_status") == 1 && rs.getInt("account_status") == 1),
                request.accountName().toLowerCase(Locale.ROOT));
        Account account = rows.isEmpty() ? null : rows.get(0);
        boolean matched = passwords.matches(request.password(), account == null ? dummyHash : account.password());
        if (!matched || account == null || !account.active()) {
            throw new ApiError(401, "INVALID_CREDENTIALS", "账户或密码错误");
        }
        Profile profile = account.profile();
        return new LoginResult(tokens.issue(profile.userId(), profile.accountId()), profile.userId(),
                profile.accountId(), profile.nickname(), profile.accountName());
    }

    Profile me(String authorization) {
        JwtTokens.Identity identity = tokens.verify(authorization);
        var profiles = jdbc.query("""
                SELECT u.id, a.id AS account_id, u.nickname, u.email, a.account_name
                FROM sys_account a JOIN sys_user u ON a.user_id=u.id
                WHERE u.id=? AND a.id=? AND a.account_type='personal'
                  AND u.status=1 AND a.status=1 AND NOT u.is_deleted AND NOT a.is_deleted
                """, (rs, row) -> new Profile(rs.getString("id"), rs.getString("account_id"),
                        rs.getString("nickname"), rs.getString("account_name"), rs.getString("email")),
                identity.userId(), identity.accountId());
        if (profiles.isEmpty()) { throw new ApiError(401, "UNAUTHORIZED", "登录凭证无效"); }
        return profiles.get(0);
    }

    record LoginRequest(@NotBlank @Pattern(regexp = "[A-Za-z0-9_]{3,32}") String accountName,
                        @NotBlank @Size(min = 8, max = 64) String password) { }
    record LoginResult(String token, String userId, String accountId, String nickname, String accountName) { }
    record Profile(String userId, String accountId, String nickname, String accountName, String email) { }
    private record Account(Profile profile, String password, boolean active) { }
}
