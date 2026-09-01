"""Queue definitions, shared by the API (which enqueues) and the worker.

BullMQ's Postgres backend keeps every queue in one schema instead of Redis
keys, so `opts["schema"]` replaces the Redis `prefix` — passing a prefix is
rejected outright. The schema is created and migrated lazily, the first time a
queue or worker touches the database; migrations are idempotent and guarded by
an advisory lock, so several processes may start at once.
"""

from bullmq import Queue

from api.config import get_settings

# One queue per kind of work. Names are part of the wire format: a worker and
# the producers must agree on them, so they live here rather than in settings.
FILINGS = "filings"

QUEUE_NAMES = (FILINGS,)

_queues: dict[str, Queue] = {}


def queue_options(**overrides) -> dict:
    """Connection options for any Queue, Worker, or QueueEvents in this app."""
    settings = get_settings()
    return {
        "backend": "postgres",
        "connection": settings.database_url,
        "schema": settings.queue_schema,
        **overrides,
    }


def get_queue(name: str) -> Queue:
    """The process-wide `Queue` for `name`, opened on first use.

    Each `Queue` owns a Postgres connection, so they are cached rather than
    built per request. Call `close_queues()` on shutdown.
    """
    if name not in QUEUE_NAMES:
        raise KeyError(f"Unknown queue {name!r}; expected one of {', '.join(QUEUE_NAMES)}")

    queue = _queues.get(name)
    if queue is None:
        queue = Queue(name, queue_options())
        _queues[name] = queue
    return queue


async def close_queues() -> None:
    """Close every queue opened by `get_queue` and release its connection."""
    while _queues:
        _, queue = _queues.popitem()
        await queue.close()
