package com.jiayuan.drive.shares;

/** Public JSON envelope; identifiers in its payload are decimal strings. */
public record ApiResult<T>(String code, String msg, T data) {
    public static <T> ApiResult<T> ok(T data) {
        return new ApiResult<>("00000", "成功", data);
    }
}
