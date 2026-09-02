"""Documents: upload, inspect, and trace extracted tables back to the PDF.

Payload discipline is the theme. A single filing page here carries 747 words
and 714 cells, so listings return metadata and the heavy parts are fetched only
when something is opened: pages without their word list, tables without their
cells, cells paginated on demand.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import StreamingResponse

from api.deps import (
    DocumentDep,
    PaginationDep,
    PipelineDep,
    SessionDep,
    SettingsDep,
    StoreDep,
    TableDep,
)
from api.schemas import (
    DocumentDetail,
    DocumentSummary,
    ExtractionOut,
    PageDetail,
    PageGeometryOut,
    PageSummary,
    Paginated,
    TableCellOut,
    TableDetail,
    TableSummary,
    UploadResponse,
)
from db import repository
from db.models import Document
from extraction.errors import ExtractionFailure
from storage.base import ObjectNotFound, StorageError, document_key

log = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])

_PDF_MAGIC = b"%PDF-"


# --- upload -----------------------------------------------------------------


@router.post("", status_code=202, response_model=UploadResponse)
async def upload_document(
    session: SessionDep,
    store: StoreDep,
    settings: SettingsDep,
    file: Annotated[UploadFile, File()],
) -> UploadResponse:
    """Accept a PDF, store it, and queue extraction.

    Returns 202: extraction takes seconds to minutes, so the client polls
    `GET /documents/{id}` for `status`. Storing the bytes before enqueuing
    means a job can never reference an object that is not there yet.
    """
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded file is empty")
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"The file is larger than the {settings.max_upload_bytes // (1024 * 1024)}MB limit",
        )
    if not data.startswith(_PDF_MAGIC):
        # Cheap up-front check; PyMuPDF will still reject a corrupt body.
        raise HTTPException(status_code=415, detail="Only PDF files are accepted")

    document_id = f"doc_{uuid.uuid4().hex[:16]}"
    document = await repository.create_document(
        session,
        document_id=document_id,
        filename=file.filename or "document.pdf",
        file_size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        mime_type=file.content_type or "application/pdf",
    )

    try:
        await store.put(document.storage_key, data, content_type="application/pdf")
    except StorageError as err:
        log.exception("could not store %s", document_id)
        raise HTTPException(status_code=502, detail=f"Could not store the document: {err.message}") from err

    job_id = await _enqueue_extraction(document_id)
    return UploadResponse(id=document.id, filename=document.filename, status=document.status, job_id=job_id)


async def _enqueue_extraction(document_id: str) -> str | None:
    """Queue the extraction job, tolerating a queue that is not reachable.

    A failure here leaves the document `pending` with its bytes safely stored,
    so `POST /documents/{id}/extract` can pick it up later. Losing the upload
    because the queue blinked would be the worse outcome.
    """
    from jobs.queues import DOCUMENTS, get_queue

    try:
        job = await get_queue(DOCUMENTS).add("extract-document", {"document_id": document_id})
        return job.id
    except Exception:
        log.exception("could not enqueue extraction for %s", document_id)
        return None


@router.post("/{document_id}/extract", status_code=202, response_model=UploadResponse)
async def reextract_document(document: DocumentDep) -> UploadResponse:
    """Re-run extraction over the stored bytes - after a threshold change, say."""
    job_id = await _enqueue_extraction(document.id)
    if job_id is None:
        raise HTTPException(status_code=503, detail="The extraction queue is unavailable")
    return UploadResponse(id=document.id, filename=document.filename, status=document.status, job_id=job_id)


# --- documents --------------------------------------------------------------


@router.get("", response_model=Paginated[DocumentSummary])
async def list_documents(session: SessionDep, pagination: PaginationDep) -> Paginated[DocumentSummary]:
    result = await repository.list_documents(session, limit=pagination.limit, offset=pagination.offset)
    return Paginated[DocumentSummary](
        items=[DocumentSummary.model_validate(row) for row in result.items],
        total=result.total,
        limit=result.limit,
        offset=result.offset,
    )


@router.get("/{document_id}", response_model=DocumentDetail)
async def get_document(session: SessionDep, document: DocumentDep) -> DocumentDetail:
    counts = await repository.count_tables_per_page(session, document.id)
    return _document_detail(document, table_count=sum(counts.values()))


def _document_detail(document: Document, *, table_count: int) -> DocumentDetail:
    extraction = None
    if document.pymupdf_run is not None:
        extraction = ExtractionOut.model_validate(
            {
                "pymupdf": document.pymupdf_run,
                "azure_di": document.azure_run or {"completed": False},
                "matching": document.matching or {},
                "config": document.matching_config,
                "extracted_at": document.extracted_at,
            }
        )
    return DocumentDetail(
        id=document.id,
        filename=document.filename,
        mime_type=document.mime_type,
        file_size=document.file_size,
        sha256=document.sha256,
        page_count=document.page_count,
        status=document.status,
        created_at=document.created_at,
        updated_at=document.updated_at,
        metadata=document.doc_metadata or {},
        is_encrypted=bool(document.is_encrypted),
        extraction=extraction,
        error=document.error,
        table_count=table_count,
    )


@router.delete("/{document_id}", status_code=204)
async def delete_document(session: SessionDep, store: StoreDep, document: DocumentDep) -> Response:
    """Remove the document, its extraction, and the stored PDF."""
    key = document.storage_key
    await repository.delete_document(session, document.id)
    try:
        await store.delete(key)
    except StorageError:
        # The rows are gone; an orphaned blob is a cleanup problem, not a
        # reason to fail the request or leave the database inconsistent.
        log.warning("deleted document %s but could not remove %s", document.id, key)
    return Response(status_code=204)


# --- the original file ------------------------------------------------------


@router.get("/{document_id}/file")
async def get_document_file(store: StoreDep, document: DocumentDep) -> Response:
    data = await _load_pdf(store, document)
    return Response(
        content=data,
        media_type=document.mime_type or "application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{document.filename}"',
            # Immutable: a document's bytes never change once uploaded.
            "Cache-Control": "private, max-age=3600, immutable",
        },
    )


async def _load_pdf(store, document: Document) -> bytes:
    try:
        return await store.get(document.storage_key)
    except ObjectNotFound as err:
        raise HTTPException(status_code=404, detail="The stored PDF is no longer available") from err
    except StorageError as err:
        raise HTTPException(status_code=502, detail=f"Could not read the stored PDF: {err.message}") from err


# --- pages ------------------------------------------------------------------


@router.get("/{document_id}/pages", response_model=Paginated[PageSummary])
async def list_pages(
    session: SessionDep, document: DocumentDep, pagination: PaginationDep
) -> Paginated[PageSummary]:
    result = await repository.list_pages(
        session, document.id, limit=pagination.limit, offset=pagination.offset
    )
    counts = await repository.count_tables_per_page(session, document.id)
    return Paginated[PageSummary](
        items=[
            PageSummary(
                page_number=row["page_number"],
                geometry=PageGeometryOut(
                    width=row["width"],
                    height=row["height"],
                    rotation=row["rotation"],
                    mediabox=tuple(row["mediabox"]),
                ),
                has_text_layer=bool(row["has_text_layer"]),
                text_length=row["text_length"] or 0,
                table_count=counts.get(row["page_number"], 0),
            )
            for row in result.items
        ],
        total=result.total,
        limit=result.limit,
        offset=result.offset,
    )


@router.get("/{document_id}/pages/{page_number}", response_model=PageDetail)
async def get_page(
    session: SessionDep,
    document: DocumentDep,
    page_number: int,
    include: Annotated[
        list[str] | None,
        Query(description="Content keys to return: blocks, words, images, links, annotations, fonts."),
    ] = None,
) -> PageDetail:
    """One page in full.

    `include` trims the content payload - the frontend's PDF overlay wants
    `words` and nothing else, and the word list dominates the response.
    """
    page = await repository.get_page(session, document.id, page_number)
    if page is None:
        raise HTTPException(status_code=404, detail=f"Document {document.id!r} has no page {page_number}")

    content: dict[str, Any] = dict(page.content or {})
    if include:
        wanted = {key for key in include}
        unknown = wanted - set(content)
        if unknown:
            raise HTTPException(status_code=400, detail=f"Unknown content keys: {', '.join(sorted(unknown))}")
        content = {key: value for key, value in content.items() if key in wanted}

    tables = await repository.list_tables(session, document.id, limit=200, offset=0, page_number=page_number)
    return PageDetail(
        page_number=page.page_number,
        geometry=PageGeometryOut(
            width=page.width,
            height=page.height,
            rotation=page.rotation,
            mediabox=tuple(page.mediabox),
        ),
        has_text_layer=bool(page.has_text_layer),
        text=page.text,
        content=content,
        table_ids=[row.table_id for row in tables.items],
    )


@router.get("/{document_id}/pages/{page_number}/render")
async def render_page(
    store: StoreDep,
    pipeline: PipelineDep,
    settings: SettingsDep,
    document: DocumentDep,
    page_number: int,
    scale: Annotated[float, Query(description="1.0 renders at 72 dpi.")] = 2.0,
) -> Response:
    """Render a page to PNG.

    The image is produced by the same PyMuPDF page object that produced every
    stored coordinate, in the same display space, so the frontend places an
    overlay box by multiplying by `scale` - no calibration, and rotation is
    already baked in.
    """
    if not settings.render_min_scale <= scale <= settings.render_max_scale:
        raise HTTPException(
            status_code=400,
            detail=f"scale must be between {settings.render_min_scale} and {settings.render_max_scale}",
        )
    if not 1 <= page_number <= max(document.page_count, 1):
        raise HTTPException(status_code=404, detail=f"Document {document.id!r} has no page {page_number}")

    data = await _load_pdf(store, document)
    try:
        png = await pipeline.render_page(data, page_number - 1, scale=scale)
    except ExtractionFailure as err:
        raise HTTPException(status_code=422, detail=err.message) from err

    return Response(
        content=png,
        media_type="image/png",
        headers={
            # Keyed by document, page, and scale, all of which are immutable.
            "Cache-Control": "private, max-age=86400, immutable",
            "Content-Length": str(len(png)),
        },
    )


# --- tables -----------------------------------------------------------------


@router.get("/{document_id}/tables", response_model=Paginated[TableSummary])
async def list_tables(
    session: SessionDep,
    document: DocumentDep,
    pagination: PaginationDep,
    page_number: Annotated[int | None, Query(ge=1)] = None,
) -> Paginated[TableSummary]:
    result = await repository.list_tables(
        session,
        document.id,
        limit=pagination.limit,
        offset=pagination.offset,
        page_number=page_number,
    )
    return Paginated[TableSummary](
        items=[_table_summary(row) for row in result.items],
        total=result.total,
        limit=result.limit,
        offset=result.offset,
    )


def _table_summary(row, *, cell_count: int | None = None) -> TableSummary:
    return TableSummary(
        id=row.table_id,
        page_number=row.page_number,
        source=row.source,
        bbox=tuple(row.bbox),
        row_count=row.row_count,
        column_count=row.column_count,
        caption=row.caption,
        confidence=row.confidence,
        continues_table_id=row.continues_table_id,
        cell_count=cell_count if cell_count is not None else row.row_count * row.column_count,
    )


@router.get("/{document_id}/tables/{table_id}", response_model=TableDetail)
async def get_table(session: SessionDep, table: TableDep) -> TableDetail:
    """One table with every cell - what the table viewer opens.

    Cells are not paginated here: a viewer needs the whole grid to lay out
    spans and to search across it, and even this document's largest table is
    539 cells. `/cells` exists for callers that do want to page.
    """
    cells = await repository.get_cells(session, table.id)
    summary = _table_summary(table, cell_count=len(cells))
    return TableDetail(**summary.model_dump(), cells=[_cell_out(cell) for cell in cells])


def _cell_out(cell) -> TableCellOut:
    return TableCellOut(
        row=cell.row,
        column=cell.column,
        row_span=cell.row_span,
        column_span=cell.column_span,
        kind=cell.kind,
        text=cell.text,
        azure_text=cell.azure_text,
        pymupdf_text=cell.pymupdf_text,
        bbox=tuple(cell.bbox),
        confidence=cell.confidence,
        text_source=cell.text_source,
    )


@router.get("/{document_id}/tables/{table_id}/cells", response_model=Paginated[TableCellOut])
async def list_cells(
    session: SessionDep, table: TableDep, pagination: PaginationDep
) -> Paginated[TableCellOut]:
    result = await repository.list_cells(session, table.id, limit=pagination.limit, offset=pagination.offset)
    return Paginated[TableCellOut](
        items=[_cell_out(cell) for cell in result.items],
        total=result.total,
        limit=result.limit,
        offset=result.offset,
    )
