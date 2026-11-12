USE file_db;

CREATE TABLE sys_file (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    parent_id BIGINT NOT NULL DEFAULT 0,
    original_name VARCHAR(255) NOT NULL,
    file_size BIGINT NOT NULL DEFAULT 0,
    mime_type VARCHAR(128),
    object_key VARCHAR(255) CHARACTER SET ascii COLLATE ascii_bin,
    is_directory BOOLEAN NOT NULL DEFAULT FALSE,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    create_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    active_name VARCHAR(255) GENERATED ALWAYS AS (
        CASE WHEN is_deleted = FALSE THEN original_name ELSE NULL END
    ) STORED,
    UNIQUE KEY uq_active_name (user_id, parent_id, active_name),
    UNIQUE KEY uq_object_key (object_key),
    KEY idx_children (user_id, parent_id, is_deleted, id),
    CONSTRAINT ck_file_deleted CHECK (is_deleted IN (0, 1)),
    CONSTRAINT ck_file_kind CHECK (
        (is_directory = TRUE AND object_key IS NULL AND file_size = 0)
        OR (is_directory = FALSE AND object_key IS NOT NULL AND file_size >= 0)
    )
) ENGINE=InnoDB;

CREATE TABLE user_quota (
    user_id BIGINT PRIMARY KEY,
    total_quota BIGINT NOT NULL DEFAULT 10737418240,
    used_space BIGINT NOT NULL DEFAULT 0,
    create_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT ck_quota_bounds CHECK (used_space >= 0 AND used_space <= total_quota)
) ENGINE=InnoDB;

CREATE TABLE object_cleanup (
    object_key VARCHAR(255) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    reason VARCHAR(64) NOT NULL,
    attempts INT UNSIGNED NOT NULL DEFAULT 0,
    last_error VARCHAR(512),
    next_attempt_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    create_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_cleanup_due (next_attempt_at)
) ENGINE=InnoDB;
