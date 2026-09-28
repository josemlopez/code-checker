import json

from code_checker.analyzer import analyze
from code_checker.evaluation import package_for, redact_credentials


def test_large_context_selects_relevant_docs_tests_and_origin(tmp_path):
    (tmp_path / 'src').mkdir()
    (tmp_path / 'tests').mkdir()
    (tmp_path / 'docs').mkdir()
    (tmp_path / 'src' / 'billing.py').write_text('def settle(): return 1\n')
    (tmp_path / 'tests' / 'test_billing.py').write_text('from billing import settle\ndef test_settle(): assert settle() == 1\n')
    for i in range(30):
        (tmp_path / 'docs' / f'a{i}.md').write_text('Unrelated material')
    (tmp_path / 'docs' / 'billing_contract.md').write_text('Billing must settle exactly once.')
    (tmp_path / '.codechecker-snapshot.json').write_text(json.dumps({'kind':'ssh-working-tree-snapshot','host':'test','remote_path':'/project','revision':'123','dirty':True,'live':False}))
    project = analyze(tmp_path)
    assert len(project['documents']) == 31
    context = package_for(project, 'src/billing.py')
    assert any(e.get('path') == 'docs/billing_contract.md' for e in context['evidence'])
    tests = next(e for e in context['evidence'] if e['id'] == 'component.related_tests')
    assert tests['value'][0]['path'] == 'tests/test_billing.py'
    assert next(e for e in context['evidence'] if e['id'] == 'project.origin')['value']['live'] is False


def test_context_redaction_preserves_local_source(tmp_path):
    secret = 'sk-proj-' + 'a' * 40
    source = f'API_KEY = "{secret}"\n'
    (tmp_path / 'a.py').write_text(source)
    project = analyze(tmp_path)
    assert secret not in json.dumps(package_for(project, 'a.py'))
    assert (tmp_path / 'a.py').read_text() == source
    assert redact_credentials('token = "' + 'x'*40 + '"') == '[REDACTED_CREDENTIAL_CANDIDATE]'
