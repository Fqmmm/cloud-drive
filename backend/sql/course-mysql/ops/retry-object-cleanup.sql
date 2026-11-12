-- Set @object_key in this session before sourcing this script.
UPDATE file_db.object_cleanup
SET next_attempt_at = CURRENT_TIMESTAMP
WHERE object_key = @object_key;
