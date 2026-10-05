import os
import subprocess

import pytest
from fastapi.testclient import TestClient

from code_checker import app as app_module, deep_link, store
from code_checker.analyzer import digest
from code_checker.app import app


@pytest.fixture
def roots(tmp_path):
    allowed = tmp_path / 'allowed'
    repo = allowed / 'repo'
    (repo / 'pkg').mkdir(parents=True)
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    (allowed / 'plain').mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    subprocess.run(['git', 'init', '-q', str(outside)], check=True)
    return allowed, repo, outside


def parse(pairs, allowed):
    return deep_link.parse(list(pairs.items()) if isinstance(pairs, dict) else pairs, [allowed.resolve()])


def test_pr_link_normalises_and_defaults(roots):
    allowed, repo, _ = roots
    result = parse({'project': str(repo), 'pr': '465', 'diff': '1', 'impact': '1'}, allowed)
    assert result == {'path': str(repo.resolve()), 'project_id': digest(str(repo.resolve()))[:16], 'mode': 'pr',
                      'pr': 465, 'base': None, 'rev': None, 'diff': True, 'impact': True}
    # A comparison implies the diff view unless diff=0; impact stays off unless asked.
    assert parse({'project': str(repo), 'pr': '7'}, allowed)['diff'] is True
    assert parse({'project': str(repo), 'pr': '7'}, allowed)['impact'] is False
    assert parse({'project': str(repo), 'pr': '7', 'diff': '0'}, allowed)['diff'] is False


def test_branch_link_and_subfolder_of_repository(roots):
    allowed, repo, _ = roots
    result = parse({'project': str(repo / 'pkg'), 'base': 'main', 'rev': 'origin/feature-x_1.2'}, allowed)
    assert (result['mode'], result['base'], result['rev'], result['diff']) == ('branches', 'main', 'origin/feature-x_1.2', True)
    assert parse({'project': str(repo)}, allowed)['mode'] is None


@pytest.mark.parametrize('pairs', [
    {'project': 'relative/path'},
    {'project': '/does/not/exist/anywhere'},
    {'pr': '1'},
    {'project': '{repo}', 'pr': '0'},
    {'project': '{repo}', 'pr': '-1'},
    {'project': '{repo}', 'pr': '1.5'},
    {'project': '{repo}', 'pr': '12abc'},
    {'project': '{repo}', 'pr': '99999999999'},
    {'project': '{repo}', 'pr': '1', 'base': 'main', 'rev': 'x'},
    {'project': '{repo}', 'base': 'main'},
    {'project': '{repo}', 'rev': 'x'},
    {'project': '{repo}', 'base': '--upload-pack=x', 'rev': 'x'},
    {'project': '{repo}', 'base': 'main', 'rev': 'a..b'},
    {'project': '{repo}', 'base': 'main', 'rev': 'x@{1}'},
    {'project': '{repo}', 'base': 'main', 'rev': 'feature.lock'},
    {'project': '{repo}', 'base': 'main', 'rev': 'a b'},
    {'project': '{repo}', 'pr': '1', 'diff': 'yes'},
    {'project': '{repo}', 'diff': '1'},
    {'project': '{repo}', 'impact': '1'},
    {'project': '{repo}', 'pr': '1', 'cmd': 'x'},
    {'project': '{plain}'},
])
def test_invalid_links_are_rejected(roots, pairs):
    allowed, repo, _ = roots
    pairs = {k: v.replace('{repo}', str(repo)).replace('{plain}', str(allowed / 'plain')) for k, v in pairs.items()}
    with pytest.raises(ValueError):
        parse(pairs, allowed)


def test_repeated_parameters_are_rejected(roots):
    allowed, repo, _ = roots
    with pytest.raises(ValueError):
        parse([('project', str(repo)), ('pr', '1'), ('pr', '2')], allowed)


def test_paths_outside_the_allowlist_are_forbidden(roots, tmp_path):
    allowed, repo, outside = roots
    with pytest.raises(deep_link.Forbidden):
        parse({'project': str(outside)}, allowed)
    with pytest.raises(deep_link.Forbidden):
        parse({'project': str(repo / '..' / '..' / 'outside')}, allowed)
    link = allowed / 'escape'
    os.symlink(outside, link)
    with pytest.raises(deep_link.Forbidden):
        parse({'project': str(link)}, allowed)
    with pytest.raises(deep_link.Forbidden):
        deep_link.parse([('project', str(repo))], [])


def test_allowed_roots_from_environment(tmp_path):
    present = tmp_path / 'a'
    present.mkdir()
    assert deep_link.allowed_roots(os.pathsep.join([str(present), str(tmp_path / 'missing'), ''])) == [present.resolve()]
    with pytest.raises(ValueError):
        deep_link.allowed_roots('relative')


def test_deep_link_endpoint_validates_and_reuses_local_index(roots, tmp_path, monkeypatch):
    allowed, repo, outside = roots
    monkeypatch.setattr(store, 'DATA', tmp_path / 'storage')
    with TestClient(app) as client:
        monkeypatch.delenv(deep_link.ENV, raising=False)
        assert client.get('/api/deep-link', params={'project': str(repo), 'pr': '1'}).status_code == 403
        monkeypatch.setenv(deep_link.ENV, str(allowed))
        assert client.get('/api/deep-link', params={'project': str(outside), 'pr': '1'}).status_code == 403
        assert client.get('/api/deep-link', params={'project': str(repo), 'pr': 'x'}).status_code == 422
        data = client.get('/api/deep-link', params={'project': str(repo), 'pr': '465', 'diff': '1', 'impact': '1'})
        assert data.status_code == 200
        assert data.json()['project_id'] is None and data.json()['pr'] == 465
        assert data.headers['cache-control'] == 'no-store'
        pid = digest(str(repo.resolve()))[:16]
        store.save({'id': pid, 'root': str(repo.resolve()), 'name': 'repo', 'created_at': 'x', 'origin': None})
        assert client.get('/api/deep-link', params={'project': str(repo), 'pr': '1'}).json()['project_id'] == pid
        store.save({'id': pid, 'root': str(repo.resolve()), 'name': 'repo', 'created_at': 'x', 'origin': {'kind': 'ssh'}})
        assert client.get('/api/deep-link', params={'project': str(repo), 'pr': '1'}).json()['project_id'] is None


def test_models_switch_blocks_every_model_call(tmp_path, monkeypatch):
    def forbidden_model(*args, **kwargs):
        raise AssertionError('The model must not run when models are disabled')
    monkeypatch.setattr('code_checker.app.evaluate', forbidden_model)
    monkeypatch.setattr(app_module, 'MODELS_ENABLED', False)
    monkeypatch.setattr(store, 'DATA', tmp_path / 'storage')
    with TestClient(app) as client:
        config = client.get('/api/config').json()
        assert config['models_enabled'] is False and config['codex_available'] is False
        headers = {'X-Code-Checker-Token': config['token']}
        for question in ('', 'Why?'):
            response = client.post('/api/projects/0123456789abcdef/evaluate', headers=headers,
                                   json={'component_id': 'a.py', 'question': question})
            assert response.status_code == 403
