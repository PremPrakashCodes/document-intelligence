"""Job handlers, keyed by job name.

A handler receives the `Job` and returns a JSON-serializable result, which
BullMQ stores as `jsonb` on the completed row. Raising retries the job per its
`attempts`/`backoff` options; raising `UnrecoverableError` fails it outright.
"""

import logging

from bullmq import Job

from jobs.queues import FILINGS

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


# job name -> handler, per queue.
PROCESSORS: dict[str, dict[str, callable]] = {
    FILINGS: {
        "parse-filing": parse_filing,
    },
}
