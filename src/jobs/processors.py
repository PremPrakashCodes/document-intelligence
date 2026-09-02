"""Job handlers, keyed by job name.

A handler receives the `Job` and returns a JSON-serializable result, which
BullMQ stores as `jsonb` on the completed row. Raising retries the job per its
`attempts`/`backoff` options; raising `UnrecoverableError` fails it outright.
"""

import logging

from bullmq import Job, UnrecoverableError

from api.config import get_settings
from api.deps import get_pipeline, get_store
from db import repository
from db.session import session_scope
from extraction.errors import ExtractionFailure
from jobs.queues import DOCUMENTS, FILINGS
from storage.base import ObjectNotFound, StorageError

log = logging.getLogger(__name__)


async def parse_filing(job: Job) -> dict:
    """Fetch a filing and hand it to the parser.

    Placeholder: the real pipeline (fetch the PDF, Azure Document Intelligence,
    persist the extracted tables) hangs off here.
    """
    source = job.data.get("source_url")
    log.info("parsing filing %s from %s", job.id, source)
    await job.updateProgress(100)
    return {"source_url": source, "pages": 0}


async def extract_document(job: Job) -> dict:
    """Run the extraction pipeline over a stored PDF and persist the result.

    Retry semantics follow which half failed. PyMuPDF failures are the file's
    fault and never retry - the same bytes will fail identically - so the
    document is marked `failed` and the job is closed with `UnrecoverableError`.
    Azure failures never reach here at all: the pipeline records them and
    returns a `partial` document, so a transient Azure outage costs the tables
    but keeps every deterministic value, and `POST /documents/{id}/extract`
    can fill them in later.
    """
    document_id = job.data.get("document_id")
    if not document_id:
        raise UnrecoverableError("extract-document requires a document_id")

    settings = get_settings()
    store = get_store()
    pipeline = get_pipeline()

    async with session_scope() as session:
        document = await repository.get_document(session, document_id)
        if document is None:
            raise UnrecoverableError(f"No document {document_id!r}")
        await repository.mark_processing(session, document_id)
        storage_key, filename = document.storage_key, document.filename

    await job.updateProgress(10)

    try:
        data = await store.get(storage_key)
    except ObjectNotFound as err:
        async with session_scope() as session:
            await repository.mark_failed(
                session, document_id, code="object_not_found", message=str(err)
            )
        raise UnrecoverableError(f"The stored PDF for {document_id!r} is missing") from err
    except StorageError as err:
        # Storage may simply be unreachable; let BullMQ retry this one.
        log.warning("could not read %s: %s", storage_key, err.message)
        raise

    await job.updateProgress(25)

    try:
        canonical = await pipeline.run(data, document_id=document_id, filename=filename)
    except ExtractionFailure as err:
        log.warning("extraction failed for %s (%s): %s", document_id, err.code, err.message)
        async with session_scope() as session:
            await repository.mark_failed(session, document_id, code=err.code, message=err.message)
        if err.retryable:
            raise
        raise UnrecoverableError(f"{err.code}: {err.message}") from err

    await job.updateProgress(80)

    async with session_scope() as session:
        await repository.save_extraction(session, canonical)

    await job.updateProgress(100)

    matching = canonical.extraction.matching
    log.info(
        "extracted %s: %d pages, %d tables, %d/%d cells matched (%.1f%%), azure=%s",
        document_id,
        len(canonical.pages),
        len(canonical.tables),
        matching.matched_cells,
        matching.content_cells,
        matching.match_rate * 100,
        canonical.extraction.azure_di.completed,
        )
    return {
        "document_id": document_id,
        "status": canonical.document.status.value,
        "pages": len(canonical.pages),
        "tables": len(canonical.tables),
        "cells": matching.total_cells,
        "match_rate": round(matching.match_rate, 4),
        "azure_completed": canonical.extraction.azure_di.completed,
        "model": settings.azure_di_model,
    }


# job name -> handler, per queue.
PROCESSORS: dict[str, dict[str, callable]] = {
    FILINGS: {
        "parse-filing": parse_filing,
    },
    DOCUMENTS: {
        "extract-document": extract_document,
    },
}
