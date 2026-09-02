"""An in-process store, for tests and for running without R2 credentials."""

from __future__ import annotations

import asyncio

from storage.base import DocumentStore, ObjectNotFound


class InMemoryDocumentStore(DocumentStore):
    """Holds objects in a dict. Not durable; not for production."""

    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}
        self._lock = asyncio.Lock()

    async def put(self, key: str, data: bytes, *, content_type: str = "application/pdf") -> str:
        async with self._lock:
            self._objects[key] = data
        return key

    async def get(self, key: str) -> bytes:
        try:
            return self._objects[key]
        except KeyError as err:
            raise ObjectNotFound(key) from err

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._objects.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self._objects
