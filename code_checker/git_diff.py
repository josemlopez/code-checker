"""Read-only Git comparisons. Git objects and source bodies remain in memory."""
import ast
import copy
import io
import os
import json
import re
from pathlib import Path, PurePosixPath
import subprocess
import tokenize
from urllib.parse import urlsplit

from code_checker import analyzer as a
from code_checker.hierarchy import add_packages


def git(root, *args, data=None):
    env = dict(os.environ, GIT_OPTIONAL_LOCKS='0', GIT_NO_LAZY_FETCH='1', GIT_TERMINAL_PROMPT='0')
    result = subprocess.run(['git', '--no-optional-locks', '-c', 'core.fsmonitor=false', '-C', str(root), *args],
                            input=data, capture_output=True, timeout=90, env=env)
    if result.returncode:
        raise ValueError('Git no pudo resolver la comparación. Comprueba las referencias disponibles en este repositorio; no se hace fetch ni checkout.')
    return result.stdout


def resolve(root, ref):
    if not ref or len(ref) > 250 or ref.startswith('-') or any(c in ref for c in '\0\r\n'):
        raise ValueError('Referencia Git no válida.')
    return git(root, 'rev-parse', '--verify', '--end-of-options', ref + '^{commit}').decode().strip()


def options(root):
    refs = git(root, 'for-each-ref', '--format=%(refname:short)', 'refs/heads', 'refs/remotes', 'refs/tags').decode().splitlines()
    branch = git(root, 'rev-parse', '--abbrev-ref', 'HEAD').decode().strip()
    return {'refs': refs, 'branch': branch, 'head': resolve(root, 'HEAD')}


def github_repository(root):
    """Only return a canonical identity; never expose credentials from an origin URL."""
    raw = git(root, 'config', '--get', 'remote.origin.url').decode().strip()
    if '://' in raw:
        url = urlsplit(raw)
        host, path = url.hostname, url.path.lstrip('/')
    else:
        match = re.fullmatch(r'(?:[^@/]+@)?([^:/]+):(.+)', raw)
        host, path = match.groups() if match else ('', '')
    path = path.removesuffix('.git')
    if host != 'github.com' or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', path):
        raise ValueError('El selector admite repositorios de github.com con remote origin. Para otros servidores usa Comparar ramas o Dos revisiones.')
    return path


def github_get(repository, endpoint):
    try:
        result = subprocess.run(['gh', 'api', '--hostname', 'github.com', '--method', 'GET',
                                 f'repos/{repository}/{endpoint}'], capture_output=True, timeout=35,
                                env=dict(os.environ, GH_PROMPT_DISABLED='1', GH_NO_UPDATE_NOTIFIER='1'))
    except (FileNotFoundError, subprocess.TimeoutExpired):
        raise ValueError('No se pudo consultar GitHub. Se necesita gh instalado y autenticado en la máquina donde está el repositorio (el servidor SSH para proyectos remotos).') from None
    if result.returncode:
        raise ValueError('GitHub no permite consultar los PR. Comprueba el acceso de la cuenta de gh en la máquina donde está el repositorio. No se ha cambiado su configuración.')
    return json.loads(result.stdout)


def pr_metadata(row):
    base, head = row['base'], row['head']
    if not all(re.fullmatch(r'[0-9a-f]{40,64}', value) for value in (base['sha'], head['sha'])):
        raise ValueError('GitHub devolvió un commit de PR no válido.')
    number = int(row['number'])
    return {'number': number, 'title': row['title'], 'state': row['state'], 'draft': bool(row.get('draft')),
            'merged': bool(row.get('merged_at')), 'base': base['ref'], 'head': head['label'],
            'base_sha': base['sha'], 'head_sha': head['sha']}


def pull_requests(root, state='open'):
    if state not in {'open', 'closed', 'all'}:
        raise ValueError('Estado de PR no válido.')
    repository = github_repository(root)
    items = []
    # Bounded pagination. The UI also accepts a PR number outside this recent list.
    for page in range(1, 6):
        rows = github_get(repository, f'pulls?state={state}&sort=updated&direction=desc&per_page=100&page={page}')
        items.extend(pr_metadata(row) for row in rows)
        if len(rows) < 100:
            break
    return {'repository': repository, 'pull_requests': items, 'truncated': len(rows) == 100 and page == 5}


def compare_pr(root, number, scope=None):
    if not isinstance(number, int) or number < 1:
        raise ValueError('Número de PR no válido.')
    repository = github_repository(root)
    pr = pr_metadata(github_get(repository, f'pulls/{number}'))
    try:
        resolve(root, pr['base_sha'])
        resolve(root, pr['head_sha'])
    except ValueError:
        raise ValueError(f"El PR #{number} está disponible en GitHub, pero faltan sus commits en este repositorio. No se hace fetch para mantener la lectura estricta. Elige un PR cuyos commits estén presentes o una comparación de ramas disponibles.") from None
    result = compare(root, pr['base_sha'], pr['head_sha'], 'pr', scope)
    result['comparison'].update(base=pr['base'], head=pr['head'], pull_request=pr | {'repository': repository})
    return result


def accepted(path, scope):
    parts = PurePosixPath(path).parts
    if any(part in a.IGNORED or part.startswith('.') for part in parts[:-1]):
        return False
    if scope and len(parts) > 1:
        if parts[0] not in scope['code_roots'] + ['docs']:
            return False
        if parts[0] == 'docs' and len(parts) > 2 and parts[1] not in scope['doc_roots']:
            return False
    return path.endswith('.py') or path.lower().endswith('.md')


def tree_sources(root, revision, scope):
    prefix = git(root, 'rev-parse', '--show-prefix').decode().strip()
    rows, total = [], 0
    for record in git(root, 'ls-tree', '-rz', '--full-tree', revision).split(b'\0'):
        if not record:
            continue
        meta, raw_path = record.split(b'\t', 1)
        mode, kind, oid = meta.decode().split()
        path = raw_path.decode('utf-8', errors='surrogateescape')
        if kind != 'blob' or mode not in {'100644','100755'} or not path.startswith(prefix):
            continue
        path = path[len(prefix):]
        if accepted(path, scope):
            rows.append((path, oid))
    if len(rows) > a.MAX_FILES + 100:
        raise ValueError('La revisión supera el límite de archivos. Selecciona un subproyecto.')
    if not rows:
        return {}
    # Query sizes before reading blobs to bound memory and avoid fetching huge objects.
    sizes = git(root, 'cat-file', '--batch-check', data=('\n'.join(oid for _, oid in rows)+'\n').encode()).splitlines()
    for row in sizes:
        fields = row.split()
        if len(fields) != 3 or fields[1] != b'blob':
            raise ValueError('Faltan objetos Git locales; no se descargan automáticamente.')
        size = int(fields[2]);total += size
        if size > a.MAX_FILE_BYTES or total > a.MAX_TOTAL_BYTES:
            raise ValueError('La revisión supera el límite de tamaño del análisis.')
    blob = git(root, 'cat-file', '--batch', data=('\n'.join(oid for _, oid in rows)+'\n').encode())
    stream = io.BytesIO(blob); sources = {}
    for path, _ in rows:
        header = stream.readline().split();size = int(header[2])
        content = stream.read(size);stream.read(1)
        if path.endswith('.py'):
            encoding, _ = tokenize.detect_encoding(io.BytesIO(content).readline)
            sources[path] = content.decode(encoding)
        else:
            sources[path] = content.decode('utf-8', errors='replace')
    return sources


def snapshot(root, revision, scope):
    nodes, pending, files, docs, warnings, unparsed = [], [], [], [], [], []
    for path, source in tree_sources(root, revision, scope).items():
        if path.endswith('.py'):
            try:
                tree = ast.parse(source, filename=path)
                nodes.extend(a.components_for(path, path, source, tree))
                pending.extend(dict(e, source=path) for e in a.import_edges(tree, a.module_name(path), path.endswith('__init__.py')))
                files.append({'path':path, 'hash':a.digest(source), 'bytes':len(source.encode('utf-8'))})
            except (SyntaxError, ValueError, RecursionError):
                warnings.append('No analizado en esta revisión: '+path)
                unparsed.append(path)
        elif len(docs) < 100:
            docs.append({'path':path,'hash':a.digest(source),'text':source[:12000],'truncated':len(source)>12000})
    edges, cycles = a.build_graph(nodes, pending)
    p = dict(id='', root=str(root), name=Path(root).name, created_at=a.now(), fingerprint=a.digest([files,revision,a.VERSION]),
             analyzer_version=a.VERSION, nodes=nodes, edges=edges, cycles=cycles, files=files, documents=docs,
             call_edges=[e for n in nodes for e in n.get('call_edges',[])], warnings=warnings,unparsed_paths=unparsed,
             coverage_reports=[], runs=[], history=[], limitations=['Análisis estático de objetos Git; no ejecuta código ni demuestra impacto en ejecución.'])
    return add_packages(p)


def node_signatures(project):
    """Include decorators, preserve comment changes, ignore unrelated line shifts."""
    result = {}
    for module in (n for n in project['nodes'] if n['kind'] == 'module'):
        source = module['source'];lines = a.source_lines(source)
        syntax = ast.parse(source)
        starts = {(n.lineno,n.name):min([n.lineno]+[d.lineno for d in n.decorator_list])
                  for n in ast.walk(syntax) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef))}
        for n in project['nodes']:
            if n['module_id'] != module['id']:
                continue
            start = starts.get((n['line'],n['name']),n['line'])
            result[n['id']] = a.digest('\n'.join(lines[start-1:n['end_line']]))
    return result


def compare(root, base, head='HEAD', mode='pr', scope=None):
    if mode not in {'pr','direct','working'}:
        raise ValueError('Tipo de comparación no válido.')
    base_sha, head_sha = resolve(root, base), resolve(root, 'HEAD' if mode == 'working' else head)
    if mode == 'pr':
        bases = git(root, 'merge-base', '--all', base_sha, head_sha).decode().splitlines()
        if len(bases) != 1:
            raise ValueError('La comparación necesita un único ancestro común.')
        base_sha = bases[0]
    before = snapshot(root, base_sha, scope)
    if mode == 'working':
        try:
            after = a.analyze(root, scope)
        except ValueError as exc:
            if not str(exc).startswith('No se encontraron archivos Python analizables.'):
                raise
            stamp = a.disk_stamp(root,scope)
            after = dict(before,nodes=[],edges=[],call_edges=[],cycles=[],files=[],documents=[],
                         fingerprint=a.digest([stamp,a.VERSION]),disk_stamp=stamp,warnings=[str(exc)])
        # Honor Git's tracked/untracked inventory; ignored generated files are not a diff.
        eligible = {p.decode('utf-8',errors='surrogateescape') for p in git(root,'ls-files','--cached','--others','--exclude-standard','-z').split(b'\0') if p}
        after['nodes'] = [n for n in after['nodes'] if n['kind']!='package' and n['path'] in eligible]
        after['files'] = [f for f in after['files'] if f['path'] in eligible]
        after['documents'] = [d for d in after['documents'] if d['path'] in eligible]
        pending = [dict(e,source=n['path']) for n in after['nodes'] if n['kind']=='module'
                   for e in a.import_edges(ast.parse(n['source']),a.module_name(n['path']),n['path'].endswith('__init__.py'))]
        after['edges'],after['cycles'] = a.build_graph(after['nodes'],pending)
        after['call_edges'] = [e for n in after['nodes'] for e in n.get('call_edges',[])]
        after = add_packages(after)
        mapped = {f['path'] for f in after['files']}
        unknown_paths = {n['path'] for n in before['nodes'] if n['kind']=='module' and n['path'] not in mapped and (Path(root)/n['path']).is_file()}
    else:
        after = snapshot(root, head_sha, scope)
        unknown_paths = set(after['unparsed_paths'])
    before_sig, after_sig = node_signatures(before), node_signatures(after)
    old = {n['id']:n for n in before['nodes']};current = {n['id']:n for n in after['nodes']}
    direct = {}
    for id in before_sig.keys() | after_sig.keys():
        if id not in after_sig: direct[id] = 'unknown' if old[id]['path'] in unknown_paths else 'deleted'
        elif id not in before_sig: direct[id] = 'added'
        elif before_sig[id] != after_sig[id]: direct[id] = 'modified'
    for id in old.keys() - current.keys():
        ghost = copy.deepcopy(old[id]);ghost['diff_side'] = 'before'
        ghost['assessment'] = None;ghost['coverage'] = None
        after['nodes'].append(ghost);current[id] = ghost
    for id, status in direct.items():
        current[id]['diff_status'] = status
    # Preserve routes to deleted/modified symbols at every level.
    def ancestors(ids):
        result = set(ids)
        for id in list(ids):
            parent = current[id]['parent']
            while parent in current:
                result.add(parent);parent = current[parent]['parent']
        return result
    changed_ids = ancestors(direct)
    changed_modules = {current[id]['module_id'] for id in direct}
    # Reverse reachability: potential consumers, using before AND after relationships.
    reverse = {}
    for e in before['edges'] + after['edges'] + before['call_edges'] + after['call_edges']:
        if e['target'] in current and e['source'] in current:
            reverse.setdefault(e['target'],set()).add(e['source'])
    impacted, queue = set(direct) | changed_modules, list(set(direct) | changed_modules)
    while queue:
        for caller in reverse.get(queue.pop(), ()):
            if caller not in impacted:
                impacted.add(caller);queue.append(caller)
    impact_only = impacted - changed_ids
    visible_impact = ancestors(impacted)
    context_nodes = {n['id'] for n in after['nodes'] if n['module_id'] in impact_only and n['id'] not in impacted}
    visible_impact.update(context_nodes)
    for id in changed_ids - direct.keys(): current[id]['diff_status'] = 'contains'
    for id in visible_impact - changed_ids:
        current[id]['diff_status'] = 'impact' if id in impact_only else 'context' if id in context_nodes else 'impact_path'
    # Retain removed relationships only where they touch removed components.
    deleted = {id for id,status in direct.items() if status == 'deleted'}
    for key in ('edges','call_edges'):
        seen = {(e['source'],e['target']) for e in after[key]}
        for e in before[key]:
            if (e['source'] in deleted or e['target'] in deleted) and (e['source'],e['target']) not in seen:
                after[key].append(dict(e, context='removed', diff_removed=True))
    # Git-wide inventory also lists files outside Python analysis scope, including deletions.
    args = ['diff','--relative','--no-ext-diff','--no-textconv','--name-status','-z','--find-renames',base_sha]
    if mode != 'working': args.append(head_sha)
    raw = git(root,*args,'--','.').split(b'\0');files=[];i=0
    while i < len(raw) and raw[i]:
        status = raw[i].decode();path = raw[i+1].decode('utf-8',errors='replace');i+=2
        old_path = None
        if status[0] in 'RC': old_path=path;path=raw[i].decode('utf-8',errors='replace');i+=1
        files.append({'status':status,'path':path,'old_path':old_path,'mapped':path in current or (old_path or '') in current})
    if mode == 'working':
        for path in git(root,'ls-files','--others','--exclude-standard','-z').split(b'\0'):
            if path:
                value=path.decode('utf-8',errors='replace');files.append({'status':'?','path':value,'old_path':None,'mapped':value in current})
        if a.disk_stamp(root, scope) != after['disk_stamp'] or resolve(root,'HEAD') != head_sha:
            raise ValueError('Los archivos cambiaron durante la comparación. Vuelve a calcular el diff.')
    after['comparison'] = dict(base=base,head=head,mode=mode,base_sha=base_sha,head_sha=head_sha,
        changed_ids=sorted(changed_ids),impact_ids=sorted(visible_impact),
        direct_count=len(direct),impacted_count=len(impact_only),files=files,
        note='Impacto potencial por consumidores transitivos de imports y llamadas locales, antes y después. No demuestra fallos. Renombrados se muestran como baja/alta de símbolos; archivos no indexados aparecen en el inventario.' + (' Hay archivos no analizables: sus símbolos se muestran como Sin analizar, con datos anteriores.' if unknown_paths else '') + (f" {len(after['warnings'])} avisos de análisis." if after['warnings'] else ''))
    # No source/doc bodies cross SSH or enter the comparison cache.
    for n in after['nodes']: n.pop('source',None);n['docstring']=''
    for d in after['documents']: d.pop('text',None)
    return after


def component(root, revision, node, scope=None):
    if node['kind'] == 'package': return dict(node,source='')
    if revision == 'working':
        path=(Path(root)/node['path']).resolve(strict=True)
        if not path.is_relative_to(Path(root).resolve()): raise ValueError('Ruta fuera del proyecto.')
        source=a.read_source(path)
    else:
        # Read only this blob, never a checkout or the rest of the repository.
        prefix=git(root,'rev-parse','--show-prefix').decode().strip()
        raw=git(root,'show',resolve(root,revision)+':'+prefix+node['path'])
        encoding,_=tokenize.detect_encoding(io.BytesIO(raw).readline);source=raw.decode(encoding)
    found=next((n for n in a.components_for(node['path'],node['path'],source,ast.parse(source)) if n['id']==node['id']),None)
    if not found or found['hash'] != node['hash']:
        raise ValueError('El código cambió desde el diff. Vuelve a calcular la comparación.')
    return dict(node,source=found['source'])
