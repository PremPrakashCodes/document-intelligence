"""Worker entrypoint: `uv run python -m jobs.worker [queue ...]`.

Runs one BullMQ worker per queue in a single event loop, and drains in-flight
jobs on SIGINT/SIGTERM so a deploy does not strand them as stalled.
"""

import asyncio
import logging
import signal
import sys

from bullmq import Job, UnrecoverableError, Worker

from api.config import get_settings
from jobs.processors import PROCESSORS
from jobs.queues import QUEUE_NAMES, queue_options

log = logging.getLogger("jobs.worker")


def _make_processor(queue_name: str):
    handlers = PROCESSORS.get(queue_name, {})

    async def process(job: Job, token: str):
        handler = handlers.get(job.name)
        if handler is None:
            # Retrying will not conjure a handler, so fail the job for good.
            raise UnrecoverableError(f"No handler for job {job.name!r} on queue {queue_name!r}")
        return await handler(job)

    return process


def _attach_logging(worker: Worker, queue_name: str) -> None:
    worker.on("completed", lambda job, result: log.info("%s: %s completed", queue_name, job.id))
    worker.on("failed", lambda job, error: log.error("%s: %s failed: %s", queue_name, getattr(job, "id", "?"), error))
    worker.on("error", lambda error: log.error("%s: worker error: %s", queue_name, error))


async def run(queue_names: tuple[str, ...]) -> None:
    settings = get_settings()
    opts = queue_options(concurrency=settings.queue_concurrency)

    workers = []
    for name in queue_names:
        worker = Worker(name, _make_processor(name), opts)
        _attach_logging(worker, name)
        workers.append(worker)
        log.info("worker listening on %r (concurrency %d)", name, settings.queue_concurrency)

    stopping = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stopping.set)

    await stopping.wait()

    log.info("shutting down; waiting for in-flight jobs")
    # close() waits for active jobs to finalize before releasing the connection.
    await asyncio.gather(*(worker.close() for worker in workers))

    # Release the Azure HTTP session and the database pool the handlers used.
    from api.deps import get_pipeline
    from db.session import dispose_engine

    await get_pipeline().aclose()
    await dispose_engine()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
    )

    requested = tuple(sys.argv[1:]) or QUEUE_NAMES
    unknown = [name for name in requested if name not in QUEUE_NAMES]
    if unknown:
        sys.exit(f"Unknown queue(s): {', '.join(unknown)}. Known: {', '.join(QUEUE_NAMES)}")

    asyncio.run(run(requested))


if __name__ == "__main__":
    main()
