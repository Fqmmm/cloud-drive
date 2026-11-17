package com.jiayuan.drive.files;

import io.minio.*;
import io.minio.errors.ErrorResponseException;
import okhttp3.OkHttpClient;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.multipart.MultipartFile;

import java.io.InputStream;
import java.util.concurrent.TimeUnit;

@Component
final class ObjectStorage {
    private static final String BUCKET = "cloud-drive";
    private final MinioClient client;
    private final MinioClient downloads;
    private final MinioClient control;
    private boolean initialized;

    ObjectStorage(@Value("${file-service.minio-endpoint}") String endpoint,
                  @Value("${file-service.minio-user}") String user,
                  @Value("${file-service.minio-password}") String password) {
        var transport = new OkHttpClient.Builder().connectTimeout(3, TimeUnit.SECONDS)
                .readTimeout(120, TimeUnit.SECONDS).writeTimeout(120, TimeUnit.SECONDS)
                .retryOnConnectionFailure(false).build();
        client = MinioClient.builder().endpoint(endpoint).credentials(user, password).httpClient(transport).build();
        // GET may reconnect before response headers if a pooled socket died.
        // Uploads keep their original non-retrying transport; an opened stream
        // is returned directly and is never replayed after partial consumption.
        downloads = MinioClient.builder().endpoint(endpoint).credentials(user, password)
                .httpClient(transport.newBuilder().retryOnConnectionFailure(true).build()).build();
        control = MinioClient.builder().endpoint(endpoint).credentials(user, password)
                .httpClient(transport.newBuilder().callTimeout(3, TimeUnit.SECONDS).build()).build();
    }

    synchronized void ensureBucket() throws Exception {
        if (!control.bucketExists(BucketExistsArgs.builder().bucket(BUCKET).build())) {
            initialized = false;
            control.makeBucket(MakeBucketArgs.builder().bucket(BUCKET).build());
        }
        if (!initialized) {
            try {
                control.deleteBucketPolicy(DeleteBucketPolicyArgs.builder().bucket(BUCKET).build());
            } catch (ErrorResponseException error) {
                if (!"NoSuchBucketPolicy".equals(error.errorResponse().code())) {
                    throw error;
                }
            }
            initialized = true;
        }
    }

    void put(String key, MultipartFile file) throws Exception {
        try (InputStream content = file.getInputStream()) {
            client.putObject(PutObjectArgs.builder().bucket(BUCKET).object(key)
                    .stream(content, file.getSize(), -1).contentType("application/octet-stream").build());
        }
    }

    InputStream open(String key) throws Exception {
        return downloads.getObject(GetObjectArgs.builder().bucket(BUCKET).object(key).build());
    }

    void delete(String key) throws Exception {
        control.removeObject(RemoveObjectArgs.builder().bucket(BUCKET).object(key).build());
    }
}
