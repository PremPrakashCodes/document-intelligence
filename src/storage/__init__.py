"""Blob storage for original PDFs, behind one narrow interface."""

from storage.base import DocumentStore, StorageError, document_key
from storage.memory import InMemoryDocumentStore
from storage.r2 import R2DocumentStore, build_store

__all__ = [
    "DocumentStore",
    "InMemoryDocumentStore",
    "R2DocumentStore",
    "StorageError",
    "build_store",
    "document_key",
]
