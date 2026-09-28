"""SSH analysis with source read on demand, never stored in the local index."""
import ast
import json
from pathlib import Path
import re
import subprocess

import radon

from .analyzer import digest
from .evaluation import POLICY_VERSION


DEFAULT_SCOPE = {'code_roots':['src','scripts','tests','test','tools','deploy'],
                 'doc_roots':['03_current_architecture','06_reference','11_testing_and_qa']}

BOOTSTRAP = r'''
import ast, json, pathlib, re, subprocess, sys, types
sys.stdout.reconfigure(encoding='utf-8')
sys.dont_write_bytecode = True
payload = json.loads(PAYLOAD)
checker_package = types.ModuleType('code_checker')
checker_package.__path__ = []
sys.modules['code_checker'] = checker_package
for name, source in payload['modules']:
    module = types.ModuleType(name)
    module.__package__ = name.rpartition('.')[0]
    if name == 'radon': module.__path__ = []
    sys.modules[name] = module
    exec(compile(source, '<code-checker:' + name + '>', 'exec'), module.__dict__)
    if name in {'checker_analyzer','checker_hierarchy'}:
        short = name.removeprefix('checker_')
        sys.modules['code_checker.' + short] = module
        setattr(checker_package, short, module)
a = sys.modules['checker_analyzer']
root = pathlib.Path(payload['root']).resolve(strict=True)
scope = payload['scope']
action = payload['action']
def git(*args):
    r = subprocess.run(['git','--no-optional-locks','-C',str(root),*args],capture_output=True,text=True)
    return r.stdout.strip() if r.returncode == 0 else None
def origin():
    return {'kind':'ssh','live':True,'host':payload['host'],'remote_path':str(root),
            'revision':git('rev-parse','HEAD'),'dirty':bool(git('status','--porcelain')),
            'scope':'Código activo, tests y herramientas; documentación de arquitectura, referencia y QA. No se indexan auditorías históricas, datos, logs ni configuración de despliegue.'}
if action == 'stamp':
    result = {'disk_stamp':a.disk_stamp(root,scope)}
elif action == 'git_options':
    result = sys.modules['code_checker.git_diff'].options(root)
elif action == 'pull_requests':
    result = sys.modules['code_checker.git_diff'].pull_requests(root,payload['state'])
elif action == 'pr_diff':
    result = sys.modules['code_checker.git_diff'].compare_pr(root,payload['number'],scope)
elif action == 'diff':
    result = sys.modules['code_checker.git_diff'].compare(root,payload['base'],payload['head'],payload['mode'],scope)
elif action == 'diff_component':
    result = sys.modules['code_checker.git_diff'].component(root,payload['revision'],payload['node'],scope)
elif action == 'component':
    node = payload['node']
    path = (root / node['path']).resolve(strict=True)
    if not path.is_relative_to(root): raise ValueError('Ruta fuera del proyecto')
    source = a.read_source(path)
    if a.digest(source) != payload['file_hash']: raise ValueError('El archivo remoto ha cambiado. Vuelve a analizar.')
    nodes = a.components_for(path,node['path'],source,ast.parse(source))
    found = next(n for n in nodes if n['id'] == node['id'])
    result = {'source':found['source']}
else:
    project = a.analyze(root,scope)
    project = sys.modules['checker_hierarchy'].add_packages(project)
    project['origin'] = origin()
    project['scan_scope'] = scope
    project['id'] = a.digest(payload['host'] + ':' + str(root))[:16]
    if action == 'scan':
        for node in project['nodes']:
            node.pop('source',None)
            node['docstring'] = ''
        for doc in project['documents']: doc.pop('text',None)
        result = project
    elif action == 'context':
        if project['fingerprint'] != payload['fingerprint']: raise ValueError('El proyecto remoto ha cambiado. Vuelve a analizar.')
        project['runs'] = payload['runs']
        for node in project['nodes']:
            node['coverage'] = payload['coverage'].get(node['id'])
        namespace = {'re':re,'POLICY_VERSION':payload['policy_version']}
        exec(payload['context_functions'],namespace)
        result = namespace['package_for'](project,payload['component_id'])
        result['origin_storage'] = 'Contexto SSH transitorio; fuentes y documentos no guardados en el índice local.'
    else: raise ValueError('Acción SSH desconocida')
print(json.dumps(result,ensure_ascii=False))
'''


def request(host, root, action, scope=None, **extra):
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.@-]*', host):
        raise ValueError('Utiliza un alias SSH sin opciones adicionales.')
    if not root.startswith('/'):
        raise ValueError('La ruta SSH debe ser absoluta.')
    base = Path(__file__).parent
    radon_dir = Path(radon.__file__).parent
    modules = [('radon',(radon_dir/'__init__.py').read_text(encoding='utf-8')),
               ('radon.visitors',(radon_dir/'visitors.py').read_text(encoding='utf-8')),
               ('radon.complexity',(radon_dir/'complexity.py').read_text(encoding='utf-8')),
               ('checker_analyzer',(base/'analyzer.py').read_text(encoding='utf-8')),
               ('checker_hierarchy',(base/'hierarchy.py').read_text(encoding='utf-8')),
               ('code_checker.git_diff',(base/'git_diff.py').read_text(encoding='utf-8'))]
    code = (base/'evaluation.py').read_text(encoding='utf-8')
    functions = '\n\n'.join(ast.get_source_segment(code,n) for n in ast.parse(code).body
                             if isinstance(n,ast.FunctionDef) and n.name in {'package_for','package_context','redact_credentials'})
    payload = dict(host=host,root=root,action=action,scope=scope or DEFAULT_SCOPE,modules=modules,
                   context_functions=functions,policy_version=POLICY_VERSION,**extra)
    script = 'PAYLOAD = ' + repr(json.dumps(payload)) + '\n' + BOOTSTRAP
    try:
        result = subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=12',host,'python3 -I -'],
                                input=script,capture_output=True,text=True,encoding='utf-8',timeout=120)
    except subprocess.TimeoutExpired:
        raise ValueError('La lectura SSH superó dos minutos.') from None
    if result.returncode:
        # No source excerpts or raw tracebacks: these can expose file content.
        message = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else ''
        if message.startswith('ValueError:'):
            raise ValueError(message[:300])
        raise ValueError('No se pudo leer el proyecto por SSH. Comprueba la conexión, la ruta y Python 3.10 o posterior.')
    return json.loads(result.stdout)


def is_remote(project):
    return project.get('origin',{}).get('kind') == 'ssh' if project.get('origin') else False


def stamp(project):
    origin = project['origin']
    return request(origin['host'],project['root'],'stamp',project.get('scan_scope'))['disk_stamp']


def component(project, node):
    if node['kind'] == 'package':
        return node | {'source':'', 'docstring':'Paquete evaluado por su estructura y contexto del nivel visible; el código de sus hijos se lee al abrirlos.'}
    origin = project['origin']
    file = next(f for f in project['files'] if f['path'] == node['path'])
    return node | request(origin['host'],project['root'],'component',project.get('scan_scope'),node=node,file_hash=file['hash'])


def context(project, identifier):
    origin = project['origin']
    return request(origin['host'],project['root'],'context',project.get('scan_scope'),
                   fingerprint=project['fingerprint'],component_id=identifier,runs=project['runs'],
                   coverage={n['id']:n['coverage'] for n in project['nodes'] if n.get('coverage')})
