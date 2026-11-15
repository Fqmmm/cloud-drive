package com.jiayuan.drive.shares;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.net.HttpURLConnection;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/** Only the file service accesses MinIO; owner/file IDs come from verified share records. */
@Component
class FileClient {
    private final String base;
    private final String token;
    private final int connectTimeout;
    private final int readTimeout;
    private final ObjectMapper json;

    FileClient(@Value("${FILE_SERVICE_URL:http://file-service:8080}") String base,
               @Value("${INTERNAL_API_TOKEN}") String token,
               @Value("${JWT_SECRET}") String jwtSecret,
               @Value("${FILE_CONNECT_TIMEOUT_MS:3000}") int connectTimeout,
               @Value("${FILE_METADATA_TIMEOUT_MS:5000}") int readTimeout, ObjectMapper json) {
        URI uri = URI.create(base);
        if (!("http".equals(uri.getScheme()) || "https".equals(uri.getScheme())) || uri.getHost() == null
                || uri.getUserInfo() != null || uri.getQuery() != null || uri.getFragment() != null
                || token.isBlank() || token.equals(jwtSecret) || connectTimeout < 1 || readTimeout < 1) {
            throw new IllegalArgumentException("Invalid file service configuration");
        }
        this.base = base.replaceAll("/+$", "");
        this.token = token;
        this.connectTimeout = connectTimeout;
        this.readTimeout = readTimeout;
        this.json = json;
    }

    Metadata metadata(String ownerId, String fileId) {
        HttpURLConnection connection = null;
        try {
            connection = connect(ownerId, fileId, "", readTimeout);
            int status = connection.getResponseCode();
            if (status == 404) { throw missing(); }
            if (status != 200) { throw unavailable(); }
            try (var source = connection.getInputStream()) {
                // A bounded response prevents a faulty dependency from filling the heap.
                byte[] bytes = source.readNBytes(65537);
                if (bytes.length > 65536) { throw unavailable(); }
                var root = json.readTree(new String(bytes, StandardCharsets.UTF_8));
                if (root == null) { throw unavailable(); }
                var data = root.path("data");
                if (!"00000".equals(root.path("code").asText())
                        || !fileId.equals(data.path("id").asText()) || !ownerId.equals(data.path("ownerId").asText())
                        || !data.path("isDirectory").isBoolean() || !data.path("fileSize").canConvertToLong()
                        || data.path("fileSize").asLong() < 0 || !data.path("originalName").isTextual()) {
                    throw unavailable();
                }
                return new Metadata(fileId, ownerId, data.path("originalName").asText(),
                        data.path("fileSize").asLong(), data.path("mimeType").asText(), data.path("isDirectory").asBoolean());
            }
        } catch (IOException invalid) {
            throw unavailable();
        } finally {
            if (connection != null) { connection.disconnect(); }
        }
    }

    HttpURLConnection connect(String ownerId, String fileId, String suffix, int timeout) throws IOException {
        if (!validId(ownerId) || !validId(fileId)) { throw missing(); }
        HttpURLConnection connection = (HttpURLConnection) URI.create(base + "/internal/v1/files/" + fileId
                + suffix + "?ownerId=" + ownerId).toURL().openConnection();
        connection.setConnectTimeout(connectTimeout);
        connection.setReadTimeout(timeout);
        connection.setInstanceFollowRedirects(false);
        connection.setRequestProperty("X-Internal-Token", token);
        return connection;
    }

    private boolean validId(String id) {
        try { return id != null && id.matches("[1-9][0-9]{0,18}") && Long.parseLong(id) > 0; }
        catch (NumberFormatException invalid) { return false; }
    }

    static ApiError missing() { return new ApiError(404, "SHARE_FILE_UNAVAILABLE", "文件已失效"); }
    static ApiError unavailable() { return new ApiError(503, "DEPENDENCY_UNAVAILABLE", "服务暂不可用，请稍后重试"); }
    record Metadata(String id, String ownerId, String originalName, long fileSize, String mimeType, boolean isDirectory) { }
}
