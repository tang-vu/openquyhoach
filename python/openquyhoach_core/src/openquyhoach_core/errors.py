"""Domain errors with stable codes — surfaced as structured API errors."""

from __future__ import annotations


class OQHError(Exception):
    code = "internal_error"
    http_status = 500

    def __init__(self, message: str, *, detail: dict | None = None):
        super().__init__(message)
        self.message = message
        self.detail = detail or {}


class NotFoundError(OQHError):
    code = "not_found"
    http_status = 404


class ConflictError(OQHError):
    code = "conflict"
    http_status = 409


class ValidationError(OQHError):
    code = "validation_error"
    http_status = 422


class FetchBlockedError(OQHError):
    """URL rejected by fetch policy (SSRF guard, size cap, scheme)."""

    code = "fetch_blocked"
    http_status = 400


class SourceDisabledError(OQHError):
    code = "source_disabled"
    http_status = 409


class UnreviewedDataError(OQHError):
    """Raised when an operation requires human review that has not happened."""

    code = "unreviewed"
    http_status = 409


class UnsupportedFormatError(OQHError):
    code = "unsupported_format"
    http_status = 415


class CRSError(OQHError):
    code = "crs_error"
    http_status = 422
