package com.jiayuan.drive.files;

record Result<T>(String code, String msg, T data) {
    static <T> Result<T> ok(T data) {
        return new Result<>("00000", "OK", data);
    }
}

final class ApiError extends RuntimeException {
    final int status;
    final String code;

    ApiError(int status, String code, String message) {
        super(message);
        this.status = status;
        this.code = code;
    }

    static ApiError missing() {
        return new ApiError(404, "FILE_NOT_FOUND", "文件或目录不存在");
    }

    static ApiError dependency() {
        return new ApiError(503, "DEPENDENCY_UNAVAILABLE", "存储暂不可用");
    }
}
