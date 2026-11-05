"""Single-workspace API. Run one worker: one machine owns one pipeline."""

from __future__ import annotations

import argparse
import asyncio
import copy
from contextlib import asynccontextmanager
from dataclasses import asdict
import hashlib
import math
from pathlib import Path
import threading
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

from seimlai.context import case_study_root
from seimlai.gui.services.catalog_watcher import CatalogWatcher
from seimlai.gui.services.config_service import ConfigService, _write_yaml_atomic
from seimlai.gui.services.pipeline_service import PipelineService
from seimlai.main import OPTIONAL_STEPS


def json_safe(value: Any) -> Any:
    """Catalogs can contain NaN; JSON and browser clients cannot."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return value


class ConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str
    data: dict[str, Any]


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str
    mode: Literal["all", "continue", "single", "from", "utility"] = "all"
    step: Literal["01", "02", "03", "04", "05"] = "01"
    command: str | None = None


class CaseRequest(BaseModel):
    path: str
    version: str


class FileUpdate(BaseModel):
    content: str
    version: str


def create_app(config_path: str = "user_configuration/config.yaml", frontend_dir: Path | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.config = ConfigService(config_path)
        app.state.config_version = version()
        app.state.pipeline = PipelineService()
        app.state.watcher = CatalogWatcher(config_path)
        app.state.mutation_lock = asyncio.Lock()
        app.state.revision = 0
        app.state.revision_lock = threading.Lock()

        def changed(_event, _items):
            with app.state.revision_lock:
                app.state.revision += 1

        app.state.watcher.add_listener(changed)
        app.state.watcher.start_watching()
        try:
            yield
        finally:
            app.state.watcher.stop_watching()
            app.state.pipeline.request_stop()
            thread = app.state.watcher._watch_thread
            if thread:
                await asyncio.to_thread(thread.join, 5)

    app = FastAPI(title="SeiMLAI", version="0.1.0", lifespan=lifespan)

    @app.middleware("http")
    async def same_origin_mutations(request, call_next):
        origin = request.headers.get("origin")
        if request.method not in ("GET", "HEAD", "OPTIONS") and origin and urlsplit(origin).netloc != request.headers.get("host"):
            return JSONResponse({"detail": "Cross-origin writes are not allowed."}, status_code=403)
        return await call_next(request)

    def version() -> str:
        return hashlib.sha256(app.state.config.config_path.read_bytes()).hexdigest()

    def require_idle():
        if app.state.pipeline.is_running:
            raise HTTPException(409, "Stop the pipeline before changing workspace files or settings.")

    def require_version(expected: str):
        if expected != version():
            raise HTTPException(409, "Configuration changed. Reload before saving or switching case studies.")

    def config_response():
        return {"data": copy.deepcopy(app.state.config.data), "version": app.state.config_version}

    def snapshot():
        pipeline = app.state.pipeline
        with app.state.revision_lock:
            revision = app.state.revision
        return json_safe({
            "running": pipeline.is_running,
            "current_step": pipeline.current_step_id,
            "steps": [asdict(s) for s in pipeline.step_states.values()],
            "logs": list(pipeline.logs),
            "catalog_revision": revision,
            "config_version": version(),
        })

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "workspace": "shared", "pipeline_slots": 1}

    @app.get("/api/config")
    async def get_config():
        # Refresh external edits only when idle; never replace a running job's settings.
        if not app.state.pipeline.is_running:
            app.state.config_version = version()
            app.state.config.load()
        return config_response()

    @app.put("/api/config")
    async def save_config(update: ConfigUpdate):
        async with app.state.mutation_lock:
            require_idle()
            require_version(update.version)
            svc = app.state.config
            svc.load()
            original = copy.deepcopy(svc.data)
            try:
                # Preserve the existing configuration schema and comment-preserving save.
                def apply(current, proposed, prefix=""):
                    if not isinstance(proposed, dict) or current.keys() != proposed.keys():
                        raise ValueError("Configuration sections and keys must match the saved schema.")
                    for key, value in proposed.items():
                        name = f"{prefix}.{key}" if prefix else key
                        if isinstance(current[key], dict):
                            apply(current[key], value, name)
                        else:
                            nullable = {"case_study.personal_folder", "model.custom_model_path", "cc_dd.worker_count", "cc_dd.chunk_size"}
                            if value is None and name not in nullable:
                                raise ValueError(f"{name} cannot be null.")
                            if isinstance(value, (dict, list)) != isinstance(current[key], (dict, list)):
                                raise ValueError(f"{name} has an invalid value type.")
                            if isinstance(current[key], bool) and not isinstance(value, bool):
                                raise ValueError(f"{name} must be true or false.")
                            if isinstance(current[key], (int, float)) and not isinstance(current[key], bool) and value is not None:
                                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                                    raise ValueError(f"{name} must be a finite number.")
                            svc.set(name, value)

                apply(original, update.data)
                geo = svc.data["geography"]
                if not (-90 <= geo["minlatitude"] < geo["maxlatitude"] <= 90 and -180 <= geo["minlongitude"] < geo["maxlongitude"] <= 180):
                    raise ValueError("Geographic bounds must be ordered and within latitude/longitude limits.")
                svc.save()
            except (ValueError, TypeError, KeyError) as exc:
                svc.reset_to_saved()
                raise HTTPException(422, str(exc)) from exc
            app.state.config_version = version()
            await asyncio.to_thread(app.state.watcher.refresh)
            return config_response()

    @app.get("/api/state")
    async def get_state():
        return snapshot()

    @app.websocket("/api/live")
    async def live(websocket: WebSocket):
        # Browser access is same-origin, including through Vite's development proxy.
        origin = websocket.headers.get("origin")
        if origin and urlsplit(origin).netloc != websocket.headers.get("host"):
            await websocket.close(code=1008)
            return
        await websocket.accept()
        try:
            while True:
                await websocket.send_json(snapshot())
                await asyncio.sleep(1)
        except WebSocketDisconnect:
            return

    @app.post("/api/pipeline/run")
    async def run(request: RunRequest):
        async with app.state.mutation_lock:
            require_idle()
            require_version(request.version)
            svc = app.state.config
            svc.load()
            app.state.config_version = version()
            errors = svc.validate()
            if errors:
                raise HTTPException(422, "\n".join(errors))
            pipeline = app.state.pipeline
            if request.mode == "utility":
                if request.command not in OPTIONAL_STEPS:
                    raise HTTPException(422, "Unknown utility.")
                started = pipeline.run_optional_command_async(str(svc.config_path), request.command)
            else:
                started = pipeline.run_workflow_async(
                    str(svc.config_path),
                    from_step="04" if request.mode == "continue" else request.step if request.mode == "from" else None,
                    only_steps=[request.step] if request.mode == "single" else None,
                    phase_label=request.mode,
                )
            if not started:
                raise HTTPException(409, "A pipeline is already running.")
            return {"started": True}

    @app.post("/api/pipeline/stop")
    async def stop():
        app.state.pipeline.request_stop()
        return {"stop_requested": True}

    @app.get("/api/catalogs/{source}")
    async def catalog(source: Literal["gamma", "hypoellipse", "hypodd"]):
        watcher = app.state.watcher
        with watcher._lock:
            events = [asdict(item) for item in watcher.catalogs[source]]
            stations = [asdict(item) for item in watcher.stations]
        return json_safe({"events": events, "stations": stations})

    @app.post("/api/catalogs/refresh")
    async def refresh():
        async with app.state.mutation_lock:
            await asyncio.to_thread(app.state.watcher.refresh)
        return {"refreshed": True}

    def case_paths():
        directory = Path.cwd() / "case_studies"
        paths = {p.resolve() for p in directory.iterdir() if p.is_dir()} if directory.exists() else set()
        paths.add(case_study_root(app.state.config.data["case_study"]).resolve())
        return paths

    @app.get("/api/cases")
    async def cases():
        active = case_study_root(app.state.config.data["case_study"]).resolve()
        return [{"name": p.name, "path": str(p), "active": p == active, "exists": p.is_dir()}
                for p in sorted(case_paths(), key=lambda p: str(p).casefold())]

    @app.post("/api/cases/select")
    async def select_case(request: CaseRequest):
        async with app.state.mutation_lock:
            require_idle()
            require_version(request.version)
            path = Path(request.path).resolve()
            if path not in case_paths() or not path.is_dir():
                raise HTTPException(404, "Case study not found.")
            try:
                app.state.config.load()
                app.state.config.select_case(path)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            await asyncio.to_thread(app.state.watcher.refresh)
            app.state.config_version = version()
            return config_response()

    def file_path(group: str, name: str) -> Path:
        if group not in ("hypoellipse", "hypodd") or name != Path(name).name or name.startswith("."):
            raise HTTPException(404, "Unknown configuration file.")
        root = (app.state.config.config_path.parent / group).resolve()
        path = (root / name).resolve()
        if path.parent != root:
            raise HTTPException(404, "Unknown configuration file.")
        return path

    @app.get("/api/files/{group}")
    async def files(group: Literal["hypoellipse", "hypodd"]):
        defaults = ["grad.mod", "improved.cfg"] if group == "hypoellipse" else ["hypoDD.inc", "ph2dt.inc", "Dockerfile"]
        root = app.state.config.config_path.parent / group
        names = {p.name for p in root.iterdir() if p.is_file() and not p.name.startswith(".") and not p.name.endswith(".bak")} if root.exists() else set()
        return defaults + sorted(names - set(defaults))

    def file_response(path: Path):
        raw = path.read_bytes() if path.exists() else b""
        return {"content": raw.decode("utf-8"), "version": hashlib.sha256(raw).hexdigest()}

    @app.get("/api/files/{group}/{name}")
    async def read_file(group: str, name: str):
        return file_response(file_path(group, name))

    @app.put("/api/files/{group}/{name}")
    async def save_file(group: str, name: str, update: FileUpdate):
        async with app.state.mutation_lock:
            require_idle()
            path = file_path(group, name)
            previous = file_response(path)
            if previous["version"] != update.version:
                raise HTTPException(409, "File changed. Reload before saving.")
            if path.exists():
                _write_yaml_atomic(path.with_name(path.name + ".bak"), previous["content"])
            _write_yaml_atomic(path, update.content)
            return file_response(path)

    dist = frontend_dir or Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")
        app.mount("/cesium", StaticFiles(directory=dist / "cesium"), name="cesium")

        @app.get("/{route:path}")
        async def frontend(route: str):
            if route == "api" or route.startswith("api/"):
                raise HTTPException(404, "Unknown API endpoint.")
            path = (dist / route).resolve()
            if path.is_relative_to(dist.resolve()) and path.is_file():
                return FileResponse(path)
            return FileResponse(dist / "index.html")

    return app


def main():
    import uvicorn

    parser = argparse.ArgumentParser(description="SeiMLAI independent web interface")
    parser.add_argument("--config", default="user_configuration/config.yaml")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run(create_app(args.config), host=args.host, port=args.port, workers=1)


if __name__ == "__main__":
    main()
