"""Strict validation of deep links (``/?project=...&pr=...``).

A deep link is a plain GET URL that any page could make the browser open, so it
only selects an already allowed local Git repository and a comparison; it never
grants access to arbitrary folders. Allowed roots come from
``CODE_CHECKER_DEEP_LINK_ROOTS`` (absolute paths separated by ``os.pathsep``).
Without that variable deep links are disabled. Validation does not run Git or
anything from the project: it only inspects paths.
"""
import os
import re
from pathlib import Path

from .analyzer import digest

ENV = 'CODE_CHECKER_DEEP_LINK_ROOTS'
class Forbidden(Exception):
    """The link points outside what deep links may open."""


KEYS = {'project', 'pr', 'base', 'rev', 'diff', 'impact'}
MAX_PR = 2147483647
PR_RE = re.compile(r'[1-9][0-9]{0,9}')
# Conservative subset of git-check-ref-format: plain branch/tag/sha names only.
REF_RE = re.compile(r'[A-Za-z0-9][A-Za-z0-9._/+-]{0,199}')


def allowed_roots(raw=None):
    raw = os.environ.get(ENV, '') if raw is None else raw
    roots = []
    for item in raw.split(os.pathsep):
        item = item.strip()
        if not item:
            continue
        path = Path(item)
        if not path.is_absolute():
            raise ValueError(f'{ENV} solo admite rutas absolutas.')
        try:
            roots.append(path.resolve(strict=True))
        except OSError:
            continue  # A missing root simply allows nothing.
    return roots


def valid_ref(value, name):
    if (not REF_RE.fullmatch(value) or '..' in value or '//' in value or value.endswith(('/', '.', '.lock'))
            or '/.' in value):
        raise ValueError(f'Parámetro {name} no válido: usa un nombre de rama, etiqueta o commit.')
    return value


def flag(value, name):
    if value not in {'0', '1'}:
        raise ValueError(f'Parámetro {name} no válido: usa 0 o 1.')
    return value == '1'


def project_path(raw, roots):
    if not roots:
        raise Forbidden(f'Los enlaces directos están desactivados. Configura {ENV} con las raíces permitidas.')
    if not raw or len(raw) > 2000 or any(c in raw for c in '\0\r\n'):
        raise ValueError('Parámetro project no válido.')
    path = Path(raw)
    if not path.is_absolute():
        raise ValueError('El parámetro project debe ser una ruta absoluta.')
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        raise ValueError('La carpeta del proyecto no existe en este servidor.') from None
    if not resolved.is_dir():
        raise ValueError('El parámetro project debe ser una carpeta.')
    root = next((r for r in roots if resolved == r or resolved.is_relative_to(r)), None)
    if root is None:
        raise Forbidden('La carpeta no está dentro de las raíces permitidas para enlaces directos.')
    # Inside a Git work tree whose top level is within the allowed root. Paths only, no git process.
    current = resolved
    while True:
        if (current / '.git').exists():
            return resolved
        if current == root:
            break
        current = current.parent
    raise ValueError('La carpeta no es un repositorio Git dentro de las raíces permitidas.')


def parse(items, roots=None):
    """Validate the query items (list of key/value pairs) of a deep link."""
    roots = allowed_roots() if roots is None else roots
    seen = {}
    for key, value in items:
        if key not in KEYS:
            raise ValueError(f'Parámetro desconocido en el enlace: {key[:40]}')
        if key in seen:
            raise ValueError(f'Parámetro repetido en el enlace: {key}')
        seen[key] = value
    if 'project' not in seen:
        raise ValueError('Falta el parámetro project.')
    path = project_path(seen['project'], roots)
    pr = None
    if 'pr' in seen:
        if not PR_RE.fullmatch(seen['pr']) or int(seen['pr']) > MAX_PR:
            raise ValueError('Parámetro pr no válido: debe ser un número entero positivo.')
        pr = int(seen['pr'])
    base = valid_ref(seen['base'], 'base') if 'base' in seen else None
    rev = valid_ref(seen['rev'], 'rev') if 'rev' in seen else None
    if pr is not None and (base or rev):
        raise ValueError('Usa pr o base+rev, no ambos.')
    if (base is None) != (rev is None):
        raise ValueError('La comparación de ramas necesita base y rev.')
    mode = 'pr' if pr is not None else 'branches' if rev else None
    diff = flag(seen['diff'], 'diff') if 'diff' in seen else mode is not None
    impact = flag(seen['impact'], 'impact') if 'impact' in seen else False
    if (diff or impact) and mode is None:
        raise ValueError('diff e impact necesitan pr o base+rev.')
    return {'path': str(path), 'project_id': digest(str(path))[:16], 'mode': mode, 'pr': pr,
            'base': base, 'rev': rev, 'diff': diff, 'impact': impact}
