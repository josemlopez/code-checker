import subprocess
from pathlib import Path

import pytest

from code_checker.git_diff import compare, component


def run(root, *args):
    return subprocess.run(['git','-C',str(root),*args],check=True,capture_output=True).stdout.decode().strip()


def write(root, path, source):
    p=root/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(source,encoding='utf-8')


@pytest.fixture
def repo(tmp_path):
    run(tmp_path,'init','-b','main')
    run(tmp_path,'config','user.email','test@example.invalid');run(tmp_path,'config','user.name','Test')
    write(tmp_path,'src/lib/core.py','def kept():\n    return 1\ndef removed():\n    return 2\n')
    write(tmp_path,'src/api/entry.py','from lib.core import kept\ndef consumer():\n    return kept()\n')
    write(tmp_path,'src/other.py','def unrelated():\n    return 0\n')
    run(tmp_path,'add','.');run(tmp_path,'commit','-m','base')
    return tmp_path


def test_worktree_diff_preserves_hierarchy_deletions_and_transitive_impact(repo):
    write(repo,'src/lib/core.py','def kept():\n    return 10\n')
    write(repo,'src/new.py','def added():\n    return 9\n')
    write(repo,'settings.txt','non-Python file')
    write(repo,'.gitignore','generated.py\n')
    write(repo,'generated.py','def ignored(): return 1\n')
    before={str(p.relative_to(repo)):p.read_bytes() for p in repo.rglob('*') if p.is_file()}
    diff=compare(repo,'HEAD',mode='working')
    nodes={n['id']:n for n in diff['nodes']};c=diff['comparison']
    assert nodes['src/lib/core.py::kept']['diff_status']=='modified'
    assert nodes['src/lib/core.py::removed']['diff_status']=='deleted'
    assert nodes['src/new.py::added']['diff_status']=='added'
    assert 'package:src/lib' in c['changed_ids']
    assert 'package:src' in c['changed_ids']
    assert 'src/other.py' not in c['impact_ids']
    assert nodes['src/api/entry.py']['diff_status']=='impact'
    assert nodes['src/api/entry.py::consumer']['diff_status']=='context'
    assert 'src/api/entry.py' not in c['changed_ids']
    assert all('source' not in n for n in diff['nodes'])
    assert 'generated.py' not in nodes
    old=component(repo,c['base_sha'],nodes['src/lib/core.py::removed'])
    assert 'return 2' in old['source']
    assert any(f['path']=='settings.txt' and not f['mapped'] for f in c['files'])
    after={str(p.relative_to(repo)):p.read_bytes() for p in repo.rglob('*') if p.is_file()}
    assert before==after  # Includes the Git index, refs, config and working files.


def test_pr_uses_merge_base_and_target_objects_without_checkout(repo):
    base=run(repo,'rev-parse','HEAD')
    run(repo,'checkout','-b','feature')
    write(repo,'src/lib/core.py','# shifted lines\ndef kept():\n    return 1\ndef removed():\n    return 20\n')
    run(repo,'add','.');run(repo,'commit','-m','feature')
    feature=run(repo,'rev-parse','HEAD')
    run(repo,'checkout','main')
    write(repo,'src/other.py','def unrelated():\n    return 123\n')
    run(repo,'add','.');run(repo,'commit','-m','main advances')
    diff=compare(repo,'main','feature','pr')
    c=diff['comparison'];nodes={n['id']:n for n in diff['nodes']}
    assert c['base_sha']==base and c['head_sha']==feature
    assert 'diff_status' not in nodes['src/lib/core.py::kept']
    assert nodes['src/lib/core.py::removed']['diff_status']=='modified'
    assert 'src/other.py' not in c['changed_ids']
    assert 'return 20' in component(repo,feature,nodes['src/lib/core.py::removed'])['source']
    assert run(repo,'branch','--show-current')=='main'
    assert 'return 2' in (repo/'src/lib/core.py').read_text()


def test_decorators_empty_diff_invalid_ref_and_renames(repo):
    write(repo,'src/lib/core.py','@decorator\ndef kept():\n    return 1\ndef removed():\n    return 2\n')
    diff=compare(repo,'HEAD',mode='working')
    assert next(n for n in diff['nodes'] if n['id']=='src/lib/core.py::kept')['diff_status']=='modified'
    assert compare(repo,'HEAD','HEAD','direct')['comparison']['changed_ids']==[]
    with pytest.raises(ValueError): compare(repo,'--output=bad',mode='working')
    with pytest.raises(ValueError): compare(repo,'does-not-exist',mode='working')
    run(repo,'restore','src/lib/core.py')
    run(repo,'mv','src/lib/core.py','src/lib/renamed.py')
    c=compare(repo,'HEAD',mode='working')['comparison']
    assert any(f['status'].startswith('R') and f['old_path']=='src/lib/core.py' for f in c['files'])


def test_unparseable_is_not_claimed_deleted_and_empty_tree_is_supported(repo):
    write(repo,'src/lib/core.py','def broken(:\n')
    p=compare(repo,'HEAD',mode='working')
    assert next(n for n in p['nodes'] if n['id']=='src/lib/core.py::kept')['diff_status']=='unknown'
    for path in repo.rglob('*.py'): path.unlink()
    p=compare(repo,'HEAD',mode='working')
    assert next(n for n in p['nodes'] if n['id']=='src/lib/core.py::kept')['diff_status']=='deleted'


def test_api_comparison_keeps_live_index_and_reads_deleted_source(repo, tmp_path, monkeypatch):
    import time
    from fastapi.testclient import TestClient
    from code_checker import store
    from code_checker.analyzer import analyze
    from code_checker.app import app
    monkeypatch.setattr(store,'DATA',tmp_path/'cache')
    p=analyze(repo);store.save(p)
    original=store.get(p['id'])
    write(repo,'src/lib/core.py','def kept():\n    return 3\n')
    with TestClient(app) as client:
        token=client.get('/api/config').json()['token']
        result=client.post(f"/api/projects/{p['id']}/diff",headers={'X-Code-Checker-Token':token},json={'base':'HEAD','mode':'working'}).json()
        for _ in range(200):
            job=client.get('/api/jobs/'+result['job_id']).json()
            if job['status'] in {'completed','failed'}:break
            time.sleep(.03)
        assert job['status']=='completed',job
        assert job['result']['project']['comparison']['direct_count']>0
        data=client.get('/api/diffs/'+result['job_id']+'/component',params={'id':'src/lib/core.py::removed'}).json()
        assert 'return 2' in data['source']
        assert store.get(p['id'])==original


def test_github_origin_sanitized_and_restricted(repo):
    from code_checker.git_diff import github_repository
    for url in ['git@github.com:org/project.git', 'https://secret@github.com/org/project.git', 'ssh://git@github.com/org/project.git']:
        run(repo,'config','remote.origin.url',url)
        assert github_repository(repo)=='org/project'
    run(repo,'config','remote.origin.url','https://secret@example.com/org/project.git')
    with pytest.raises(ValueError, match='github.com') as error: github_repository(repo)
    assert 'secret' not in str(error.value)


def test_pr_list_pagination_and_compare_pins_provider_commits(repo, monkeypatch):
    from code_checker import git_diff
    run(repo,'config','remote.origin.url','git@github.com:org/project.git')
    base=run(repo,'rev-parse','HEAD')
    write(repo,'src/lib/core.py','def kept():\n    return 99\n')
    run(repo,'add','.');run(repo,'commit','-m','PR change')
    head=run(repo,'rev-parse','HEAD')
    row={'number':42,'title':'A PR','state':'open','base':{'sha':base,'ref':'main'},
         'head':{'sha':head,'label':'fork:same-name'},'draft':True,'merged_at':None}
    calls=[]
    def get(repository,endpoint):
        calls.append((repository,endpoint))
        return row if endpoint=='pulls/42' else [row]*100 if endpoint.endswith('&page=1') else []
    monkeypatch.setattr(git_diff,'github_get',get)
    listed=git_diff.pull_requests(repo,'all')
    assert len(calls)==2 and len(listed['pull_requests'])==100 and not listed['truncated']
    before={str(p.relative_to(repo)):p.read_bytes() for p in repo.rglob('*') if p.is_file()}
    result=git_diff.compare_pr(repo,42)
    assert result['comparison']['head_sha']==head
    assert result['comparison']['pull_request']['head']=='fork:same-name'
    assert result['comparison']['pull_request']['draft'] is True
    assert before=={str(p.relative_to(repo)):p.read_bytes() for p in repo.rglob('*') if p.is_file()}
    row['head']['sha']='0'*40
    with pytest.raises(ValueError,match='faltan sus commits'):git_diff.compare_pr(repo,42)


def test_github_api_is_read_only_and_errors_hide_credentials(monkeypatch):
    from code_checker import git_diff
    from types import SimpleNamespace
    calls=[]
    def run(args,**kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=1,stdout=b'',stderr=b'secret auth detail')
    monkeypatch.setattr(git_diff.subprocess,'run',run)
    with pytest.raises(ValueError) as error:git_diff.github_get('org/project','pulls')
    assert 'secret' not in str(error.value)
    assert calls[0][calls[0].index('--method')+1]=='GET'
    assert calls[0][calls[0].index('--hostname')+1]=='github.com'


def test_pr_api_reads_remote_list_and_dispatches_selected_number(tmp_path,monkeypatch):
    import time
    from fastapi.testclient import TestClient
    from code_checker import remote,store
    from code_checker.app import app
    p={'id':'test-pr','root':'/project','origin':{'kind':'ssh','host':'server'}}
    monkeypatch.setattr(store,'get',lambda _:p)
    calls=[]
    def request(host,root,action,*args,**kwargs):
        calls.append((action,kwargs))
        return {'repository':'org/project','pull_requests':[]} if action=='pull_requests' else {'comparison':{'pull_request':{'number':kwargs['number']}}}
    monkeypatch.setattr(remote,'request',request)
    with TestClient(app) as client:
        assert client.get('/api/projects/test-pr/pull-requests?state=closed').status_code==200
        assert calls[-1]==('pull_requests',{'state':'closed'})
        assert client.get('/api/projects/test-pr/pull-requests?state=bad').status_code==422
        token=client.get('/api/config').json()['token']
        response=client.post('/api/projects/test-pr/diff',headers={'X-Code-Checker-Token':token},json={'mode':'pr','pr_number':42,'head':'wrong-branch'})
        for _ in range(100):
            job=client.get('/api/jobs/'+response.json()['job_id']).json()
            if job['status'] in {'completed','failed'}:break
            time.sleep(.01)
        assert job['status']=='completed',job
        assert calls[-1]==('pr_diff',{'number':42})
