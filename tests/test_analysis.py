import json
from pathlib import Path

import pytest

from code_checker.analyzer import analyze, attach_coverage, cycles_for, disk_stamp
from code_checker import store
from code_checker.evaluation import package_for


def write(root, path, text):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def test_relative_imports_typing_and_cycles(tmp_path):
    write(tmp_path, "src/shop/__init__.py", "from . import api\n")
    write(tmp_path, "src/shop/api.py", "from .service import go\nfrom typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from . import types\n")
    write(tmp_path, "src/shop/service.py", "from . import api\ndef go(x):\n    if x:\n        return 1\n    return 0\n")
    write(tmp_path, "src/shop/types.py", "class Input: pass\n")
    p = analyze(tmp_path)
    assert any(e["source"] == "src/shop/api.py" and e["target"] == "src/shop/service.py" for e in p["edges"])
    assert any(e["context"] == "typing" and e["target"] == "src/shop/types.py" for e in p["edges"])
    assert p["cycles"] == [["src/shop/api.py", "src/shop/service.py"]]
    fn = next(n for n in p["nodes"] if n["name"] == "go")
    assert fn["metrics"]["cc"] == 2
    assert fn["metrics"]["nesting"] == 1
    assert fn["assessment"] is None


def test_nested_scopes_effects_and_no_execution(tmp_path):
    write(tmp_path, "a.py", "raise RuntimeError('must never execute')\ndef outer():\n    def inner(x):\n        if x:\n            print(x)\n    return inner\n")
    p = analyze(tmp_path)
    outer = next(n for n in p["nodes"] if n["name"] == "outer")
    inner = next(n for n in p["nodes"] if n["name"] == "inner")
    assert outer["metrics"]["nesting"] == 0
    assert not outer["metrics"]["effect_candidates"]
    assert inner["parent"] == outer["id"]
    assert inner["metrics"]["effect_candidates"][0]["call"] == "print"


def test_scan_exclusions_errors_and_readonly(tmp_path):
    write(tmp_path, "good.py", "def f(): return 1\n")
    write(tmp_path, "broken.py", "def invalid(:\n")
    write(tmp_path, ".venv/ignored.py", "invalid code!!!")
    before = {str(f): f.read_bytes() for f in tmp_path.rglob("*.py")}
    p = analyze(tmp_path)
    assert len(p["files"]) == 1
    assert len(p["warnings"]) == 1
    assert "broken.py" in p["warnings"][0]
    assert before == {str(f): f.read_bytes() for f in tmp_path.rglob("*.py")}


def test_coverage_unknown_zero_and_invalid_revision(tmp_path):
    write(tmp_path, "a.py", "def f(x):\n    if x:\n        return 1\n    return 0\n")
    p = analyze(tmp_path)
    assert all(n["coverage"] is None for n in p["nodes"])
    report = {"meta": {"branch_coverage": True}, "files": {"a.py": {"executed_lines": [], "missing_lines": [1,2,3,4], "executed_branches": [], "missing_branches": [[2,3],[2,4]]}}}
    with pytest.raises(ValueError):
        attach_coverage(p, report, "wrong revision")
    attach_coverage(p, report, p["fingerprint"])
    assert p["nodes"][0]["coverage"]["percent"] == 0
    assert not p["nodes"][0]["coverage"]["source_verified"]
    with pytest.raises(ValueError):
        attach_coverage(p, {"files":{"unknown.py":{}}}, p["fingerprint"])


def test_document_change_invalidates_evaluation(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA", tmp_path / "storage")
    root = tmp_path / "repo"
    write(root, "a.py", "def f(): return 1\n")
    write(root, "README.md", "Contract A")
    p = analyze(root)
    p["nodes"][0]["assessment"] = {"color":"green", "stale":False}
    store.save(p)
    same = store.merge_scan(analyze(root))
    assert not same["nodes"][0]["assessment"]["stale"]
    write(root, "README.md", "Contract changed")
    changed = store.merge_scan(analyze(root))
    assert changed["nodes"][0]["assessment"]["stale"]
    assert changed["fingerprint"] != same["fingerprint"]
    assert not changed["coverage_reports"]


def test_context_is_bounded_and_has_real_references(tmp_path):
    write(tmp_path, "a.py", "def f(): return 1\n")
    write(tmp_path, "README.md", "x" * 15000)
    p = analyze(tmp_path)
    package = package_for(p, "a.py::f")
    assert package["assessment_basis"] == "predictive"
    source = next(e for e in package["evidence"] if e["id"] == "component.source")
    assert source["text"] == "def f(): return 1"
    doc = next(e for e in package["evidence"] if e["id"] == "document.0")
    assert doc["truncated"] is True
    assert len(doc["text"]) == 4000


def test_no_false_cycle_from_typing_only():
    edges = [{"source":"a","target":"b","context":"typing","internal":True}, {"source":"b","target":"a","context":"runtime","internal":True}]
    assert cycles_for(["a","b"], edges) == []


def test_duplicate_definitions_keep_children_attached(tmp_path):
    write(tmp_path, "a.py", "class C:\n    def f(self): pass\nclass C:\n    def f(self): pass\n")
    p = analyze(tmp_path)
    assert len({n["id"] for n in p["nodes"]}) == len(p["nodes"])
    classes = [n for n in p["nodes"] if n["kind"] == "class"]
    methods = [n for n in p["nodes"] if n["kind"] == "method"]
    assert [n["parent"] for n in methods] == [n["id"] for n in classes]


def test_new_file_detected_and_ignored_file_not_detected(tmp_path):
    write(tmp_path, "a.py", "x = 1\n")
    before = disk_stamp(tmp_path)
    write(tmp_path, ".venv/ignored.py", "x = 2\n")
    assert disk_stamp(tmp_path) == before
    write(tmp_path, "b.py", "x = 2\n")
    assert disk_stamp(tmp_path) != before


def test_malformed_coverage_is_rejected(tmp_path):
    write(tmp_path, "a.py", "x = 1\n")
    p = analyze(tmp_path)
    with pytest.raises(ValueError, match="lista"):
        attach_coverage(p, {"files":{"a.py":{"executed_lines":["1"],"missing_lines":[]}}}, p["fingerprint"])
    with pytest.raises(ValueError, match="a la vez"):
        attach_coverage(p, {"files":{"a.py":{"executed_lines":[1],"missing_lines":[1]}}}, p["fingerprint"])
