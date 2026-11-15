package com.jiayuan.drive.auth;

import java.net.HttpURLConnection;
import java.net.URI;

/** Standalone probe uses only the JRE; no shell, curl or Spring boot is needed. */
public final class HealthProbe {
    public static void main(String[] args) {
        HttpURLConnection connection = null;
        int result = 1;
        try {
            String port = System.getenv().getOrDefault("SERVER_PORT", "8080");
            int number = Integer.parseInt(port);
            if (number < 1 || number > 65535) { throw new IllegalArgumentException("Invalid HTTP port"); }
            connection = (HttpURLConnection) URI.create("http://127.0.0.1:" + number + "/health/ready").toURL().openConnection();
            connection.setConnectTimeout(1000);
            connection.setReadTimeout(4000);
            result = connection.getResponseCode() == 200 ? 0 : 1;
        } catch (Exception unavailable) {
            // Probe failures expose no connection details.
        } finally {
            if (connection != null) { connection.disconnect(); }
        }
        System.exit(result);
    }
}
