import time

from fastapi.testclient import TestClient

from code_checker.app import app
from code_checker import store
from code_checker.analyzer import digest
from code_checker.evaluation import package_for


def wait(client, identifier):
    for _ in range(100):
        data = client.get("/api/jobs/" + identifier).json()
        if data["status"] in {"completed", "failed"}:
            return data
        time.sleep(.02)
    raise AssertionError("job did not finish")


def test_api_scan_persist_export_and_guard(tmp_path, monkeypatch):
    def forbidden_model(*args, **kwargs):
        raise AssertionError('Static analysis must not invoke a model')
    monkeypatch.setattr('code_checker.app.evaluate', forbidden_model)
    monkeypatch.setattr(store, "DATA", tmp_path / "storage")
    root = tmp_path / "source"
    root.mkdir()
    (root / "a.py").write_text("def f(): return 1", encoding="utf-8")
    with TestClient(app) as client:
        assert client.post("/api/scan", json={"path":str(root)}).status_code == 403
        token = client.get("/api/config").json()["token"]
        headers = {"X-Code-Checker-Token":token}
        assert client.post("/api/scan", headers=headers | {"Origin":"https://evil.example"}, json={"path":str(root)}).status_code == 403
        job = client.post("/api/scan", headers=headers, json={"path":str(root)}).json()
        result = wait(client, job["job_id"])
        assert result["status"] == "completed", result
        pid = result["result"]["project_id"]
        data = client.get("/api/projects/" + pid).json()
        assert len(data["nodes"]) == 2
        assert "source" not in data["nodes"][0]
        assert data['nodes'][0]['metrics']['aggregate']['functions'] == 1
        assert data['nodes'][0]['metrics']['measurement']['uses_model'] is False
        assert client.get(f"/api/projects/{pid}/component", params={"id":"a.py::f"}).json()["source"] == "def f(): return 1"
        assert client.get(f"/api/projects/{pid}/component", params={"id":"missing"}).status_code == 404
        exported = client.get(f"/api/projects/{pid}/export")
        assert "attachment" in exported.headers["content-disposition"]
        assert exported.json()["fingerprint"] == data["fingerprint"]
        project = store.get(pid)
        for node in project["nodes"]:
            node["assessment"] = {"context_hash": digest(package_for(project, node["id"])), "stale": False}
        store.save(project)
        run = {"component_id":"a.py", "task":"Change a rule", "profile":"Test profile", "accepted":False, "acceptance":"Return a specific result", "evidence":"An illustrative failed outcome"}
        added = client.post(f"/api/projects/{pid}/runs", json=run, headers=headers)
        assert added.status_code == 200
        assert added.json()["independently_verified"] is False
        assert len(store.get(pid)["runs"]) == 1
        assert all(n["assessment"]["stale"] for n in store.get(pid)["nodes"])
