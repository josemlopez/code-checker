from code_checker.analyzer import analyze
from code_checker.hierarchy import add_packages
from code_checker.evaluation import package_for


def test_scopes_annotations_and_signals_without_execution(tmp_path):
    (tmp_path / 'a.py').write_text('''raise RuntimeError("never execute")
def outer(x: int, *, flag=False) -> int:
    """A contract."""
    def inner(y):
        assert y
        logger.info(y)
    try:
        inner(x)
    except (ValueError, Exception):
        raise
    return x
class C:
    def method(self, value: str):
        return value
    @staticmethod
    def static(self: int):
        return self
def ordinary(self: int):
    return self
''')
    p = analyze(tmp_path)
    nodes = {n['name']: n for n in p['nodes']}
    a = nodes['a']['metrics']['aggregate']
    assert a['functions'] == 5
    assert a['parameters'] == 6
    assert a['annotated_parameters'] == 4
    assert a['parameter_annotation_percent'] == 66.7
    assert a['documented_functions'] == 1
    assert a['return_annotations'] == 1
    assert a['asserts'] == 1
    assert a['raises'] == 2
    assert a['exception_handlers'] == a['broad_exception_handlers'] == 1
    assert a['logging_candidates'] == 1
    assert nodes['outer']['metrics']['asserts'] == 0
    assert nodes['outer']['metrics']['aggregate']['asserts'] == 1
    assert nodes['C']['metrics']['aggregate']['functions'] == 2
    assert nodes['method']['metrics']['parameters'] == 1
    assert nodes['ordinary']['metrics']['parameters'] == 1
    assert all(n['assessment'] is None for n in p['nodes'])
    assert all(n['metrics']['measurement']['uses_model'] is False for n in p['nodes'])


def test_package_aggregation_boundary_and_context(tmp_path):
    (tmp_path / 'pkg').mkdir()
    (tmp_path / 'tests').mkdir()
    (tmp_path / 'pkg/a.py').write_text('from pkg.b import f\nfrom outside import x\ndef g():\n    assert True\n')
    (tmp_path / 'pkg/b.py').write_text('from pkg.a import g\nfrom outside import x\ndef f(v: int) -> int:\n    return v\n')
    (tmp_path / 'outside.py').write_text('x = 1\n')
    (tmp_path / 'tests/test_api.py').write_text('from pkg.a import g\nfrom pkg.b import f\n')
    p = add_packages(analyze(tmp_path))
    pkg = next(n for n in p['nodes'] if n['id'] == 'package:pkg')
    m = pkg['metrics']
    assert m['fan_in'] == m['fan_out'] == 1  # Unique boundary modules, not summed fan counts.
    assert m['cyclic_modules'] == 2
    assert m['test_importers'] == 1
    assert m['test_modules'] == 0
    assert m['aggregate']['functions'] == 2
    assert m['aggregate']['asserts'] == 1
    assert m['aggregate']['return_annotations'] == 1
    assert 'parameters' not in m  # No inherited first-module scope.
    ctx = package_for(p, pkg['id'])
    evidence = next(e['value'] for e in ctx['evidence'] if e['id'] == 'package.metrics')
    assert evidence['aggregate'] == m['aggregate']
    assert pkg['coverage'] is None


def test_empty_denominators_remain_not_applicable(tmp_path):
    (tmp_path / 'a.py').write_text('x = 1\n')
    m = analyze(tmp_path)['nodes'][0]['metrics']['aggregate']
    assert m['parameter_annotation_percent'] is None
    assert m['max_cc'] is None
    assert m['functions'] == 0
