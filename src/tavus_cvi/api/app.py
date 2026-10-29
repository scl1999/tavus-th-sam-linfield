"""Local candidate API plus a signature-verified internal Tavus handler."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from tavus_cvi.adapters.config import Settings, load_settings
from tavus_cvi.adapters.runtime_repository import RuntimeRepository
from tavus_cvi.adapters.tavus_client import TavusClient
from tavus_cvi.api.logging_middleware import RequestLogMiddleware
from tavus_cvi.api.routes_interviews import callback_reachable
from tavus_cvi.api.routes_interviews import router as interviews_router
from tavus_cvi.api.routes_recordings import router as recordings_router
from tavus_cvi.api.routes_telemetry import router as telemetry_router
from tavus_cvi.api.routes_tools import router as tools_router
from tavus_cvi.api.routes_workspace import router as workspace_router
from tavus_cvi.api.security import CandidateSecurityMiddleware
from tavus_cvi.services.candidate_profile import ensure_seeded_candidate
from tavus_cvi.services.code_execution_service import CodeExecutionService
from tavus_cvi.services.context_compression_service import ContextCompressionService
from tavus_cvi.services.interview_service import InterviewService
from tavus_cvi.services.model_card_service import ModelCardService
from tavus_cvi.services.recording_service import RecordingService
from tavus_cvi.services.telemetry_service import TelemetryService

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        repository = RuntimeRepository(resolved.database_url)
        repository.allow_unknown_thinking_tokens()
        repository.ensure_revisit_column()
        repository.ensure_candidate_work_columns()
        repository.apply_schema(
            (
                resolved.agent_config_dir.parent.parent / "src/tavus_cvi/adapters/db/repair.sql"
            ).read_text()
        )
        tavus = (
            TavusClient(resolved.tavus_api_key, resolved.tavus_base_url)
            if resolved.tavus_api_key
            else None
        )
        # Missing callback configuration cannot provision insecure app-message tools.
        provisioner = tavus if resolved.callback_base_url and resolved.callback_secret else None
        ModelCardService(
            repository, provisioner, resolved.callback_base_url, resolved.callback_secret
        ).sync_directory(resolved.agent_config_dir)
        ensure_seeded_candidate(repository)
        app.state.repository = repository
        app.state.tavus = tavus
        app.state.interviews = InterviewService(
            repository, tavus, resolved.recordings_dir, call_limit=resolved.call_limit_seconds
        )
        app.state.compression = ContextCompressionService()
        app.state.telemetry = TelemetryService(repository, app.state.compression)
        app.state.execution = CodeExecutionService(resolved.recordings_dir)
        app.state.recordings = RecordingService(repository, resolved.recordings_dir)

        async def reconcile() -> None:
            passes = 0
            while True:
                try:
                    if passes % 10 == 0:
                        await asyncio.to_thread(app.state.execution.cleanup_stale)
                    passes += 1
                    await asyncio.to_thread(app.state.interviews.tick)
                    with repository._connect() as connection:
                        connection.execute(
                            "UPDATE recording_segments SET status='incomplete' "
                            "WHERE status='open' AND updated_at < now()-interval '2 minutes'"
                        )
                except Exception:
                    logger.exception("Background reconciliation failed")
                await asyncio.sleep(3)

        worker = asyncio.create_task(reconcile())
        try:
            yield
        finally:
            worker.cancel()
            try:
                await worker
            except asyncio.CancelledError:
                pass
            if tavus:
                tavus.close()

    app = FastAPI(title="Tavus interviewer", lifespan=lifespan)
    app.state.settings = resolved
    app.add_middleware(RequestLogMiddleware)
    app.add_middleware(CandidateSecurityMiddleware)
    for router in (interviews_router, workspace_router, telemetry_router, recordings_router):
        app.include_router(router, prefix="/api")
    app.include_router(tools_router)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/readiness")
    def readiness() -> dict[str, bool]:
        card = app.state.repository.latest_interviewer_card()
        return {
            "callbacks_configured": bool(resolved.callback_base_url and resolved.callback_secret),
            "callback_reachable": bool(
                resolved.callback_base_url and callback_reachable(resolved.callback_base_url)
            ),
            "interviewer_provisioned": bool(card and card.version >= 7 and card.tavus_pal_id),
        }

    return app


app = create_app()
