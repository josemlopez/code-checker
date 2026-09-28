import json
import pytest
import httpx

from code_checker.evaluation import evaluate, package_for, DIMENSIONS, assessment_schema
from code_checker.analyzer import analyze


def response_data():
    return {"color":"yellow", "summary":"Localized friction", "responsibility":"A tiny example", "dimensions":[{"key":k,"level":"unknown","explanation":"Insufficient evidence", "evidence_refs":["component.source"]} for k in DIMENSIONS], "findings":[{"title":"Example", "detail":"Check the function", "evidence_refs":["component.source"]}], "next_actions":["Inspect a test"], "unknowns":["No runtime evidence"], "answer":"A bounded answer"}


def test_ollama_adapter_validates_schema_and_evidence(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text("def f(): return 1", encoding="utf-8")
    package = package_for(analyze(tmp_path), "a.py::f")
    result = response_data()
    def fake_post(url, **kwargs):
        assert url == "http://127.0.0.1:11434/api/chat"
        assert kwargs["json"]["format"]["additionalProperties"] is False
        for definition in ('Finding','Dimension'):
            assert kwargs['json']['format']['$defs'][definition]['properties']['evidence_refs']['items']['enum'] == sorted(e['id'] for e in package['evidence'])
        assert kwargs["trust_env"] is False
        return httpx.Response(200, json={"message":{"content":json.dumps(result)},"prompt_eval_count":100,"eval_count":40}, request=httpx.Request("POST",url))
    monkeypatch.setattr(httpx, "post", fake_post)
    assessed = evaluate(package, provider="ollama", model="test-model")
    assert assessed["basis"] == "predictive"
    assert assessed["usage"]["input_tokens"] == 100
    result["findings"][0]["evidence_refs"] = ["imaginary.evidence"]
    with pytest.raises(ValueError, match="inexistente"):
        evaluate(package, provider="ollama", model="test-model")


def test_model_cannot_omit_dimensions_or_findings_evidence(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text("x = 1", encoding="utf-8")
    package = package_for(analyze(tmp_path), "a.py")
    result = response_data()
    monkeypatch.setattr(httpx, "post", lambda url, **kwargs: httpx.Response(200, json={"message":{"content":json.dumps(result)}},request=httpx.Request("POST",url)))
    result["dimensions"] = result["dimensions"][:4]
    with pytest.raises(ValueError, match="cinco dimensiones"):
        evaluate(package, provider="ollama", model="test-model")
    result["dimensions"] = response_data()["dimensions"]
    result["findings"][0]["evidence_refs"] = []
    with pytest.raises(ValueError, match="sin evidencia"):
        evaluate(package, provider="ollama", model="test-model")


def test_ollama_only_accepts_local_endpoint():
    with pytest.raises(ValueError, match="loopback"):
        evaluate({"evidence":[]}, provider="ollama", model="test", endpoint="http://example.com")


def test_schema_uses_only_current_level_catalog_without_leaking_between_calls():
    package={'evidence':[{'id':'package.children'},{'id':'document.0'}]}
    function={'evidence':[{'id':'component.source'},{'id':'component.metrics'}]}
    for context in (package,function,package):
        schema=assessment_schema(context)
        for definition in ('Finding','Dimension'):
            refs=schema['$defs'][definition]['properties']['evidence_refs']
            assert refs['items']['enum'] == sorted(e['id'] for e in context['evidence'])
        assert schema['$defs']['Finding']['properties']['evidence_refs']['minItems'] == 1


def test_empty_catalog_requires_empty_citations_and_no_findings():
    schema=assessment_schema({'evidence':[]})
    assert schema['properties']['findings']['maxItems'] == 0
    for definition in ('Finding','Dimension'):
        assert schema['$defs'][definition]['properties']['evidence_refs']['maxItems'] == 0


def test_codex_receives_schema_with_package_citation_enum(monkeypatch):
    from pathlib import Path
    from code_checker import evaluation
    package={'evidence':[{'id':'package.children'},{'id':'document.0'}], 'fingerprint':'revision'}
    result=response_data()
    for item in result['findings']+result['dimensions']:
        item['evidence_refs']=['package.children']
    monkeypatch.setattr(evaluation,'codex_command',lambda:['codex'])
    class Process:
        returncode=0
        def __init__(self,args,**kwargs):
            schema=json.loads(Path(args[args.index('--output-schema')+1]).read_text(encoding='utf-8'))
            for definition in ('Finding','Dimension'):
                assert schema['$defs'][definition]['properties']['evidence_refs']['items']['enum'] == ['document.0','package.children']
            Path(args[args.index('-o')+1]).write_text(json.dumps(result),encoding='utf-8')
        def communicate(self,prompt,timeout):
            assert 'IDENTIFICADORES PERMITIDOS' in prompt
            return '', ''
    monkeypatch.setattr(evaluation.subprocess,'Popen',Process)
    assert evaluate(package,provider='codex',model='gpt-6-luna')['findings'][0]['evidence_refs'] == ['package.children']
