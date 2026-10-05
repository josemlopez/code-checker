"""Read Python as data. Never import or execute the inspected project."""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import tokenize
from datetime import datetime, timezone
from pathlib import Path

from radon.complexity import cc_visit

VERSION = "1.3.1"
IGNORED = {".git", ".venv", "venv", "env", "node_modules", "__pycache__", ".codechecker", ".pytest_cache", ".mypy_cache", "site-packages", "dist", "build"}
MAX_FILES = 1500
MAX_FILE_BYTES = 500_000
MAX_TOTAL_BYTES = 20_000_000
LINE_BREAK = re.compile(r'\r\n|\r|\n')


def source_lines(source):
    """Split lines as Python's tokenizer and AST line numbers do (\\n, \\r\\n, \\r).

    str.splitlines also breaks on \\x0c, \\x1c-\\x1e, \\x85, \\u2028 and \\u2029, which may
    appear inside string literals; that shifts AST line numbers and corrupts fragments.
    """
    lines = LINE_BREAK.split(source)
    if lines and lines[-1] == '':
        lines.pop()
    return lines


def digest(value):
    if not isinstance(value, str):
        value = json.dumps(value, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def module_name(relative):
    parts = list(Path(relative).with_suffix("").parts)
    if parts and parts[0] == "src":
        parts.pop(0)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) or "__root__"


class LocalFacts(ast.NodeVisitor):
    """Counts only this scope, excluding nested function/class bodies."""
    def __init__(self, root):
        self.root = root
        self.depth = 0
        self.max_depth = 0
        self.raises = 0
        self.asserts = 0
        self.globals = []
        self.effects = []
        self.statements = 0
        self.handlers = 0
        self.broad_handlers = 0
        self.logging_candidates = 0
        self.calls = 0

    def visit(self, node):
        if node is not self.root and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            return
        if isinstance(node, ast.stmt):
            self.statements += 1
        nested = isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.With, ast.AsyncWith, ast.Match))
        if nested:
            self.depth += 1
            self.max_depth = max(self.max_depth, self.depth)
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            self.globals.extend(node.names)
        if isinstance(node, ast.Raise):
            self.raises += 1
        if isinstance(node, ast.Assert):
            self.asserts += 1
        if isinstance(node, ast.ExceptHandler):
            self.handlers += 1
            types = node.type.elts if isinstance(node.type, ast.Tuple) else [node.type]
            if any(t is None or isinstance(t, ast.Name) and t.id in {'Exception', 'BaseException'} for t in types):
                self.broad_handlers += 1
        if isinstance(node, ast.Call):
            self.calls += 1
            name = ast.unparse(node.func)
            if isinstance(node.func, ast.Attribute) and node.func.attr in {'debug','info','warning','warn','error','exception','critical','log'}:
                self.logging_candidates += 1
            if name == "open" or any(part in name.lower() for part in ("write", "execute", "commit", "request", "send", "unlink", "remove", "print")):
                self.effects.append({"call": name[:120], "line": node.lineno, "certainty": "heuristic"})
        super().visit(node)
        if nested:
            self.depth -= 1


def read_source(path):
    with tokenize.open(path) as file:
        return file.read()


def scoped_walk(root, scope=None):
    for folder, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in IGNORED and not d.startswith('.') and not (Path(folder) / d).is_symlink())
        relative = Path(folder).relative_to(root).as_posix()
        if scope:
            if relative == '.':
                dirs[:] = [d for d in dirs if d in scope['code_roots'] or d == 'docs']
            elif relative == 'docs':
                dirs[:] = [d for d in dirs if d in scope['doc_roots']]
        yield folder, dirs, names


def disk_stamp(root_path, scope=None):
    """Cheap change detection, including newly added and removed source/docs."""
    root = Path(root_path)
    inventory = []
    for folder, dirs, names in scoped_walk(root, scope):
        for name in sorted(names):
            path = Path(folder) / name
            if path.suffix.lower() in {".py", ".md"} and not path.is_symlink():
                try:
                    stat = path.stat()
                    inventory.append((path.relative_to(root).as_posix(), stat.st_size, stat.st_mtime_ns))
                except OSError:
                    inventory.append((str(path), "unavailable"))
    return digest(inventory)


def components_for(path, relative, source, tree):
    mod = module_name(relative)
    module_id = relative
    lines = source_lines(source)
    cc = {}

    def collect_cc(blocks):
        for block in blocks:
            if not hasattr(block, "methods"):
                cc[(block.lineno, block.name)] = block.complexity
            collect_cc(getattr(block, "closures", []))
            collect_cc(getattr(block, "methods", []))

    collect_cc(cc_visit(source))
    nodes = []

    def add(node, qualname, kind, parent):
        start = getattr(node, "lineno", 1)
        end = getattr(node, "end_lineno", len(lines)) or len(lines)
        identifier = module_id if kind == "module" else f"{module_id}::{qualname}"
        if any(existing["id"] == identifier for existing in nodes):
            identifier += f"@{start}"
        facts = LocalFacts(node)
        facts.visit(node)
        doc = ast.get_docstring(node) or ""
        params = []
        typed = 0
        returns = False
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            arguments = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
            arguments += [arg for arg in (node.args.vararg, node.args.kwarg) if arg]
            if kind == 'method' and arguments and arguments[0].arg in {'self','cls'} and not any(isinstance(d, ast.Name) and d.id == 'staticmethod' for d in node.decorator_list):
                arguments = arguments[1:]
            params = [arg.arg for arg in arguments]
            typed = sum(arg.annotation is not None for arg in arguments)
            returns = node.returns is not None
        fragment = "\n".join(lines[start - 1:end])
        nodes.append({
            "id": identifier, "name": mod if kind == "module" else node.name,
            "qualified_name": mod if kind == "module" else f"{mod}.{qualname}",
            "kind": kind, "parent": parent, "module_id": module_id, "path": relative,
            "line": start, "end_line": end, "source": fragment, "hash": digest(fragment),
            "docstring": doc, "is_test": bool({'test','tests'}.intersection(Path(relative).parts)) or Path(relative).name.startswith("test_") or Path(relative).name.endswith('_test.py'),
            "metrics": {"cc": cc.get((start, getattr(node, "name", ""))) if kind in {"function", "method"} else None,
                        "lines": end - start + 1, "statements": facts.statements,
                        "nesting": facts.max_depth, "parameters": len(params),
                        "annotated_parameters": typed, "return_annotation": returns,
                        "raises": facts.raises, "asserts": facts.asserts,
                        "has_docstring": bool(doc), "calls": facts.calls,
                        "exception_handlers": facts.handlers, "broad_exception_handlers": facts.broad_handlers,
                        "logging_candidates": facts.logging_candidates,
                        "global_declarations": sorted(set(facts.globals)), "effect_candidates": facts.effects[:40]},
            "coverage": None, "assessment": None,
        })
        for child in ast.iter_child_nodes(node):
            visit_child(child, qualname if kind != "module" else "", identifier, kind)

    def visit_child(child, prefix, parent, parent_kind):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = f"{prefix}.{child.name}" if prefix else child.name
            kind = "class" if isinstance(child, ast.ClassDef) else "method" if parent_kind == "class" else "function"
            add(child, name, kind, parent)
        else:
            for nested in ast.iter_child_nodes(child):
                visit_child(nested, prefix, parent, parent_kind)

    add(tree, mod, "module", None)
    attach_calls(tree, nodes)
    return nodes


def attach_calls(tree, nodes):
    """Conservative same-file lexical name resolution, not a runtime call graph.

    Unknown attributes/aliases and names with competing bindings are left unresolved.
    Only bodies are visited: decorators/defaults are not calls made by the function.
    """
    definitions = {(n['line'], n['name']): n for n in nodes if n['kind'] != 'module'}
    scopes = {}

    class Body(ast.NodeVisitor):
        def __init__(self):
            self.bindings, self.calls, self.directives = {}, [], set()

        def bind(self, name, target=None):
            self.bindings.setdefault(name, []).append(target)

        def visit_FunctionDef(self, node):
            self.bind(node.name, definitions.get((node.lineno, node.name)))

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_ClassDef(self, node):
            self.bind(node.name)

        def visit_Lambda(self, node):
            pass

        def visit_Name(self, node):
            if isinstance(node.ctx, (ast.Store, ast.Del)):
                self.bind(node.id)

        def visit_Import(self, node):
            for alias in node.names:
                self.bind(alias.asname or alias.name.split('.')[0])

        def visit_ImportFrom(self, node):
            for alias in node.names:
                self.bind(alias.asname or alias.name)

        def visit_ExceptHandler(self, node):
            if node.name:
                self.bind(node.name)
            self.generic_visit(node)

        def visit_MatchAs(self, node):
            if node.name:
                self.bind(node.name)
            self.generic_visit(node)

        visit_MatchStar = visit_MatchAs

        def visit_MatchMapping(self, node):
            if node.rest:
                self.bind(node.rest)
            self.generic_visit(node)

        def visit_Global(self, node):
            self.directives.update(node.names)

        visit_Nonlocal = visit_Global

        def visit_Call(self, node):
            self.calls.append(node)
            self.generic_visit(node)

    for syntax in ast.walk(tree):
        if not isinstance(syntax, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        component = nodes[0] if isinstance(syntax, ast.Module) else definitions[(syntax.lineno, syntax.name)]
        facts = Body()
        if isinstance(syntax, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for arg in syntax.args.posonlyargs + syntax.args.args + syntax.args.kwonlyargs + [a for a in (syntax.args.vararg, syntax.args.kwarg) if a]:
                facts.bind(arg.arg)
        for statement in syntax.body:
            facts.visit(statement)
        scopes[component['id']] = (component, facts)

    def resolve(name, start):
        scope = start
        while scope in scopes:
            component, facts = scopes[scope]
            if name in facts.directives or '*' in facts.bindings:
                return None
            # A method's bare names do not resolve in the class namespace.
            if component['kind'] != 'class' or scope == start:
                bindings = facts.bindings.get(name)
                if bindings is not None:
                    return bindings[0] if len(bindings) == 1 else None
            scope = component['parent']
        return None

    for component, facts in scopes.values():
        edges, unresolved = {}, 0
        for call in facts.calls:
            target = resolve(call.func.id, component['id']) if isinstance(call.func, ast.Name) else None
            if target is None:
                unresolved += 1
                continue
            edge = edges.setdefault(target['id'], {'source': component['id'], 'target': target['id'],
                'kind': 'call', 'resolution': 'static_name', 'lines': []})
            edge['lines'].append(call.lineno)
        component['call_edges'] = list(edges.values())
        component['metrics']['local_calls_resolved'] = sum(len(e['lines']) for e in edges.values())
        component['metrics']['calls_unresolved'] = unresolved


def enrich_metrics(nodes, edges, cycles):
    """Deterministic evidence only. Aggregate disjoint AST scopes, never their source ranges."""
    by_id = {n['id']: n for n in nodes}
    children = {}
    for n in nodes:
        children.setdefault(n['parent'], []).append(n)
    for node in nodes:
        kind, metrics = node['kind'], node['metrics']
        if kind == 'package':
            scopes = [n for n in nodes if n['kind'] != 'package' and n['path'].startswith(node['path'] + '/')]
        else:
            scopes, stack = [], [node]
            while stack:
                current = stack.pop()
                scopes.append(current)
                stack.extend(children.get(current['id'], []))
        functions = [n for n in scopes if n['kind'] in {'function','method'}]
        modules = {n['id'] for n in scopes if n['kind'] == 'module'}
        total_params = sum(n['metrics']['parameters'] for n in functions)
        typed_params = sum(n['metrics']['annotated_parameters'] for n in functions)
        summary = {
            'scope': 'component_and_descendants', 'functions': len(functions),
            'classes': sum(n['kind'] == 'class' for n in scopes),
            'documented_functions': sum(n['metrics']['has_docstring'] for n in functions),
            'parameters': total_params, 'annotated_parameters': typed_params,
            'parameter_annotation_percent': round(100 * typed_params / total_params, 1) if total_params else None,
            'return_annotations': sum(n['metrics']['return_annotation'] for n in functions),
            'max_cc': max((n['metrics']['cc'] for n in functions if n['metrics']['cc'] is not None), default=None),
            'max_nesting': max((n['metrics']['nesting'] for n in scopes), default=0),
        }
        for key in ('statements','calls','asserts','raises','exception_handlers','broad_exception_handlers','logging_candidates'):
            summary[key] = sum(n['metrics'][key] for n in scopes)
        summary['global_declarations'] = sum(len(n['metrics']['global_declarations']) for n in scopes)
        metrics['aggregate'] = summary
        metrics['measurement'] = {'method': 'static_ast_and_import_graph', 'analyzer_version': VERSION,
                                  'executes_project': False, 'uses_model': False}
        if kind in {'module','package'}:
            outgoing = {e['target'] for e in edges if e['source'] in modules and e['target'] not in modules and e['internal']}
            incoming = {e['source'] for e in edges if e['target'] in modules and e['source'] not in modules and e['internal']}
            metrics.update(functions=len(functions), max_cc=summary['max_cc'], fan_out=len(outgoing), fan_in=len(incoming),
                           external_dependencies=len({e['target'] for e in edges if e['source'] in modules and not e['internal']}),
                           test_importers=sum(by_id[i]['is_test'] for i in incoming),
                           test_modules=sum(by_id[i]['is_test'] for i in modules),
                           cyclic_modules=len(modules.intersection(n for cycle in cycles for n in cycle)))
        else:
            # No per-function dependency counts: the import graph belongs to modules.
            metrics['module_dependency_scope'] = node['module_id']


def import_edges(tree, mod, is_package):
    found = []

    def walk(node, context="runtime"):
        if isinstance(node, ast.If) and ast.unparse(node.test) in {"TYPE_CHECKING", "typing.TYPE_CHECKING"}:
            for child in node.body:
                walk(child, "typing")
            for child in node.orelse:
                walk(child, context)
            return
        if isinstance(node, ast.Try):
            context = "conditional"
        if isinstance(node, ast.Import):
            found.extend({"target": alias.name, "line": node.lineno, "context": context} for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                package = mod.split(".") if is_package else mod.split(".")[:-1]
                up = node.level - 1
                package = package[:len(package) - up] if up <= len(package) else []
                base = ".".join(package + ([base] if base else []))
            for alias in node.names:
                found.append({"target": ".".join(filter(None, [base, alias.name])), "base": base, "line": node.lineno, "context": context})
        for child in ast.iter_child_nodes(node):
            walk(child, context)

    walk(tree)
    return found


def cycles_for(module_ids, edges):
    """Iterative Kosaraju; excludes typing and conditional import edges."""
    graph = {key: set() for key in module_ids}
    reverse = {key: set() for key in module_ids}
    for edge in edges:
        if edge["internal"] and edge["context"] == "runtime":
            graph[edge["source"]].add(edge["target"])
            reverse[edge["target"]].add(edge["source"])
    visited, order = set(), []
    for root in graph:
        stack = [(root, False)]
        while stack:
            key, done = stack.pop()
            if done:
                order.append(key)
            elif key not in visited:
                visited.add(key)
                stack.append((key, True))
                stack.extend((other, False) for other in sorted(graph[key]) if other not in visited)
    visited, cycles = set(), []
    for root in reversed(order):
        if root in visited:
            continue
        group, stack = [], [root]
        while stack:
            key = stack.pop()
            if key not in visited:
                visited.add(key)
                group.append(key)
                stack.extend(reverse[key] - visited)
        if len(group) > 1:
            cycles.append(sorted(group))
    return cycles


def analyze(root_path, scope=None):
    root = Path(root_path).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Selecciona una carpeta de proyecto.")
    initial_stamp = disk_stamp(root, scope)
    nodes, pending, warnings, files, docs = [], [], [], [], []
    total_bytes = 0
    stop = False
    for folder, dirs, names in scoped_walk(root, scope):
        for name in sorted(names):
            path = Path(folder) / name
            if path.is_symlink() or not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            if name.lower().endswith(".md") and len(docs) < 100 and path.stat().st_size <= 100_000:
                content = path.read_text(encoding="utf-8", errors="replace")
                docs.append({"path": relative, "text": content[:12_000], "truncated": len(content) > 12_000, "hash": digest(content)})
            if path.suffix != ".py":
                continue
            if len(files) >= MAX_FILES or total_bytes >= MAX_TOTAL_BYTES:
                warnings.append("Límite de análisis alcanzado; selecciona un subproyecto para completar la inspección.")
                stop = True
                break
            size = path.stat().st_size
            if size > MAX_FILE_BYTES:
                warnings.append(f"Omitido por tamaño: {relative}")
                continue
            total_bytes += size
            try:
                source = read_source(path)
                tree = ast.parse(source, filename=relative)
                file_nodes = components_for(path, relative, source, tree)
                nodes.extend(file_nodes)
                pending.extend(dict(edge, source=relative) for edge in import_edges(tree, module_name(relative), name == "__init__.py"))
                files.append({"path": relative, "hash": digest(source), "bytes": size})
            except (SyntaxError, UnicodeError, OSError, ValueError, RecursionError) as exc:
                warnings.append(f"No analizado: {relative}: {type(exc).__name__}: {str(exc)[:180]}")
        if stop:
            break
    if not nodes:
        raise ValueError("No se encontraron archivos Python analizables. " + " ".join(warnings[:3]))
    edges, cycles = build_graph(nodes, pending)
    fingerprint = digest({"files": files, "docs": [{"path": d["path"], "hash": d["hash"]} for d in docs], "version": VERSION})
    final_stamp = disk_stamp(root, scope)
    if initial_stamp != final_stamp:
        raise ValueError("Los archivos cambiaron durante el análisis. Vuelve a analizar cuando termine la escritura.")
    origin = None
    manifest = root / '.codechecker-snapshot.json'
    if manifest.is_file():
        metadata = json.loads(manifest.read_text(encoding='utf-8'))
        origin = {key: metadata.get(key) for key in ('kind', 'host', 'remote_path', 'revision', 'dirty', 'captured_at', 'live', 'scope')}
    return {"id": digest(str(root))[:16], "root": str(root), "name": root.name, "created_at": now(), "fingerprint": fingerprint, "origin": origin,
            "disk_stamp": final_stamp,
            "analyzer_version": VERSION, "nodes": nodes, "edges": edges, "call_edges": [e for n in nodes for e in n.get('call_edges', [])], "cycles": cycles, "files": files, "documents": docs,
            "warnings": warnings, "coverage_reports": [], "runs": [], "history": [],
            "limitations": ["Grafo de imports estáticos; no es un grafo completo de llamadas.",
                            "Llamadas locales resueltas por nombre léxico: no prueban ejecución. Atributos, alias y nombres ambiguos quedan sin resolver; se omiten cuerpos lambda y expresiones de definición.",
                            "Efectos detectados por nombre: candidatos, no hechos confirmados.",
                            "Sin ejecución de tests ni código del proyecto durante el análisis.",
                            "Elif cuenta como un nivel AST; no se calcula Cognitive Complexity de Sonar."]}


def build_graph(nodes, pending):
    modules = {node["qualified_name"]: node["id"] for node in nodes if node["kind"] == "module"}
    edges, seen = [], set()
    for item in pending:
        target = item["target"]
        resolved = None
        candidate = target
        while candidate:
            if candidate in modules:
                resolved = modules[candidate]
                break
            candidate = candidate.rpartition(".")[0]
        target_id = resolved or "external:" + (item.get("base") or target)
        key = (item["source"], target_id, item["context"])
        if target_id == item["source"] or key in seen:
            continue
        seen.add(key)
        edges.append({"source": item["source"], "target": target_id, "internal": bool(resolved), "context": item["context"], "line": item["line"], "import": target})
    cycles = cycles_for(modules.values(), edges)
    for node in nodes:
        if node["kind"] == "module":
            children = [n for n in nodes if n["module_id"] == node["id"] and n["kind"] in {"function", "method"}]
            node["metrics"].update({"functions": len(children), "max_cc": max((n["metrics"]["cc"] or 0 for n in children), default=0),
                                     "fan_out": len({e["target"] for e in edges if e["source"] == node["id"] and e["internal"]}),
                                     "fan_in": len({e["source"] for e in edges if e["target"] == node["id"] and e["internal"]}),
                                     "cycle": next((c for c in cycles if node["id"] in c), [])})
    enrich_metrics(nodes, edges, cycles)
    return edges, cycles


def attach_coverage(project, report, expected_fingerprint):
    if expected_fingerprint != project["fingerprint"]:
        raise ValueError("El informe se está asociando a un análisis diferente. Vuelve a analizar y seleccionar el informe.")
    if not isinstance(report.get("files"), dict):
        raise ValueError("Se necesita un informe JSON de coverage.py con el campo files.")
    if not isinstance(report.get("meta", {}), dict):
        raise ValueError("El campo meta del informe debe ser un objeto.")
    for name, item in report["files"].items():
        if not isinstance(item, dict):
            raise ValueError(f"Entrada de cobertura inválida: {name}")
        for key in ("executed_lines", "missing_lines"):
            if key not in item or not isinstance(item[key], list) or any(type(v) is not int or v < 1 for v in item[key]):
                raise ValueError(f"El informe necesita {key} como lista de líneas positivas en {name}.")
        for key in ("executed_branches", "missing_branches"):
            if not isinstance(item.get(key, []), list) or any(not isinstance(pair, list) or len(pair) != 2 or any(type(v) is not int for v in pair) for pair in item.get(key, [])):
                raise ValueError(f"Ramas inválidas en {name}.")
        if set(item["executed_lines"]) & set(item["missing_lines"]):
            raise ValueError(f"El informe declara líneas cubiertas y ausentes a la vez en {name}.")
    mapped, skipped = 0, []
    root = project["root"].replace("\\", "/").rstrip("/")
    by_path = {n["path"]: n for n in project["nodes"] if n["kind"] == "module"}
    for name, item in report["files"].items():
        key = name.replace("\\", "/")
        if key.lower().startswith(root.lower() + "/"):
            key = key[len(root) + 1:]
        key = key.removeprefix("./")
        if key not in by_path:
            skipped.append(name)
            continue
        executed, missing = set(item.get("executed_lines", [])), set(item.get("missing_lines", []))
        branches = report.get("meta", {}).get("branch_coverage", False)
        for node in project["nodes"]:
            if node["path"] != key:
                continue
            inside = lambda line: node["line"] <= line <= node["end_line"]
            hit = sum(inside(line) for line in executed)
            miss = sum(inside(line) for line in missing)
            b_hit = sum(inside(pair[0]) for pair in item.get("executed_branches", []))
            b_miss = sum(inside(pair[0]) for pair in item.get("missing_branches", []))
            node["coverage"] = {"lines_hit": hit, "lines_total": hit + miss, "percent": round(100 * hit / (hit + miss), 1) if hit + miss else None,
                                "branches_hit": b_hit if branches else None, "branches_total": b_hit + b_miss if branches else None,
                                "basis": "source-range", "provenance": "user-imported", "source_verified": False,
                                "linked_fingerprint": project["fingerprint"]}
            if node.get("assessment"):
                node["assessment"]["stale"] = True
        mapped += 1
    if not mapped:
        raise ValueError("Ninguna ruta del informe coincide con este proyecto. Exporta coverage.json con rutas relativas a su raíz.")
    project["coverage_reports"].append({"at": now(), "files_mapped": mapped, "files_unmapped": skipped, "source_verified": False,
                                       "note": "Asociado por el usuario; coverage.json no demuestra por sí solo la revisión del código."})
    return {"mapped": mapped, "unmapped": skipped}
