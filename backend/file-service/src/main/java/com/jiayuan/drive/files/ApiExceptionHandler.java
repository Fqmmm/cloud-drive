package com.jiayuan.drive.files;

import org.springframework.dao.DataAccessException;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.bind.ServletRequestBindingException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
import org.springframework.web.multipart.MaxUploadSizeExceededException;
import org.springframework.web.multipart.support.MissingServletRequestPartException;

@RestControllerAdvice
class ApiExceptionHandler {
    @ExceptionHandler(ApiError.class)
    ResponseEntity<Result<Void>> api(ApiError error) {
        return ResponseEntity.status(error.status).body(new Result<>(error.code, error.getMessage(), null));
    }

    @ExceptionHandler(MaxUploadSizeExceededException.class)
    ResponseEntity<Result<Void>> limit() {
        return api(new ApiError(413, "FILE_TOO_LARGE", "文件或请求超过大小限制"));
    }

    @ExceptionHandler({HttpMessageNotReadableException.class, ServletRequestBindingException.class,
            MethodArgumentTypeMismatchException.class, MissingServletRequestPartException.class})
    ResponseEntity<Result<Void>> invalid() {
        return api(new ApiError(400, "INVALID_REQUEST", "请求参数无效"));
    }

    @ExceptionHandler({DataAccessException.class, org.springframework.transaction.TransactionException.class})
    ResponseEntity<Result<Void>> unavailable() {
        return api(ApiError.dependency());
    }
}
