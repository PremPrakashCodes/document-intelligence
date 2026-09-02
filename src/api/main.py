from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.config import get_settings
from api.deps import get_pipeline
from api.routers import documents, health, queues
from db.session import dispose_engine
from jobs.queues import close_queues

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    # Queues open lazily and hold a Postgres connection each.
    await close_queues()
    # The Azure client holds an aiohttp session; the engine holds a pool.
    await get_pipeline().aclose()
    await dispose_engine()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    debug=settings.debug,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(queues.router)
app.include_router(documents.router)
