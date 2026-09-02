"""Reads and writes for extracted documents.

Every query the API needs lives here, and each is written to fetch only what
its endpoint returns. That is the whole reason this layer exists: a filing page
can carry 700 cells and a megabyte of word coordinates, so a document listing
that innocently loaded `Document.pages` would ship all of it. The relationships
in `models` are configured but never eagerly loaded by these functions.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Document, DocumentPage, DocumentTable, DocumentTableCell
from extraction.types import CanonicalDocument, DocumentStatus
from storage.base import document_key


@dataclass(frozen=True, slots=True)
class Page[T]:
    """One slice of a listing, with the total so a client can size a pager."""

    items: list[T]
    total: int
    limit: int
    offset: int


# --- writes -----------------------------------------------------------------


async def create_document(
    session: AsyncSession,
    *,
    document_id: str,
    filename: str,
    file_size: int,
    sha256: str,
    mime_type: str = "application/pdf",
) -> Document:
    """Insert the row that an upload creates, before extraction runs."""
    document = Document(
        id=document_id,
        filename=filename,
        file_size=file_size,
        sha256=sha256,
        mime_type=mime_type,
        storage_key=document_key(document_id),
        status=DocumentStatus.PENDING.value,
        doc_metadata={},
    )
    session.add(document)
    await session.flush()
    return document


async def mark_processing(session: AsyncSession, document_id: str) -> None:
    document = await session.get(Document, document_id)
    if document is not None:
        document.status = DocumentStatus.PROCESSING.value
        document.error = None


async def mark_failed(session: AsyncSession, document_id: str, *, code: str, message: str) -> None:
    """Record a fatal extraction failure - PyMuPDF could not read the file."""
    document = await session.get(Document, document_id)
    if document is not None:
        document.status = DocumentStatus.FAILED.value
        document.error = {"code": code, "message": message}


async def save_extraction(session: AsyncSession, canonical: CanonicalDocument) -> Document:
    """Persist a canonical document, replacing any previous extraction.

    Re-extraction is expected - a new Azure model, a corrected threshold - so
    pages and tables are deleted and rewritten rather than merged. The document
    row itself survives, keeping its id, storage key, and upload timestamp.
    """
    document = await session.get(Document, canonical.document.id)
    if document is None:
        raise LookupError(f"Unknown document {canonical.document.id!r}")

    info = canonical.document
    document.page_count = info.page_count
    document.status = info.status.value
    document.doc_metadata = info.metadata
    document.is_encrypted = int(info.is_encrypted)
    document.file_size = info.file_size
    document.sha256 = info.sha256
    document.error = None

    extraction = canonical.extraction
    document.pymupdf_run = extraction.pymupdf.model_dump(mode="json")
    document.azure_run = extraction.azure_di.model_dump(mode="json")
    document.matching = _matching_payload(extraction.matching)
    document.matching_config = (
        extraction.config.model_dump(mode="json") if extraction.config else None
    )
    document.extracted_at = extraction.extracted_at

    # Cells cascade from tables at the ORM level, but these are bulk deletes,
    # so the cell rows are removed explicitly first.
    table_pks = (
        select(DocumentTable.id).where(DocumentTable.document_id == document.id).scalar_subquery()
    )
    await session.execute(delete(DocumentTableCell).where(DocumentTableCell.table_pk.in_(table_pks)))
    await session.execute(delete(DocumentTable).where(DocumentTable.document_id == document.id))
    await session.execute(delete(DocumentPage).where(DocumentPage.document_id == document.id))
    await session.flush()

    position = 0
    for page in canonical.pages:
        session.add(
            DocumentPage(
                document_id=document.id,
                page_number=page.page_number,
                width=page.geometry.width,
                height=page.geometry.height,
                rotation=page.geometry.rotation,
                mediabox=list(page.geometry.mediabox),
                has_text_layer=int(page.has_text_layer),
                text=page.content.text,
                content=page.content.model_dump(mode="json", exclude={"text"}),
            )
        )

        for table in page.tables:
            position += 1
            row = DocumentTable(
                document_id=document.id,
                table_id=table.id,
                position=position,
                page_number=table.page_number,
                source=table.source.value,
                bbox=list(table.bbox),
                row_count=table.row_count,
                column_count=table.column_count,
                caption=table.caption,
                confidence=table.confidence,
                continues_table_id=table.continues_table_id,
            )
            session.add(row)
            await session.flush()  # need row.id for the cells' foreign key

            session.add_all(
                DocumentTableCell(
                    table_pk=row.id,
                    row=cell.row,
                    column=cell.column,
                    row_span=cell.row_span,
                    column_span=cell.column_span,
                    kind=cell.kind,
                    text=cell.text,
                    azure_text=cell.azure_text,
                    pymupdf_text=cell.pymupdf_text,
                    bbox=list(cell.bbox),
                    confidence=cell.confidence,
                    text_source=cell.text_source.model_dump(mode="json"),
                )
                for cell in table.cells
            )

    await session.flush()
    return document


def _matching_payload(stats) -> dict:
    """Matching stats plus the derived rates, so clients need no arithmetic."""
    payload = stats.model_dump(mode="json")
    payload["content_cells"] = stats.content_cells
    payload["match_rate"] = round(stats.match_rate, 4)
    return payload


async def delete_document(session: AsyncSession, document_id: str) -> bool:
    document = await session.get(Document, document_id)
    if document is None:
        return False
    table_pks = (
        select(DocumentTable.id).where(DocumentTable.document_id == document_id).scalar_subquery()
    )
    await session.execute(delete(DocumentTableCell).where(DocumentTableCell.table_pk.in_(table_pks)))
    await session.execute(delete(DocumentTable).where(DocumentTable.document_id == document_id))
    await session.execute(delete(DocumentPage).where(DocumentPage.document_id == document_id))
    await session.delete(document)
    return True


# --- reads ------------------------------------------------------------------


async def get_document(session: AsyncSession, document_id: str) -> Document | None:
    return await session.get(Document, document_id)


async def list_documents(session: AsyncSession, *, limit: int, offset: int) -> Page[Document]:
    total = await session.scalar(select(func.count()).select_from(Document)) or 0
    rows = await session.scalars(
        select(Document).order_by(Document.created_at.desc(), Document.id).limit(limit).offset(offset)
    )
    return Page(items=list(rows), total=total, limit=limit, offset=offset)


async def list_pages(
    session: AsyncSession, document_id: str, *, limit: int, offset: int
) -> Page[DocumentPage]:
    """Page rows *without* their `content` blob.

    A page's word list is the largest thing in the database; the listing needs
    geometry and a text-layer flag only. `content` is deferred by selecting
    columns explicitly rather than by loading the entity and hoping.
    """
    total = await session.scalar(
        select(func.count()).select_from(DocumentPage).where(DocumentPage.document_id == document_id)
    ) or 0
    rows = await session.execute(
        select(
            DocumentPage.page_number,
            DocumentPage.width,
            DocumentPage.height,
            DocumentPage.rotation,
            DocumentPage.mediabox,
            DocumentPage.has_text_layer,
            func.length(DocumentPage.text).label("text_length"),
        )
        .where(DocumentPage.document_id == document_id)
        .order_by(DocumentPage.page_number)
        .limit(limit)
        .offset(offset)
    )
    return Page(items=[row._mapping for row in rows], total=total, limit=limit, offset=offset)


async def get_page(session: AsyncSession, document_id: str, page_number: int) -> DocumentPage | None:
    return await session.scalar(
        select(DocumentPage).where(
            DocumentPage.document_id == document_id, DocumentPage.page_number == page_number
        )
    )


async def count_tables_per_page(session: AsyncSession, document_id: str) -> dict[int, int]:
    rows = await session.execute(
        select(DocumentTable.page_number, func.count())
        .where(DocumentTable.document_id == document_id)
        .group_by(DocumentTable.page_number)
    )
    return {page_number: count for page_number, count in rows}


async def list_tables(
    session: AsyncSession,
    document_id: str,
    *,
    limit: int,
    offset: int,
    page_number: int | None = None,
) -> Page[DocumentTable]:
    """Table metadata only - cells are fetched per table, never in a listing."""
    filters = [DocumentTable.document_id == document_id]
    if page_number is not None:
        filters.append(DocumentTable.page_number == page_number)

    total = await session.scalar(select(func.count()).select_from(DocumentTable).where(*filters)) or 0
    rows = await session.scalars(
        select(DocumentTable).where(*filters).order_by(DocumentTable.position).limit(limit).offset(offset)
    )
    return Page(items=list(rows), total=total, limit=limit, offset=offset)


async def get_table(session: AsyncSession, document_id: str, table_id: str) -> DocumentTable | None:
    return await session.scalar(
        select(DocumentTable).where(
            DocumentTable.document_id == document_id, DocumentTable.table_id == table_id
        )
    )


async def get_cells(session: AsyncSession, table_pk: int) -> Sequence[DocumentTableCell]:
    rows = await session.scalars(
        select(DocumentTableCell)
        .where(DocumentTableCell.table_pk == table_pk)
        .order_by(DocumentTableCell.row, DocumentTableCell.column)
    )
    return list(rows)


async def list_cells(
    session: AsyncSession, table_pk: int, *, limit: int, offset: int
) -> Page[DocumentTableCell]:
    total = await session.scalar(
        select(func.count()).select_from(DocumentTableCell).where(DocumentTableCell.table_pk == table_pk)
    ) or 0
    rows = await session.scalars(
        select(DocumentTableCell)
        .where(DocumentTableCell.table_pk == table_pk)
        .order_by(DocumentTableCell.row, DocumentTableCell.column)
        .limit(limit)
        .offset(offset)
    )
    return Page(items=list(rows), total=total, limit=limit, offset=offset)
