package com.jiayuan.drive.shares;

import java.sql.Connection;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.Map;
import javax.sql.DataSource;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

/** Probes deliberately expose no database details or exception messages. */
@RestController
public class HealthController {
    private final DataSource dataSource;

    public HealthController(DataSource dataSource) {
        this.dataSource = dataSource;
    }

    /** Liveness stays independent of external services during a database outage. */
    @GetMapping("/health/live")
    public Map<String, String> live() {
        return Map.of("status", "UP");
    }

    /** Each request borrows a fresh connection so readiness can recover without restart. */
    @GetMapping("/health/ready")
    public ResponseEntity<Map<String, String>> ready() {
        try (Connection connection = dataSource.getConnection();
             Statement statement = connection.createStatement()) {
            statement.setQueryTimeout(2);
            try (var result = statement.executeQuery("SELECT 1")) {
                if (result.next() && result.getInt(1) == 1) {
                    return ResponseEntity.ok(Map.of("status", "UP"));
                }
            }
        } catch (SQLException unavailable) {
            // Hikari and the JDBC driver bound connection/query waits; never leak credentials.
        }
        return ResponseEntity.status(503).body(Map.of("status", "DOWN"));
    }
}
