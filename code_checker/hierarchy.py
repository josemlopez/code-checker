"""Directory nodes used for evaluation at the currently visible level."""


def add_packages(project):
    modules = [n for n in project['nodes'] if n['kind'] == 'module']
    groups = {}
    for node in modules:
        parts = node['path'].split('/')[:-1]
        node['parent'] = 'package:'+'/'.join(parts) if parts else None
        for depth in range(1,len(parts)+1):
            path = '/'.join(parts[:depth])
            groups.setdefault(path,[]).append(node)
    for path,members in sorted(groups.items()):
        identifier = 'package:'+path
        # A package has no executable AST scope of its own. Do not inherit facts
        # (parameters, nesting, fan-in, etc.) from its arbitrary first module.
        metrics = dict(lines=sum(n['metrics']['lines'] for n in members),cc=None,max_cc=None,
                       functions=sum(n['metrics']['functions'] for n in members),modules=len(members),
                       effect_candidates=[],global_declarations=[],cycle=[])
        node = dict(id=identifier,name=path.split('/')[-1],qualified_name=path.replace('/','.'),
                    kind='package',parent='package:'+path.rpartition('/')[0] if '/' in path else None,
                    module_id=identifier,path=path,line=0,end_line=0,source='',hash='',docstring='',
                    is_test=all(n['is_test'] for n in members),metrics=metrics,coverage=None,assessment=None)
        project['nodes'].append(node)
    # Imported here to keep the analyzer independent of package construction.
    from code_checker.analyzer import enrich_metrics
    enrich_metrics(project['nodes'], project['edges'], project['cycles'])
    return project
