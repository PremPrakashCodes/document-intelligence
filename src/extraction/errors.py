"""Extraction failures, mapped to stable codes the API and UI can key off."""

from __future__ import annotations


class ExtractionFailure(Exception):
    """Base class. `code` is a stable identifier; `retryable` gates retries."""

    code = "extraction_failed"
    retryable = False

    def __init__(self, message: str, *, code: str | None = None, retryable: bool | None = None):
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if retryable is not None:
            self.retryable = retryable


# --- PyMuPDF: these are fatal, since nothing downstream can proceed ---------


class InvalidPdfError(ExtractionFailure):
    """The bytes are not a PDF, or are damaged past MuPDF's recovery."""

    code = "invalid_pdf"


class EmptyPdfError(ExtractionFailure):
    """A structurally valid PDF with zero pages."""

    code = "empty_pdf"


class EncryptedPdfError(ExtractionFailure):
    """Password-protected, and the empty password did not open it."""

    code = "encrypted_pdf"


# --- Azure DI: recoverable; PyMuPDF output still stands ---------------------


class AzureNotConfiguredError(ExtractionFailure):
    code = "azure_not_configured"


class AzureAuthError(ExtractionFailure):
    """401/403 - a new key is needed, so retrying is pointless."""

    code = "azure_auth_failed"


class AzureRateLimitError(ExtractionFailure):
    code = "azure_rate_limited"
    retryable = True


class AzureTimeoutError(ExtractionFailure):
    code = "azure_timeout"
    retryable = True


class AzureServiceError(ExtractionFailure):
    """Any other failure from the service or the network in front of it."""

    code = "azure_service_error"
    retryable = True


class AzureUnsupportedDocumentError(ExtractionFailure):
    """The service rejected the document itself; a retry sends the same bytes."""

    code = "azure_unsupported_document"
