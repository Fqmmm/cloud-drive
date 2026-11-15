package com.jiayuan.drive.auth;

import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

@RestController
class AuthController {
    private final AccountRegistration registration;
    private final AccountLogin login;

    AuthController(AccountRegistration registration, AccountLogin login) {
        this.registration = registration;
        this.login = login;
    }

    @PostMapping("/api/v1/auth/register")
    ApiResult<Void> register(@Valid @RequestBody Registration request) {
        registration.register(request);
        return ApiResult.ok(null);
    }

    @PostMapping("/api/v1/auth/login")
    ApiResult<AccountLogin.LoginResult> login(@Valid @RequestBody AccountLogin.LoginRequest request) {
        return ApiResult.ok(login.login(request));
    }

    @GetMapping("/api/v1/users/me")
    ApiResult<AccountLogin.Profile> me(@RequestHeader(value = "Authorization", required = false) String authorization) {
        return ApiResult.ok(login.me(authorization));
    }
}
