"""FastAPI dependencies: the wiring point for everything injectable.

Handlers ask for a session, a store, or a pipeline and get one; tests override
these with `app.dependency_overrides` rather than reaching into module globals.
The store and pipeline are cached per process because both hold connection
state that is expensive to rebuild per request.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import Settings, get_settings
from db import repository
from db.models import Document, DocumentTable
from db.session import get_sessionmaker
from extraction.pipeline import ExtractionPipeline, build_pipeline
from storage.base import DocumentStore
from storage.r2 import build_store


async def get_session() -> AsyncIterator[AsyncSession]:
    """One session per request, committed if the handler returns cleanly."""
    async with get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@lru_cache
def get_store() -> DocumentStore:
    return build_store(get_settings())


@lru_cache
def get_pipeline() -> ExtractionPipeline:
    return build_pipeline(get_settings())


SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
StoreDep = Annotated[DocumentStore, Depends(get_store)]
PipelineDep = Annotated[ExtractionPipeline, Depends(get_pipeline)]


class Pagination:
    """Shared `limit`/`offset` for every listing endpoint."""

    def __init__(
        self,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> None:
        self.limit = limit
        self.offset = offset


PaginationDep = Annotated[Pagination, Depends(Pagination)]


async def get_document_or_404(
    session: SessionDep,
    document_id: Annotated[str, Path(max_length=64)],
) -> Document:
    document = await repository.get_document(session, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail=f"No document {document_id!r}")
    return document


DocumentDep = Annotated[Document, Depends(get_document_or_404)]


async def get_table_or_404(
    session: SessionDep,
    document: DocumentDep,
    table_id: Annotated[str, Path(max_length=64)],
) -> DocumentTable:
    table = await repository.get_table(session, document.id, table_id)
    if table is None:
        raise HTTPException(status_code=404, detail=f"No table {table_id!r} on document {document.id!r}")
    return table


TableDep = Annotated[DocumentTable, Depends(get_table_or_404)]
