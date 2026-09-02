"""Cloudflare R2 via its S3-compatible API.

boto3 is synchronous, so every call is pushed to a worker thread rather than
blocking the event loop. The client itself is built once and shared: botocore
clients are thread-safe for calls, and rebuilding one per request would redo
TLS and credential setup each time.

R2 ignores regions but botocore insists on one; "auto" is the value Cloudflare
documents. Signature v4 with the virtual-addressing style off is what R2's
endpoint expects.
"""

from __future__ import annotations

import asyncio
import logging
from functools import cached_property

from storage.base import DocumentStore, ObjectNotFound, StorageError

log = logging.getLogger(__name__)


class R2DocumentStore(DocumentStore):
    def __init__(
        self,
        *,
        endpoint_url: str,
        access_key_id: str,
        secret_access_key: str,
        bucket: str,
    ) -> None:
        self._endpoint_url = endpoint_url
        self._access_key_id = access_key_id
        self._secret_access_key = secret_access_key
        self._bucket = bucket

    @cached_property
    def _client(self):
        import boto3
        from botocore.config import Config

        return boto3.client(
            "s3",
            endpoint_url=self._endpoint_url,
            aws_access_key_id=self._access_key_id,
            aws_secret_access_key=self._secret_access_key,
            region_name="auto",
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )

    async def put(self, key: str, data: bytes, *, content_type: str = "application/pdf") -> str:
        await asyncio.to_thread(self._put, key, data, content_type)
        return key

    def _put(self, key: str, data: bytes, content_type: str) -> None:
        try:
            self._client.put_object(
                Bucket=self._bucket, Key=key, Body=data, ContentType=content_type
            )
        except Exception as err:
            raise StorageError(f"Could not store {key!r}: {err}", code="storage_put_failed") from err

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(self._get, key)

    def _get(self, key: str) -> bytes:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
            return response["Body"].read()
        except Exception as err:
            if _is_missing(err):
                raise ObjectNotFound(key) from err
            raise StorageError(f"Could not read {key!r}: {err}", code="storage_get_failed") from err

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._delete, key)

    def _delete(self, key: str) -> None:
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
        except Exception as err:
            raise StorageError(f"Could not delete {key!r}: {err}", code="storage_delete_failed") from err

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._exists, key)

    def _exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except Exception as err:
            if _is_missing(err):
                return False
            raise StorageError(f"Could not stat {key!r}: {err}", code="storage_head_failed") from err


def _is_missing(err: Exception) -> bool:
    """True for the several shapes botocore uses to say "no such object"."""
    code = getattr(err, "response", {}).get("Error", {}).get("Code") if hasattr(err, "response") else None
    if code in ("NoSuchKey", "NotFound", "404"):
        return True
    status = getattr(err, "response", {}).get("ResponseMetadata", {}).get("HTTPStatusCode") if hasattr(err, "response") else None
    return status == 404


def build_store(settings) -> DocumentStore:
    """R2 when it is configured, an in-memory store otherwise.

    Falling back keeps the API and the test suite runnable on a machine with no
    R2 credentials; the log line makes the downgrade impossible to miss.
    """
    if not settings.r2_configured:
        log.warning(
            "R2 is not configured (R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY / "
            "R2_BUCKET_NAME); falling back to in-memory storage, which is lost on restart"
        )
        from storage.memory import InMemoryDocumentStore

        return InMemoryDocumentStore()

    return R2DocumentStore(
        endpoint_url=settings.r2_endpoint,
        access_key_id=settings.r2_access_key_id,
        secret_access_key=settings.r2_secret_access_key,
        bucket=settings.r2_bucket_name,
    )
