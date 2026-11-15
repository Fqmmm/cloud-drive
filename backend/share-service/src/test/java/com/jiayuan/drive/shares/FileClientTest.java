package com.jiayuan.drive.shares;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class FileClientTest {
    @Test
    void forwardsInternalCredentialAndMapsDependencyFailures() throws Exception {
        String token = UUID.randomUUID().toString();
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/internal/v1/files/2", exchange -> {
            boolean allowed = token.equals(exchange.getRequestHeaders().getFirst("X-Internal-Token"));
            String body = "{\"code\":\"00000\",\"data\":{\"id\":\"2\",\"ownerId\":\"1\",\"originalName\":\"file.txt\",\"fileSize\":3,\"isDirectory\":false}}";
            byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(allowed ? 200 : 403, bytes.length);
            try (var out = exchange.getResponseBody()) { out.write(bytes); }
        });
        server.start();
        try {
            String base = "http://127.0.0.1:" + server.getAddress().getPort();
            FileClient good = new FileClient(base, token, "different-secret", 300, 500, new ObjectMapper());
            assertEquals("file.txt", good.metadata("1", "2").originalName());
            assertEquals(404, assertThrows(ApiError.class, () -> good.metadata("1", "3")).status);
            assertEquals(503, assertThrows(ApiError.class, () -> good.metadata("99", "2")).status);
            FileClient wrong = new FileClient(base, "wrong-credential", "different-secret", 300, 500, new ObjectMapper());
            assertEquals(503, assertThrows(ApiError.class, () -> wrong.metadata("1", "2")).status);
        } finally { server.stop(0); }
    }

    @Test
    void unreachableDependencyIsBounded() {
        FileClient client = new FileClient("http://127.0.0.1:1", UUID.randomUUID().toString(),
                "different-secret", 100, 100, new ObjectMapper());
        assertTimeout(java.time.Duration.ofSeconds(3), () ->
                assertEquals(503, assertThrows(ApiError.class, () -> client.metadata("1", "2")).status));
    }
}
