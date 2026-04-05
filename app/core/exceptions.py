"""
Custom exception classes and standard error codes.

All application errors inherit from AppException so the global
error handler can catch them and return a standardized JSON response.
"""


class AppException(Exception):
    """Base exception for all application errors."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: list | None = None,
    ):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or []


# ── Specific Exceptions ───────────────────────────────────────


class AuthenticationException(AppException):
    def __init__(self, message: str = "Authentication required"):
        super().__init__(
            code="AUTHENTICATION_ERROR", message=message, status_code=401
        )


class AuthorizationException(AppException):
    def __init__(self, message: str = "You do not have access to this resource"):
        super().__init__(
            code="AUTHORIZATION_ERROR", message=message, status_code=403
        )


class NotFoundException(AppException):
    def __init__(self, resource: str = "Resource"):
        super().__init__(
            code="NOT_FOUND", message=f"{resource} not found", status_code=404
        )


class SessionExpiredException(AppException):
    def __init__(self, message: str = "Upload session has expired. Please upload your CSV again."):
        super().__init__(
            code="SESSION_EXPIRED", message=message, status_code=410
        )


class FileTooLargeException(AppException):
    def __init__(self, max_size_mb: int = 10):
        super().__init__(
            code="FILE_TOO_LARGE",
            message=f"File exceeds maximum size of {max_size_mb}MB",
            status_code=413,
        )


class RowLimitExceededException(AppException):
    def __init__(self, max_rows: int = 50_000):
        super().__init__(
            code="ROW_LIMIT_EXCEEDED",
            message=f"CSV exceeds maximum of {max_rows:,} rows",
            status_code=422,
        )


class ValidationException(AppException):
    def __init__(self, message: str = "Invalid input data", details: list | None = None):
        super().__init__(
            code="VALIDATION_ERROR",
            message=message,
            status_code=422,
            details=details,
        )


class InsufficientDataException(AppException):
    def __init__(self):
        super().__init__(
            code="INSUFFICIENT_DATA",
            message="At least 6 months of historical data required",
            status_code=422,
        )


class ForecastFailedException(AppException):
    def __init__(self, reason: str = "Model training failed"):
        super().__init__(
            code="FORECAST_FAILED", message=reason, status_code=500
        )


class AIServiceException(AppException):
    def __init__(self, message: str = "AI service unavailable"):
        super().__init__(
            code="AI_SERVICE_ERROR", message=message, status_code=503
        )


class DuplicateEmailException(AppException):
    def __init__(self):
        super().__init__(
            code="DUPLICATE_EMAIL",
            message="An account with this email already exists",
            status_code=409,
        )


class WeakPasswordException(AppException):
    def __init__(self, message: str = "Password does not meet strength requirements"):
        super().__init__(
            code="WEAK_PASSWORD", message=message, status_code=422
        )


class InvalidCredentialsException(AppException):
    def __init__(self):
        super().__init__(
            code="INVALID_CREDENTIALS",
            message="Wrong email or password",
            status_code=401,
        )


class TokenExpiredException(AppException):
    def __init__(self):
        super().__init__(
            code="TOKEN_EXPIRED",
            message="JWT token has expired",
            status_code=401,
        )


class RateLimitExceededException(AppException):
    def __init__(self):
        super().__init__(
            code="RATE_LIMIT_EXCEEDED",
            message="Too many requests. Please try again later.",
            status_code=429,
        )
