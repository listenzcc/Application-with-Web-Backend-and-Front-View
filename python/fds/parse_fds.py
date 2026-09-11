"""
File: parse_fds.py
Author: Chuncheng Zhang
Date: 2026-09-11

Purpose:
    Parse a (rendered) FDS input file into a plain dict so the front-end can
    draw the environment: mesh domain, obstructions, vents, devices and slices.

Functions:
    1. Requirements and constants
    2. Function and class
    3. Play ground
"""


# %% ---- 2026-09-11 ------------------------
# Requirements and constants
from pathlib import Path
from typing import Any


# %% ---- 2026-09-11 ------------------------
# Function and class


def iter_namelists(text: str):
    """Yield (NAME, body) for every `&NAME ... /` block in the text.

    Text outside a namelist is treated as a comment and ignored, which is how
    FDS itself reads the input file.
    """
    i, n = 0, len(text)
    while i < n:
        if text[i] != '&':
            i += 1
            continue

        j = i + 1
        k = j
        while k < n and (text[k].isalnum() or text[k] in '_-'):
            k += 1
        name = text[j:k].upper()

        m = k
        in_quote = False
        while m < n:
            c = text[m]
            if c == "'":
                in_quote = not in_quote
            elif c == '/' and not in_quote:
                break
            m += 1

        yield name, text[k:m]
        i = m + 1


def _split_top_level(body: str) -> list:
    """Split `body` on commas that are outside quotes and outside parentheses."""
    parts, buf = [], []
    depth, in_quote = 0, False
    for c in body:
        if c == "'":
            in_quote = not in_quote
            buf.append(c)
        elif in_quote:
            buf.append(c)
        elif c == '(':
            depth += 1
            buf.append(c)
        elif c == ')':
            depth -= 1
            buf.append(c)
        elif c == ',' and depth == 0:
            parts.append(''.join(buf))
            buf = []
        else:
            buf.append(c)
    if buf:
        parts.append(''.join(buf))
    return parts


def _normalize(value: str) -> Any:
    """'Methane' -> Methane, '20.0' -> 20.0, '.TRUE.' -> '.TRUE.'."""
    v = value.strip()
    if len(v) >= 2 and v[0] == "'" and v[-1] == "'":
        return v[1:-1]
    try:
        return float(v)
    except ValueError:
        return v


def parse_namelist(body: str) -> dict:
    """Parse `KEY=V1,V2, KEY2=V3` into {KEY: [V1, V2], KEY2: [V3]}.

    Commas after the first value belong to the same key, which mirrors how FDS
    reads array-valued parameters such as XB. Keys carrying an index suffix
    (`MATL_ID(1,1)`) are collapsed onto their base name.
    """
    params: dict = {}
    current = None

    for chunk in _split_top_level(body):
        s = chunk.strip()
        if not s:
            continue

        if '=' in s:
            key, _, raw = s.partition('=')
            base = key.strip().upper().split('(')[0].strip()
            current = base
            params.setdefault(base, []).append(_normalize(raw))
        elif current is not None:
            # continuation of the previous value list, e.g. XB=0.0,10.0,...
            params[current].append(_normalize(s))

    return params


def _first(params: dict, key: str, default=None):
    values = params.get(key)
    if not values:
        return default
    return values[0]


def _number(params: dict, key: str):
    """First value of `key` as a float, or None."""
    vals = params.get(key)
    if not vals:
        return None
    try:
        return float(vals[0])
    except (TypeError, ValueError):
        return None


def _number_list(params: dict, key: str, n: int = None):
    """Whole value list of `key` as floats. Returns None when unusable.

    `XB=0.0,10.0,...` is split into separate chunks while parsing, so the
    values live in the list rather than in the first slot.
    """
    vals = params.get(key)
    if not vals:
        return None
    out = []
    for v in vals:
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            return None
    if n is not None and len(out) != n:
        return None
    return out


def _is_placeholder(value) -> bool:
    return isinstance(value, str) and '{{' in value


def parse_fds_environment(text: str) -> dict:
    """Turn an FDS input file into the environment description used by the UI."""
    env: dict = {
        'chid': None,
        'title': None,
        't_end': None,
        'dt_devc': None,
        'dt_slcf': None,
        'spec_id': None,
        'mesh': {'ijk': None, 'xb': None},
        'meshes': [],
        'domain': None,
        'obst': [],
        'vents': [],
        'devices': [],
        'slices': [],
        'species': [],
    }

    domain_points = []

    for name, body in iter_namelists(text):
        params = parse_namelist(body)

        if name == 'HEAD':
            env['chid'] = _first(params, 'CHID') or env['chid']
            env['title'] = _first(params, 'TITLE') or env['title']

        elif name == 'TIME':
            env['t_end'] = _number(params, 'T_END') or env['t_end']

        elif name == 'DUMP':
            for key in ('DT_DEVC', 'DT_SLCF'):
                v = _number(params, key)
                if v is not None:
                    env[key.lower()] = v

        elif name == 'MESH':
            xb = _number_list(params, 'XB', 6)
            ijk = _number_list(params, 'IJK', 3)
            ijk = [int(e) for e in ijk] if ijk else None
            mesh = {'id': _first(params, 'ID'), 'ijk': ijk, 'xb': xb}
            env['meshes'].append(mesh)
            if env['mesh']['xb'] is None and xb:
                env['mesh'] = {'ijk': ijk, 'xb': xb}
            if xb:
                domain_points.append(xb)

        elif name == 'SPEC':
            sid = _first(params, 'ID')
            if sid and not _is_placeholder(sid):
                env['species'].append(sid)
            if env['spec_id'] is None and sid:
                env['spec_id'] = sid

        elif name == 'OBST' or name == 'OBSTACLE':
            xb = _number_list(params, 'XB', 6)
            if xb:
                env['obst'].append({
                    'id': _first(params, 'ID'),
                    'xb': xb,
                    'surf_id': _first(params, 'SURF_ID'),
                })

        elif name == 'VENT':
            xb = _number_list(params, 'XB', 6)
            if xb:
                env['vents'].append({
                    'id': _first(params, 'ID'),
                    'xb': xb,
                    'surf_id': _first(params, 'SURF_ID'),
                })

        elif name == 'DEVC':
            xyz = _number_list(params, 'XYZ', 3)
            env['devices'].append({
                'id': _first(params, 'ID'),
                'xyz': xyz,
                'quantity': _first(params, 'QUANTITY'),
                'spec_id': _first(params, 'SPEC_ID'),
            })

        elif name == 'SLCF':
            env['slices'].append({
                'quantity': _first(params, 'QUANTITY'),
                'spec_id': _first(params, 'SPEC_ID'),
                'pbz': _number(params, 'PBZ'),
            })

    if domain_points:
        env['domain'] = [
            min(p[0] for p in domain_points),
            max(p[1] for p in domain_points),
            min(p[2] for p in domain_points),
            max(p[3] for p in domain_points),
            min(p[4] for p in domain_points),
            max(p[5] for p in domain_points),
        ]
    elif env['mesh']['xb']:
        env['domain'] = list(env['mesh']['xb'])

    # Drop the devices without a usable position
    env['devices'] = [d for d in env['devices'] if d['xyz']]

    return env


def parse_fds_file(path) -> dict:
    return parse_fds_environment(Path(path).read_text(encoding='utf-8',
                                                      errors='replace'))


def read_devc_series(path) -> dict:
    """Read an FDS `*_devc.csv` into {names, units, times, values}.

    FDS writes the units on the first row and the device names on the second
    row, so the numeric data starts on the third row.
    """
    import csv

    path = Path(path)
    if not path.is_file():
        return {'names': [], 'units': [], 'times': [], 'values': {}}

    with path.open(encoding='utf-8', errors='replace') as f:
        rows = [r for r in csv.reader(f) if r]

    if len(rows) < 3:
        return {'names': [], 'units': [], 'times': [], 'values': {}}

    units = [c.strip().strip('"') for c in rows[0]]
    names = [c.strip().strip('"') for c in rows[1]]

    times, values = [], {name: [] for name in names[1:]}
    for row in rows[2:]:
        try:
            nums = [float(c) for c in row]
        except ValueError:
            continue
        if len(nums) != len(names):
            continue
        times.append(nums[0])
        for name, v in zip(names[1:], nums[1:]):
            values[name].append(v)

    return {'names': names[1:], 'units': units[1:], 'times': times,
            'values': values}


# %% ---- 2026-09-11 ------------------------
# Play ground

if __name__ == '__main__':
    import json
    res = parse_fds_file('fds/template.fds')
    print(json.dumps(res, ensure_ascii=False, indent=2))
