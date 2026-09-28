"""Atomic local persistence outside inspected repositories."""
import json
import os
import threading
from pathlib import Path

from .analyzer import now

DATA = Path(os.environ.get("CODE_CHECKER_DATA", Path(__file__).resolve().parents[1] / ".codechecker"))
LOCK = threading.RLock()


def save(project):
    with LOCK:
        DATA.mkdir(parents=True, exist_ok=True)
        target = DATA / (project["id"] + ".json")
        temp = target.with_suffix(".tmp")
        temp.write_text(json.dumps(project, ensure_ascii=False), encoding="utf-8")
        temp.replace(target)


def get(project_id):
    if len(project_id) != 16 or any(c not in "0123456789abcdef" for c in project_id):
        raise KeyError("Proyecto no encontrado")
    with LOCK:
        path = DATA / (project_id + ".json")
        if not path.exists():
            raise KeyError("Proyecto no encontrado")
        return json.loads(path.read_text(encoding="utf-8"))


def listing():
    projects = []
    with LOCK:
        for path in DATA.glob("*.json"):
            if len(path.stem) != 16:
                continue
            p = json.loads(path.read_text(encoding="utf-8"))
            projects.append({k: p[k] for k in ("id", "name", "root", "created_at")})
    return sorted(projects, key=lambda p: p["created_at"], reverse=True)


def merge_scan(project):
    with LOCK:
        try:
            previous = get(project["id"])
        except KeyError:
            save(project)
            return project
        changed = previous["fingerprint"] != project["fingerprint"]
        old = {n["id"]: n for n in previous["nodes"]}
        for node in project["nodes"]:
            before = old.get(node["id"], {})
            if before.get("assessment"):
                node["assessment"] = before["assessment"]
                node["assessment"]["stale"] = changed or node["assessment"].get("stale", False)
            if not changed:
                node["coverage"] = before.get("coverage")
        project["runs"] = previous.get("runs", [])
        project["coverage_reports"] = previous.get("coverage_reports", []) if not changed else []
        project["history"] = (previous.get("history", []) + [{"at": now(), "previous_fingerprint": previous["fingerprint"], "changed": changed}])[-30:]
        save(project)
        return project
