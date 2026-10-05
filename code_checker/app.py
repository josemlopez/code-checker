from __future__ import annotations

import json
import os
import secrets
import threading
import uuid
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import store, remote, git_diff, deep_link
from .analyzer import VERSION, analyze, attach_coverage, digest, disk_stamp, now
from .evaluation import POLICY_VERSION, codex_command, evaluate, package_for, profile_key

BASE = Path(__file__).resolve().parents[1]
app = FastAPI(title="Code Checker", docs_url="/api/docs")
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "::1", "testserver"])
TOKEN = secrets.token_urlsafe(32)
JOBS = {}
JOB_LOCK = threading.RLock()
MODEL_LOCK = threading.Lock()
# CODE_CHECKER_MODELS=off disables every model call (evaluate, ask, lazy) on this server.
MODELS_ENABLED = os.environ.get('CODE_CHECKER_MODELS', 'on').strip().lower() not in {'off', '0', 'false', 'no'}


@app.middleware("http")
async def local_guard(request: Request, call_next):
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        if request.headers.get("x-code-checker-token") != TOKEN:
            return JSONResponse({"detail": "Recarga la aplicación para renovar la sesión local."}, status_code=403)
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            return JSONResponse({"detail": "Origen no permitido"}, status_code=403)
        if len(await request.body()) > 8_000_000:
            return JSONResponse({"detail": "El documento supera 8 MB"}, status_code=413)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(KeyError)
async def missing_handler(request, exc):
    return JSONResponse({"detail": "No se encontró el proyecto o componente."}, status_code=404)


@app.exception_handler(ValueError)
async def value_handler(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=422)


class ScanRequest(BaseModel):
    path: str = Field(min_length=1, max_length=2000)
    ssh_host: str = Field(default='', max_length=150)


class DiffRequest(BaseModel):
    base: str = Field(default='HEAD', min_length=1, max_length=250)
    head: str = Field(default='HEAD', min_length=1, max_length=250)
    mode: Literal['working','pr','direct'] = 'working'
    pr_number: int | None = Field(default=None, ge=1, le=2147483647)


def current_stamp(project):
    return remote.stamp(project) if remote.is_remote(project) else disk_stamp(project['root'])


def current_context(project, identifier):
    return remote.context(project, identifier) if remote.is_remote(project) else package_for(project, identifier)


class ModelRequest(BaseModel):
    component_id: str
    provider: Literal["codex", "ollama"] = "codex"
    model: str = Field(default="", max_length=150)
    endpoint: str = "http://127.0.0.1:11434"
    question: str = Field(default="", max_length=4000)
    force: bool = False


class CoverageRequest(BaseModel):
    report: dict
    fingerprint: str


class RunRequest(BaseModel):
    component_id: str
    task: str = Field(min_length=5, max_length=2000)
    profile: str = Field(min_length=1, max_length=150)
    accepted: bool
    acceptance: str = Field(min_length=5, max_length=4000)
    evidence: str = Field(min_length=5, max_length=8000)
    attempts: int = Field(default=1, ge=1, le=10000)
    regressions: int = Field(default=0, ge=0, le=10000)
    human_interventions: int = Field(default=0, ge=0, le=10000)
    tokens: int | None = Field(default=None, ge=0)
    seconds: float | None = Field(default=None, ge=0)


def launch_job(kind, worker):
    job_id = uuid.uuid4().hex
    with JOB_LOCK:
        if sum(j["status"] in {"queued", "running"} for j in JOBS.values()) >= 5:
            raise HTTPException(429, "Hay cinco trabajos pendientes. Espera a que finalicen.")
        JOBS[job_id] = {"id": job_id, "kind": kind, "status": "queued", "created_at": now(), "message": "En cola"}

    def run():
        try:
            JOBS[job_id].update(status="running", message="Analizando archivos…" if kind == "scan" else "Esperando al modelo…")
            result = worker()
            JOBS[job_id].update(status="completed", message="Completado", result=result)
        except Exception as exc:
            message = str(exc)[:700] if isinstance(exc, (ValueError, OSError, KeyError)) else f"No se pudo completar el trabajo ({type(exc).__name__})."
            JOBS[job_id].update(status="failed", message=message)
    threading.Thread(target=run, daemon=True, name="checker-" + job_id[:8]).start()
    return {"job_id": job_id}


@app.get("/api/config")
def config():
    return {"token": TOKEN, "version": "1.0.0", "policy_version": POLICY_VERSION,
            "codex_available": MODELS_ENABLED and codex_command() is not None, "models_enabled": MODELS_ENABLED, "example_path": str(BASE / "examples" / "dispatch"),
            "self_path": str(BASE / "code_checker"), "data_path": str(store.DATA)}


@app.get("/api/deep-link")
def deep_link_target(request: Request):
    try:
        target = deep_link.parse(request.query_params.multi_items())
    except deep_link.Forbidden as exc:
        raise HTTPException(403, str(exc)) from None
    # Reuse an existing local index of that folder; otherwise the UI scans it statically.
    try:
        known = store.get(target['project_id'])
        if remote.is_remote(known) or known.get('root') != target['path']:
            target['project_id'] = None
    except KeyError:
        target['project_id'] = None
    return target


@app.get("/api/projects")
def projects():
    return store.listing()


@app.post("/api/scan")
def scan(body: ScanRequest):
    if body.ssh_host:
        return launch_job('scan', lambda: {'project_id':store.merge_scan(remote.request(body.ssh_host, body.path, 'scan'))['id']})
    root = Path(body.path).expanduser()
    if not root.is_dir():
        raise ValueError("La carpeta no existe en este ordenador.")
    return launch_job("scan", lambda: {"project_id": store.merge_scan(analyze(body.path))["id"]})


@app.get("/api/jobs/{job_id}")
def job(job_id: str):
    with JOB_LOCK:
        if job_id not in JOBS:
            raise HTTPException(404, "Trabajo no encontrado; el servidor puede haberse reiniciado.")
        return dict(JOBS[job_id])


@app.get("/api/projects/{project_id}")
def project(project_id: str):
    result = store.get(project_id)
    result["needs_rescan"] = result.get('analyzer_version') != VERSION or current_stamp(result) != result.get("disk_stamp")
    if result["needs_rescan"]:
        for node in result["nodes"]:
            if node.get("assessment"):
                node["assessment"]["stale"] = True
    # Source is fetched only for the selected component.
    result["nodes"] = [{k: v for k, v in node.items() if k != "source"} for node in result["nodes"]]
    result["documents"] = [{"path": doc["path"], "truncated": doc["truncated"]} for doc in result["documents"]]
    return result


@app.get("/api/projects/{project_id}/freshness")
def freshness(project_id: str):
    result = store.get(project_id)
    return {"changed": result.get('analyzer_version') != VERSION or current_stamp(result) != result.get("disk_stamp")}


@app.get('/api/projects/{project_id}/git-options')
def git_options(project_id: str):
    p = store.get(project_id)
    return remote.request(p['origin']['host'],p['root'],'git_options') if remote.is_remote(p) else git_diff.options(p['root'])


@app.post('/api/projects/{project_id}/diff')
def compare_project(project_id: str, body: DiffRequest):
    p = store.get(project_id)
    def work():
        if body.pr_number is not None:
            if body.mode != 'pr': raise ValueError('Selecciona el modo PR para comparar un pull request.')
            result = remote.request(p['origin']['host'],p['root'],'pr_diff',p.get('scan_scope'),number=body.pr_number) if remote.is_remote(p) else git_diff.compare_pr(p['root'],body.pr_number)
        else:
            result = remote.request(p['origin']['host'],p['root'],'diff',p.get('scan_scope'),**body.model_dump(exclude={'pr_number'})) if remote.is_remote(p) else git_diff.compare(p['root'],body.base,body.head,body.mode)
        result.update(id=p['id'],origin=p.get('origin'),scan_scope=p.get('scan_scope'),needs_rescan=False)
        return {'project':result}
    return launch_job('diff',work)


@app.get('/api/projects/{project_id}/pull-requests')
def project_pull_requests(project_id: str, state: Literal['open','closed','all'] = 'open'):
    p = store.get(project_id)
    return remote.request(p['origin']['host'],p['root'],'pull_requests',state=state) if remote.is_remote(p) else git_diff.pull_requests(p['root'],state)


@app.get('/api/diffs/{job_id}/component')
def diff_component(job_id: str, id: str):
    with JOB_LOCK:
        job = JOBS.get(job_id)
        if not job or job['kind'] != 'diff' or job['status'] != 'completed':
            raise ValueError('La comparación ya no está disponible. Calcula el diff de nuevo.')
        p = job['result']['project']
    node = next((n for n in p['nodes'] if n['id']==id),None)
    if node is None: raise KeyError(id)
    c = p['comparison']
    revision = c['base_sha'] if node.get('diff_side')=='before' else 'working' if c['mode']=='working' else c['head_sha']
    if remote.is_remote(p):
        return remote.request(p['origin']['host'],p['root'],'diff_component',p.get('scan_scope'),revision=revision,node=node)
    return git_diff.component(p['root'],revision,node)


@app.get("/api/projects/{project_id}/component")
def component(project_id: str, id: str):
    project = store.get(project_id)
    for node in project["nodes"]:
        if node["id"] == id:
            return remote.component(project, node) if remote.is_remote(project) else node
    raise KeyError(id)


@app.get("/api/projects/{project_id}/context")
def context(project_id: str, id: str):
    return current_context(store.get(project_id), id)


@app.post("/api/projects/{project_id}/evaluate")
def assessment(project_id: str, body: ModelRequest):
    if not MODELS_ENABLED:
        raise HTTPException(403, "La evaluación con modelos está desactivada en este servidor (CODE_CHECKER_MODELS=off).")
    project = store.get(project_id)
    if project.get('analyzer_version') != VERSION or current_stamp(project) != project.get("disk_stamp"):
        raise ValueError("El proyecto ha cambiado en disco. Vuelve a analizar antes de evaluar.")
    package = current_context(project, body.component_id)
    node = next(n for n in project["nodes"] if n["id"] == body.component_id)
    cached = node.get("assessment")
    # An unspecified CLI default can change after an upgrade: do not assume same model.
    if body.model.strip() and not body.force and not body.question and cached and not cached.get("stale") and cached.get("context_hash") == digest(package) and cached.get("profile_key") == profile_key(body.provider, body.model, body.endpoint):
        return {"cached": True, "result": cached}

    def work():
        with MODEL_LOCK:
            result = evaluate(package, body.provider, body.model.strip(), body.endpoint, body.question)
        if not body.question:
            with store.LOCK:
                latest = store.get(project_id)
                if remote.is_remote(latest):
                    previous_coverage = {n['id']:n.get('coverage') for n in project['nodes']}
                    result['stale'] = latest['fingerprint'] != project['fingerprint'] or latest['runs'] != project['runs'] or current_stamp(latest) != latest.get('disk_stamp') or any(n.get('coverage') != previous_coverage.get(n['id']) for n in latest['nodes'])
                else:
                    result["stale"] = digest(package_for(latest, body.component_id)) != digest(package) or current_stamp(latest) != latest.get("disk_stamp")
                target = next(n for n in latest["nodes"] if n["id"] == body.component_id)
                target["assessment"] = result
                store.save(latest)
        return {"assessment": result, "component_id": body.component_id, "question": body.question}
    return launch_job("evaluate", work)


@app.post("/api/projects/{project_id}/coverage")
def coverage(project_id: str, body: CoverageRequest):
    with store.LOCK:
        project = store.get(project_id)
        result = attach_coverage(project, body.report, body.fingerprint)
        store.save(project)
        return result


@app.post("/api/projects/{project_id}/runs")
def runs(project_id: str, body: RunRequest):
    with store.LOCK:
        project = store.get(project_id)
        if body.component_id not in {n["id"] for n in project["nodes"]}:
            raise KeyError(body.component_id)
        record = body.model_dump() | {"at": now(), "id": uuid.uuid4().hex, "fingerprint": project["fingerprint"], "provenance": "user-recorded", "independently_verified": False}
        project["runs"].append(record)
        for node in project["nodes"]:
            if node.get("assessment") and (remote.is_remote(project) or node["assessment"].get("context_hash") != digest(package_for(project, node["id"]))):
                node["assessment"]["stale"] = True
        store.save(project)
        return record


@app.get("/api/projects/{project_id}/export")
def export(project_id: str):
    project = store.get(project_id)
    return Response(json.dumps(project, ensure_ascii=False, indent=2), media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="code-checker-report.json"'})


@app.get("/")
def index():
    return FileResponse(BASE / "web" / "index.html")


app.mount("/static", StaticFiles(directory=BASE / "web"), name="static")
