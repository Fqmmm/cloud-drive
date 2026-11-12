package com.jiayuan.drive.files;

import jakarta.servlet.http.HttpServletResponse;
import org.springframework.http.ContentDisposition;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;

@RestController
class FileController {
    record Name(String name) {}
    record Directory(String name, Long parentId) {}
    record Metadata(String id, String ownerId, String originalName, long fileSize,
                    String mimeType, boolean isDirectory) {}

    private final FileCatalog catalog;
    private final ObjectStorage storage;

    FileController(FileCatalog catalog, ObjectStorage storage) {
        this.catalog = catalog;
        this.storage = storage;
    }

    @GetMapping("/api/v1/files")
    Result<FileCatalog.Listing> list(@RequestAttribute("fileOwner") long owner,
                                    @RequestParam(defaultValue = "0") long parentId) {
        return Result.ok(catalog.list(owner, parentId));
    }

    @GetMapping("/api/v1/directories")
    Result<List<FileCatalog.Item>> directories(@RequestAttribute("fileOwner") long owner,
                                               @RequestParam(defaultValue = "0") long parentId) {
        return Result.ok(catalog.list(owner, parentId).items().stream().filter(FileCatalog.Item::isDirectory).toList());
    }

    @PostMapping("/api/v1/directories")
    Result<FileCatalog.Item> create(@RequestAttribute("fileOwner") long owner, @RequestBody Directory request) {
        return Result.ok(catalog.createDirectory(owner, request.parentId() == null ? 0 : request.parentId(),
                request.name()));
    }

    @PostMapping(value = "/api/v1/files", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    Result<FileCatalog.Item> upload(@RequestAttribute("fileOwner") long owner,
                                     @RequestParam(defaultValue = "0") long parentId,
                                     @RequestPart MultipartFile file) {
        return Result.ok(catalog.upload(owner, parentId, file));
    }

    @GetMapping("/api/v1/quota")
    Result<FileCatalog.Quota> quota(@RequestAttribute("fileOwner") long owner) {
        return Result.ok(catalog.quota(owner));
    }

    @PutMapping("/api/v1/files/{id}/rename")
    Result<FileCatalog.Item> renameFile(@RequestAttribute("fileOwner") long owner, @PathVariable long id,
                                       @RequestBody Name request) {
        return Result.ok(catalog.rename(owner, id, false, request.name()));
    }

    @PutMapping("/api/v1/directories/{id}/rename")
    Result<FileCatalog.Item> renameDirectory(@RequestAttribute("fileOwner") long owner, @PathVariable long id,
                                            @RequestBody Name request) {
        return Result.ok(catalog.rename(owner, id, true, request.name()));
    }

    @DeleteMapping("/api/v1/files/{id}")
    Result<Void> deleteFile(@RequestAttribute("fileOwner") long owner, @PathVariable long id) {
        catalog.delete(owner, id, false);
        return Result.ok(null);
    }

    @DeleteMapping("/api/v1/directories/{id}")
    Result<Void> deleteDirectory(@RequestAttribute("fileOwner") long owner, @PathVariable long id) {
        catalog.delete(owner, id, true);
        return Result.ok(null);
    }

    @GetMapping("/api/v1/files/{id}/download")
    void download(@RequestAttribute("fileOwner") long owner, @PathVariable long id,
                  HttpServletResponse response) throws IOException {
        stream(catalog.requireKind(owner, id, false), response);
    }

    @GetMapping("/internal/v1/files/{id}")
    Result<Metadata> metadata(@PathVariable long id, @RequestParam long ownerId) {
        FileCatalog.Item item = catalog.get(ownerId, id).item();
        return Result.ok(new Metadata(item.id(), Long.toString(ownerId), item.originalName(),
                item.fileSize(), item.mimeType(), item.isDirectory()));
    }

    @GetMapping("/internal/v1/files/{id}/content")
    void internalDownload(@PathVariable long id, @RequestParam long ownerId,
                          HttpServletResponse response) throws IOException {
        stream(catalog.requireKind(ownerId, id, false), response);
    }

    @GetMapping("/health/live")
    Map<String, String> live() {
        return Map.of("status", "UP");
    }

    @GetMapping("/health/ready")
    ResponseEntity<Map<String, String>> ready() {
        boolean ready = catalog.ready();
        return ResponseEntity.status(ready ? 200 : 503).body(Map.of("status", ready ? "UP" : "DOWN"));
    }

    private void stream(FileCatalog.Stored file, HttpServletResponse response) throws IOException {
        InputStream source;
        try {
            source = storage.open(file.key());
        } catch (Exception unavailable) {
            throw ApiError.dependency();
        }

        try (source) {
            response.setContentType(MediaType.APPLICATION_OCTET_STREAM_VALUE);
            response.setContentLengthLong(file.item().fileSize());
            response.setHeader("Content-Disposition", ContentDisposition.attachment()
                    .filename(file.item().originalName(), StandardCharsets.UTF_8).build().toString());
            source.transferTo(response.getOutputStream());
        }
    }
}
