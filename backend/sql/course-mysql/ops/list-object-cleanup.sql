SELECT object_key, reason, attempts, last_error, next_attempt_at
FROM file_db.object_cleanup
ORDER BY next_attempt_at, object_key;
