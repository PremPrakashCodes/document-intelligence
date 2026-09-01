"""Apply BullMQ's Postgres schema: `uv run python -m jobs.migrate`.

Queues and workers migrate lazily on first use, so this is only needed where
that is undesirable — a deploy step that runs before the app boots, or a
database whose app role may not create schemas at runtime.
"""

import asyncio
import logging

import psycopg
from bullmq.backends.postgres_connection import run_migrations

from api.config import get_settings

log = logging.getLogger("jobs.migrate")


async def migrate() -> int:
    settings = get_settings()
    # run_migrations needs one non-autocommit session: the advisory lock and
    # the DDL have to share a transaction.
    conn = await psycopg.AsyncConnection.connect(settings.database_url, autocommit=False)
    try:
        return await run_migrations(conn, settings.queue_schema)
    finally:
        await conn.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
    version = asyncio.run(migrate())
    log.info("schema %r at migration version %s", get_settings().queue_schema, version)


if __name__ == "__main__":
    main()
