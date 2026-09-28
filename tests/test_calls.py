from code_checker.analyzer import analyze


def test_local_calls_scopes_and_recursion(tmp_path):
    (tmp_path / 'a.py').write_text('''def helper():
    return 1
async def caller():
    helper()
    helper()
    def child():
        helper()
    child()
def recursive():
    return recursive()
def shadow(helper):
    helper()
def assigned():
    helper = lambda: 1
    helper()
class C:
    def helper(self): pass
    def method(self):
        helper()
        self.helper()
''')
    p = analyze(tmp_path)
    calls = {(e['source'].split('::')[-1], e['target'].split('::')[-1]):e for e in p['call_edges']}
    assert set(calls) == {('caller','helper'),('caller','caller.child'),('caller.child','helper'),
                          ('recursive','recursive'),('C.method','helper')}
    assert calls['caller','helper']['lines'] == [4,5]
    assert calls['caller.child','helper']['lines'] == [7]
    method = next(n for n in p['nodes'] if n['name'] == 'method')
    assert method['metrics']['local_calls_resolved'] == 1
    assert method['metrics']['calls_unresolved'] == 1


def test_ambiguous_names_and_definition_expressions_are_not_false_edges(tmp_path):
    (tmp_path / 'a.py').write_text('''def helper(): pass
def helper(): pass
def unique(): pass
def caller(x=unique()):
    helper()
    external.run()
    [unique() for unique in []]
def imported():
    from other import unique
    unique()
def redirected():
    global unique
    unique()
''')
    p = analyze(tmp_path)
    assert p['call_edges'] == []
    caller = next(n for n in p['nodes'] if n['name'] == 'caller')
    assert caller['metrics']['calls_unresolved'] == 3


def test_calls_are_evidence_without_executing_project(tmp_path):
    (tmp_path / 'a.py').write_text('''raise RuntimeError('not executed')
def target(): pass
def caller(): target()
''')
    from code_checker.evaluation import package_for
    p = analyze(tmp_path)
    ctx = package_for(p, 'a.py::caller')
    evidence = next(e for e in ctx['evidence'] if e['id'] == 'component.local_calls')
    assert evidence['value'][0]['target'] == 'a.py::target'
    assert evidence['value'][0]['lines'] == [3]
