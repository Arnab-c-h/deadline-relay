"""Loopback-only FastAPI application. Run one uvicorn worker."""
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from relay.providers.base import ProviderError
from relay.service import RUNNING, RelayService, WorkflowError
from relay.simulation import SimulationProvider
from relay.store import Store

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_ORIGINS = {"http://127.0.0.1:5173", "http://localhost:5173", "http://127.0.0.1:8000", "http://localhost:8000"}


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class PlanRequest(Payload):
    snapshot_id: str = Field(min_length=1, max_length=100)
    request: str = Field(min_length=1, max_length=2000)
    alternative_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    parent_plan_id: str | None = None


class ApprovalRequest(Payload):
    version: int = Field(ge=1)
    hash: str = Field(min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=1, max_length=200)


class ResumeRequest(Payload):
    idempotency_key: str = Field(min_length=1, max_length=200)


class ResetRequest(Payload):
    confirm: Literal[True]


class MissingLiveProvider:
    def health(self):
        return [{"provider": provider, "status": "missing", "detail": "Dedicated runtime credentials and resource IDs required"}
                for provider in ("notion", "github", "calendar")]

    def snapshot(self, *args, **kwargs):
        raise ProviderError("Live configuration is missing or invalid; see docs/SETUP.md", kind="auth")

    read = snapshot
    write = snapshot


def create_app(data_dir=None, *, mode=None):
    load_dotenv(ROOT / ".env", override=False)
    selected_mode = mode or os.getenv("RELAY_MODE", "simulated")
    if selected_mode not in {"simulated", "live"}:
        raise RuntimeError("RELAY_MODE must be simulated or live")
    store = Store(Path(data_dir or ROOT / "data") / f"relay-{selected_mode}.sqlite")
    if selected_mode == "simulated":
        provider = SimulationProvider(store)
    else:
        from relay.providers.live import LiveProvider
        config = Path(os.getenv("DEMO_CONFIG_PATH", ROOT / "config.local.json"))
        try:
            provider = LiveProvider(config)
        except (ProviderError, ValueError, OSError):
            provider = MissingLiveProvider()
    service = RelayService(store, provider, mode=selected_mode)

    @asynccontextmanager
    async def lifespan(app):
        for run in store.runs():
            if run["status"] in RUNNING:
                for op in run["operations"]:
                    if op["status"] in {"IN_FLIGHT", "APPLIED_UNVERIFIED"}:
                        op["status"] = "UNCERTAIN"
                service._save(run, "UNCERTAIN", "Backend restarted. Resume to inspect provider state before continuing.")
        yield

    app = FastAPI(title="Deadline Relay", version="0.1.0", lifespan=lifespan)
    app.state.service = service
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
    app.add_middleware(CORSMiddleware, allow_origins=sorted(ALLOWED_ORIGINS),
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type"])

    @app.middleware("http")
    async def reject_external_origins(request: Request, call_next):
        origin = request.headers.get("origin")
        if request.method not in {"GET", "HEAD", "OPTIONS"} and origin and origin not in ALLOWED_ORIGINS:
            return JSONResponse({"detail": "External browser origins cannot mutate this local application"}, status_code=403)
        return await call_next(request)

    @app.exception_handler(WorkflowError)
    async def workflow_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    @app.exception_handler(ProviderError)
    async def provider_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=503)

    @app.exception_handler(KeyError)
    async def not_found(request, exc):
        return JSONResponse({"detail": "Record, snapshot, plan or run not found"}, status_code=404)

    @app.get("/api/projects/demo/health")
    def health():
        return service.health()

    @app.post("/api/projects/demo/snapshots")
    def snapshot():
        return service.snapshot()

    @app.post("/api/projects/demo/plans")
    def plan(body: PlanRequest):
        return service.plan(body.snapshot_id, body.request, body.alternative_date, body.parent_plan_id)

    @app.get("/api/snapshots/{snapshot_id}")
    def get_snapshot(snapshot_id: str):
        return store.get("snapshots", snapshot_id)

    @app.get("/api/plans/{plan_id}")
    def get_plan(plan_id: str):
        return store.get("plans", plan_id)

    @app.post("/api/plans/{plan_id}/approve", status_code=202)
    def approve(plan_id: str, body: ApprovalRequest, tasks: BackgroundTasks):
        result = service.approve(plan_id, body.version, body.hash, body.idempotency_key)
        tasks.add_task(service.execute, result["run_id"])
        return result

    @app.get("/api/runs/{run_id}")
    def run(run_id: str):
        return service.run(run_id)

    @app.post("/api/runs/{run_id}/resume", status_code=202)
    def resume(run_id: str, body: ResumeRequest, tasks: BackgroundTasks):
        result = service.resume(run_id, body.idempotency_key)
        tasks.add_task(service.execute, run_id)
        return result

    @app.post("/api/runs/{run_id}/recovery-plan")
    def recovery_plan(run_id: str):
        return service.recovery_plan(run_id)

    @app.post("/api/demo/reset")
    def reset(body: ResetRequest):
        return service.reset()

    frontend = ROOT / "frontend" / "dist"
    if frontend.exists():
        app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
    return app


app = create_app()
