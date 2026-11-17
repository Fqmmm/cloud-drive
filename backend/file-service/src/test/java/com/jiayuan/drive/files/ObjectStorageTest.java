package com.jiayuan.drive.files;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;
import static org.junit.jupiter.api.Assertions.*;

class ObjectStorageTest {
    private static final byte[] BYTES = "object bytes with a fixed length".getBytes(StandardCharsets.UTF_8);

    @Test
    @Timeout(15)
    void downloadReconnectsWhenAReusedConnectionDiesBeforeHeaders() throws Exception {
        AtomicInteger attempts = new AtomicInteger();
        HttpServer server = server(attempts, false);
        try {
            ObjectStorage storage = storage(server);
            try (var warmup = storage.open("warmup")) { assertArrayEquals(BYTES, warmup.readAllBytes()); }
            try (var recovered = storage.open("sample")) { assertArrayEquals(BYTES, recovered.readAllBytes()); }
            assertEquals(2, attempts.get(), "The failed pooled connection must be replaced once");
        } finally { server.stop(0); }
    }

    @Test
    @Timeout(15)
    void partiallyConsumedDownloadFailsWithoutReplayingTheObject() throws Exception {
        AtomicInteger attempts = new AtomicInteger();
        HttpServer server = server(attempts, true);
        try {
            ObjectStorage storage = storage(server);
            try (var warmup = storage.open("warmup")) { assertArrayEquals(BYTES, warmup.readAllBytes()); }
            assertThrows(IOException.class, () -> {
                try (var partial = storage.open("sample")) { partial.readAllBytes(); }
            });
            assertEquals(1, attempts.get(), "An opened object stream must not be replayed");
        } finally { server.stop(0); }
    }

    private ObjectStorage storage(HttpServer server) {
        return new ObjectStorage("http://127.0.0.1:" + server.getAddress().getPort(),
                "test-minio-user", "test-minio-password");
    }

    private HttpServer server(AtomicInteger attempts, boolean partial) throws IOException {
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/", exchange -> {
            if (String.valueOf(exchange.getRequestURI().getQuery()).contains("location")) {
                byte[] xml = "<LocationConstraint xmlns=\"http://s3.amazonaws.com/doc/2006-03-01/\">us-east-1</LocationConstraint>".getBytes(StandardCharsets.UTF_8);
                send(exchange, xml);
            } else if (exchange.getRequestURI().getPath().endsWith("/sample")) {
                int attempt = attempts.incrementAndGet();
                if (!partial && attempt == 1) {
                    exchange.close();
                } else if (partial) {
                    exchange.sendResponseHeaders(200, BYTES.length);
                    exchange.getResponseBody().write(BYTES, 0, 4);
                    exchange.close();
                } else { send(exchange, BYTES); }
            } else { send(exchange, BYTES); }
        });
        server.start();
        return server;
    }

    private void send(HttpExchange exchange, byte[] bytes) throws IOException {
        exchange.sendResponseHeaders(200, bytes.length);
        try (var out = exchange.getResponseBody()) { out.write(bytes); }
    }
}
