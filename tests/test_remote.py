import ast
import json
import subprocess
import sys

import pytest

from code_checker import remote, store


def test_remote_protocol_reads_on_demand_without_persisting_sources(tmp_path, monkeypatch):
    root = tmp_path / 'project'
    root.mkdir()
    source = '"""Private documentation."""\ndef f(): return 987654321\n'
    (root / 'a.py').write_text(source)
    (root / 'README.md').write_text('Private contract text.')
    actual_run = subprocess.run
    def transport(args, **kwargs):
        assert args[0] == 'ssh'
        assert args[-1] == 'python3 -I -'
        payload = json.loads(ast.literal_eval(kwargs['input'].splitlines()[0].split(' = ',1)[1]))
        payload['root'] = str(root)
        script = 'PAYLOAD = ' + repr(json.dumps(payload)) + '\n' + remote.BOOTSTRAP
        return actual_run([sys.executable,'-I','-'],input=script,capture_output=True,text=True,encoding='utf-8',timeout=20)
    monkeypatch.setattr(remote.subprocess,'run',transport)
    monkeypatch.setattr(store,'DATA',tmp_path/'storage')
    p = remote.request('example','/project','scan')
    store.save(p)
    persisted = (store.DATA / (p['id']+'.json')).read_text(encoding='utf-8')
    assert '987654321' not in persisted
    assert 'Private documentation' not in persisted
    assert 'Private contract text' not in persisted
    assert all('source' not in n for n in p['nodes'])
    module_metrics = next(n['metrics'] for n in p['nodes'] if n['id'] == 'a.py')
    assert module_metrics['aggregate']['functions'] == 1
    assert module_metrics['measurement']['uses_model'] is False
    # Use the public request surface with the simulated POSIX remote path.
    p['root'] = '/project'
    node = next(n for n in p['nodes'] if n['id']=='a.py')
    assert remote.component(p,node)['source'] == source.rstrip('\n')
    ctx = remote.context(p,'a.py')
    assert any('Private contract text' in e.get('text','') for e in ctx['evidence'])
    assert (store.DATA / (p['id']+'.json')).read_text(encoding='utf-8') == persisted
    assert (root / 'a.py').read_text() == source
    (root/'a.py').write_text(source+'x = 2\n')
    with pytest.raises(ValueError,match='cambiado'):
        remote.component(p,node)


def test_ssh_host_cannot_supply_options():
    with pytest.raises(ValueError):
        remote.request('-oProxyCommand=bad','/project','scan')


def test_package_context_does_not_include_descendant_bodies(tmp_path):
    from code_checker.analyzer import analyze
    from code_checker.hierarchy import add_packages
    from code_checker.evaluation import package_for
    (tmp_path/'src'/'billing').mkdir(parents=True)
    (tmp_path/'src'/'billing'/'settle.py').write_text('def settle():\n    return "DESCENDANT_BODY_MARKER"\n')
    project=add_packages(analyze(tmp_path))
    ctx=package_for(project,'package:src')
    assert 'DESCENDANT_BODY_MARKER' not in json.dumps(ctx)
    children=next(e for e in ctx['evidence'] if e['id']=='package.children')['value']
    assert [n['id'] for n in children] == ['package:src/billing']
