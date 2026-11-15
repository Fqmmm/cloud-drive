package com.jiayuan.drive.auth;

import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

/** Missing accountType means personal; supplied values must be exactly personal. */
public record Registration(
        @NotBlank @Pattern(regexp = "[A-Za-z0-9_]{3,32}") String accountName,
        @NotBlank @Size(min = 8, max = 64) String password,
        @NotBlank @Size(max = 32) String nickname,
        @NotBlank @Email @Size(max = 254) String email,
        @Pattern(regexp = "personal") String accountType) {
}
