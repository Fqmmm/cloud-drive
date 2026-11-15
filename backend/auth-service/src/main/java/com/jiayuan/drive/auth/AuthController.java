package com.jiayuan.drive.auth;

import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

@RestController
class AuthController {
    private final AccountRegistration registration;

    AuthController(AccountRegistration registration) {
        this.registration = registration;
    }

    @PostMapping("/api/v1/auth/register")
    ApiResult<Void> register(@Valid @RequestBody Registration request) {
        registration.register(request);
        return ApiResult.ok(null);
    }
}
