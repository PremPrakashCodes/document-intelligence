"""Enqueue jobs and inspect queue depth."""

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from jobs.queues import QUEUE_NAMES, get_queue

router = APIRouter(prefix="/queues", tags=["queues"])


class EnqueueRequest(BaseModel):
    name: str
    data: dict[str, Any] = {}
    opts: dict[str, Any] = {}


class EnqueueResponse(BaseModel):
    id: str
    queue: str
    name: str


def _queue(queue_name: str):
    try:
        return get_queue(queue_name)
    except KeyError as err:
        # str() on a KeyError re-quotes the message; args[0] is the raw text.
        raise HTTPException(status_code=404, detail=err.args[0]) from err


@router.get("")
def list_queues() -> dict[str, list[str]]:
    return {"queues": list(QUEUE_NAMES)}


@router.get("/{queue_name}")
async def queue_counts(queue_name: str) -> dict[str, int]:
    """Job counts per state — also a readiness check for the Postgres backend."""
    return await _queue(queue_name).getJobCounts()


@router.post("/{queue_name}/jobs", status_code=201)
async def enqueue(queue_name: str, body: EnqueueRequest) -> EnqueueResponse:
    job = await _queue(queue_name).add(body.name, body.data, body.opts)
    return EnqueueResponse(id=job.id, queue=queue_name, name=job.name)
