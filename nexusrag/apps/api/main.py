from __future__ import annotations

from fastapi import FastAPI

from nexusrag.apps.api.routes.audio import router as audio_router
from nexusrag.apps.api.routes.corpora import router as corpora_router
from nexusrag.apps.api.routes.documents import router as documents_router
from nexusrag.apps.api.routes.health import router as health_router
from nexusrag.apps.api.routes.run import router as run_router
from nexusrag.core.logging import configure_logging


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="NexusRAG API")
    app.include_router(audio_router)
    app.include_router(documents_router)
    app.include_router(health_router)
    app.include_router(corpora_router)
    app.include_router(run_router)
    return app


app = create_app()
