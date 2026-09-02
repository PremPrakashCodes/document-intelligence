"""The storage seam.

Deliberately tiny: put, get, delete, exists. The pipeline needs the original
bytes back to re-render a page long after upload, and nothing more. Keeping the
interface this small is what lets the in-memory implementation stand in for R2
in tests without pretending to be S3.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


class StorageError(Exception):
    """A blob operation failed. Carries a stable `code` for the API layer."""

    def __init__(self, message: str, *, code: str = "storage_error"):
        super().__init__(message)
        self.message = message
        self.code = code


class ObjectNotFound(StorageError):
    def __init__(self, key: str):
        super().__init__(f"No stored object at {key!r}", code="object_not_found")
        self.key = key


@runtime_checkable
class DocumentStore(Protocol):
    async def put(self, key: str, data: bytes, *, content_type: str = "application/pdf") -> str: ...

    async def get(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...

    async def exists(self, key: str) -> bool: ...


def document_key(document_id: str, filename: str = "source.pdf") -> str:
    """Object key for a document's original bytes.

    One prefix per document keeps every derived artefact - the source now,
    thumbnails or exports later - under a single deletable path.
    """
    return f"documents/{document_id}/{filename}"
