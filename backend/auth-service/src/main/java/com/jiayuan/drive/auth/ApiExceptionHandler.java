package com.jiayuan.drive.auth;

import org.springframework.dao.DataAccessException;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.transaction.TransactionException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

/** Never reflect submitted passwords, JDBC errors or rejected field values. */
@RestControllerAdvice
class ApiExceptionHandler {
    @ExceptionHandler(ApiError.class)
    ResponseEntity<ApiResult<Void>> api(ApiError error) {
        return ResponseEntity.status(error.status)
                .body(new ApiResult<>(error.code, error.getMessage(), null));
    }

    @ExceptionHandler({MethodArgumentNotValidException.class, HttpMessageNotReadableException.class})
    ResponseEntity<ApiResult<Void>> invalid() {
        return api(new ApiError(400, "INVALID_REQUEST", "请检查必填项、长度与格式"));
    }

    @ExceptionHandler({DataAccessException.class, TransactionException.class})
    ResponseEntity<ApiResult<Void>> unavailable() {
        return api(new ApiError(503, "DEPENDENCY_UNAVAILABLE", "服务暂不可用，请稍后重试"));
    }
}
