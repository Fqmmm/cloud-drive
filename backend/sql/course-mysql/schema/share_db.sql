USE share_db;

CREATE TABLE sys_share (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    file_id BIGINT NOT NULL,
    file_name VARCHAR(255) NOT NULL,
    share_token VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    access_type TINYINT NOT NULL,
    extract_code_hash VARCHAR(255),
    expire_time TIMESTAMP NULL,
    status TINYINT NOT NULL DEFAULT 0,
    create_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_share_token (share_token),
    KEY idx_share_owner (user_id, create_time),
    KEY idx_share_expiry (expire_time),
    CONSTRAINT ck_share_access CHECK (
        (access_type = 0 AND extract_code_hash IS NULL)
        OR (access_type = 1 AND extract_code_hash IS NOT NULL)
    )
) ENGINE=InnoDB;
