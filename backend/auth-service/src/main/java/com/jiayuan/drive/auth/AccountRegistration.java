package com.jiayuan.drive.auth;

import java.sql.PreparedStatement;
import java.sql.Statement;
import java.util.Locale;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.stereotype.Component;
import org.springframework.transaction.support.TransactionTemplate;

/** User and account insertion share a local transaction; no quota or cross-service writes. */
@Component
class AccountRegistration {
    private final JdbcTemplate jdbc;
    private final TransactionTemplate transactions;
    private final AccountPasswords passwords;

    AccountRegistration(JdbcTemplate jdbc, TransactionTemplate transactions, AccountPasswords passwords) {
        this.jdbc = jdbc;
        this.transactions = transactions;
        this.passwords = passwords;
    }

    void register(Registration request) {
        String account = request.accountName().toLowerCase(Locale.ROOT);
        String email = request.email().toLowerCase(Locale.ROOT);
        // Expensive hashing stays outside the database transaction and its row locks.
        String encoded = passwords.encode(request.password());
        try {
            transactions.executeWithoutResult(status -> {
                GeneratedKeyHolder key = new GeneratedKeyHolder();
                jdbc.update(connection -> {
                    PreparedStatement insert = connection.prepareStatement(
                            "INSERT INTO sys_user (nickname, email) VALUES (?, ?)", Statement.RETURN_GENERATED_KEYS);
                    insert.setString(1, request.nickname());
                    insert.setString(2, email);
                    return insert;
                }, key);
                jdbc.update("INSERT INTO sys_account (user_id, account_name, password, account_type) VALUES (?, ?, ?, 'personal')",
                        key.getKey().longValue(), account, encoded);
            });
        } catch (DuplicateKeyException conflict) {
            // Constraint names distinguish conflicts; never expose SQL text or field values.
            String message = conflict.getMostSpecificCause().getMessage();
            boolean duplicateEmail = message != null && message.contains("uq_email");
            throw new ApiError(409, duplicateEmail ? "EMAIL_EXISTS" : "ACCOUNT_EXISTS",
                    duplicateEmail ? "邮箱已注册" : "账户名已注册");
        }
    }
}
