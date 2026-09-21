"""
File: simulate.py
Author: Chuncheng Zhang
Date: 2026-09-15

Purpose:
    用 FDS 跑三维（体积）扩散模拟。

    跟二维版本（python/fds/simulate.py）是一套逻辑、两套产物：
    二维只要某高度的切片（SLCF），三维要整个计算域的体数据（PL3D）。
    一次模拟 = fds3d/simulation/<session>/ 一个目录，session 为
    `YYYY-MM-DD-HH-MM-SS-<uuid>`，目录里放齐这次模拟的全部产物，
    跑完（或失败）后由 fds3d/run3d.ps1 落 success / failed 标记文件。

    几何（传感器 -> SURF/OBST/VENT、六面墙、DEVC、SLCF）的拼装直接复用
    二维那边的助手函数，省得两份实现慢慢漂开。

Functions:
    1. Requirements and constants
    2. Function and class
    3. Play ground
    4. Pending
"""


# %% ---- 2026-09-15 ------------------------
# Requirements and constants
import re
import sys
import json
import uuid
import subprocess

from datetime import datetime
from pathlib import Path

from fds.parse_fds import parse_fds_environment, read_devc_series


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FDS3D_DIR = PROJECT_ROOT / 'fds3d'
SIMULATION_DIR = FDS3D_DIR / 'simulation'
TEMPLATE_PATH = FDS3D_DIR / 'template3d.fds'
RUN_SCRIPT = FDS3D_DIR / 'run3d.ps1'

# 渲染后的输入文件在模拟目录里的固定名字
FDS_INPUT_NAME = 'template3d.fds'
CONFIG_NAME = 'config.json'
SENSORS_NAME = 'sensors.json'
SUCCESS_MARKER = 'success'
FAILED_MARKER = 'failed'
FRAMES_NAME = 'frames.json'

# 体数据产物：volume/frame_000.bin（uint8，x 最快）+ frames.json
VOLUME_DIR = 'volume'
P3D_DIR = 'p3d'          # fds2ascii 导出的体积文本，转完就删

#: 体数据的物理量。跟二维页面的「浓度」是同一个量（CO 体积分数）
VOLUME_QUANTITY = 'VOLUME FRACTION'

#: 一次模拟最多允许多少个体数据帧，PL3D 每帧都是几十 MB 的文本
MAX_VOLUME_FRAMES = 60

#: 网格上限。三维体数据的文本是 每格 ~105 字节，格子太多磁盘和内存都顶不住
MAX_CELLS = 1_500_000

#: FDS 可执行文件所在目录，用来给 fds2ascii 找 DLL
FDS_BIN_CANDIDATES = [
    Path(r'C:\Program Files\firemodels\FDS6\bin'),
    Path(r'C:\Program Files (x86)\firemodels\FDS6\bin'),
]

DEFAULT_XB = [0.0, 10.0, 0.0, 10.0, 0.0, 3.0]
DEFAULT_IJK = [60, 60, 20]

DEFAULT_CONFIG = {
    'gas_name': '',
    'spec_id': 'CO',
    'title': '',
    't_end': 20.0,
    'dt': 0.5,            # DEVC / SLCF 输出间隔
    'dt_pl3d': 2.0,       # 体数据输出间隔，决定动画帧数
    'slice_z': 1.5,
    'ijk': list(DEFAULT_IJK),
    'xb': list(DEFAULT_XB),
    'devices': [
        {'id': 'CO_NEAR_LEAK', 'x': 1.3, 'y': 4.5, 'z': 1.5},
    ],
    'obstacles': [],
    'extra_spec': '',
    'velocity_slice': False,
    'v_min': 0.0,
    'v_max': None,
    # 危险区阈值（体积分数）。跟二维一样，只是「看结果」的参数
    'lvl1': None,
    'lvl2': None,
    # 体积文本（每帧几十 MB）转完就删，.q 原始文件留着
    'keep_p3d_txt': False,
}

# 供 subprocess 写日志用，避免文件对象被 GC 提前关掉
_OPEN_LOGS = []


# %% ---- 2026-09-15 ------------------------
# Function and class


def mk_fds3d_session() -> str:
    """生成 `YYYY-MM-DD-HH-MM-SS-<uuid>` 形式的会话 ID。"""
    now = datetime.now()
    return '-'.join([now.strftime('%Y-%m-%d-%H-%M-%S'), str(uuid.uuid4())])


def _parse_dt_pl3d(text: str):
    """从 &DUMP 里取 DT_PL3D，没有返回 None。"""
    from fds.parse_fds import iter_namelists, parse_namelist
    for name, body in iter_namelists(text):
        if name != 'DUMP':
            continue
        vals = parse_namelist(body).get('DT_PL3D')
        if vals:
            try:
                return float(vals[0])
            except (TypeError, ValueError):
                return None
    return None


def _spawn_run3d(dst: Path):
    """后台拉起 run3d.ps1：fds -> fds2ascii -> 体数据 -> 标记文件。"""
    stdout = open(dst / 'stdout.txt', 'w', encoding='utf-8', errors='replace')
    stderr = open(dst / 'stderr.txt', 'w', encoding='utf-8', errors='replace')
    _OPEN_LOGS.extend([stdout, stderr])

    cmd = (
        f'cd /d "{FDS3D_DIR}" && powershell -ExecutionPolicy Bypass '
        f'-File "{RUN_SCRIPT}" -folder "{dst}" -filename {FDS_INPUT_NAME} '
        f'-python "{sys.executable}"'
    )

    subprocess.Popen(
        cmd,
        shell=True,
        stdout=stdout,
        stderr=stderr,
        start_new_session=True,
    )


def fds_bin_dir() -> str:
    """本机 FDS bin 目录，找不到返回空串。"""
    for p in FDS_BIN_CANDIDATES:
        if p.is_dir():
            return str(p)
    return ''


def merge_config(config: dict = None) -> dict:
    """把用户配置并到默认值上，None 表示“用默认值”。"""
    return {**DEFAULT_CONFIG,
            **{k: v for k, v in (config or {}).items() if v is not None}}


def get_fds3d_default_template() -> str:
    """编辑器预填用的默认 FDS 文本（template3d.fds 原文）。"""
    if not TEMPLATE_PATH.is_file():
        return ''
    return TEMPLATE_PATH.read_text(encoding='utf-8', errors='replace')


def validate_fds_text(fds_text: str) -> dict:
    """校验用户写的完整 FDS 文本，返回解析摘要；不合法直接抛 ValueError。

    校验项：MESH 可识别且不超网格上限、T_END / DT_PL3D 有效且帧数不超上限、
    SPEC 存在。前端「解析 FDS」和提交模拟共用这一份逻辑。
    """
    text = str(fds_text or '').strip()
    if not text:
        raise ValueError('FDS 输入内容为空，请先在编辑器里粘贴或编写 FDS。')

    env = parse_fds_environment(text)
    mesh = env.get('mesh') or {}
    xb, ijk = mesh.get('xb'), mesh.get('ijk')
    if not xb or not ijk:
        raise ValueError('FDS 里没有可识别的 &MESH（XB/IJK），无法计算。')
    if len(env.get('meshes') or []) > 1:
        raise ValueError('暂只支持单个 &MESH 的输入文件，请合并网格。')

    nx, ny, nz = ijk
    warnings = []
    if nx * ny * nz > MAX_CELLS:
        raise ValueError(
            f'网格 {nx}×{ny}×{nz} = {nx * ny * nz} 格，超过上限 {MAX_CELLS}。'
            f'体数据每格都要落盘导出，请把网格调粗一些。')
    if nx * ny * nz > MAX_CELLS / 2:
        warnings.append(
            f'网格 {nx}×{ny}×{nz} 接近上限，PL3D 导出会比较慢，'
            f'建议单轴不超过 100。')

    t_end = env.get('t_end')
    if not t_end or t_end <= 0:
        raise ValueError('FDS 里没有有效的 &TIME T_END。')

    # DUMP 里的 DT_PL3D 决定体数据帧数
    dt_pl3d = _parse_dt_pl3d(text)
    if not dt_pl3d or dt_pl3d <= 0:
        raise ValueError('FDS 的 &DUMP 里没有有效的 DT_PL3D，无法导出体数据。')

    n_vol = int(t_end / dt_pl3d) + 1
    if n_vol > MAX_VOLUME_FRAMES:
        raise ValueError(
            f'T_END {t_end}s / DT_PL3D {dt_pl3d}s 会产出 {n_vol} 帧体数据，'
            f'超过上限 {MAX_VOLUME_FRAMES}，请调大 DT_PL3D 或缩短 T_END。')

    if not env.get('spec_id'):
        raise ValueError('FDS 里没有 &SPEC 组分定义，无法导出浓度体数据。')

    return {
        'env': env,
        'xb': list(xb),
        'ijk': [int(nx), int(ny), int(nz)],
        't_end': t_end,
        'dt_pl3d': dt_pl3d,
        'n_frames': n_vol,
        'cells': int(nx) * int(ny) * int(nz),
        'warnings': warnings,
    }


def simulate_fds_text(fds_text: str, config: dict = None,
                      sensors: list = None) -> str:
    """直接跑甲方写好的完整 FDS 输入文件，返回 session。

    跟老的 render 流程不同：这里不再往模板里填占位符、也不按传感器
    生成几何，FDS 文本原样落盘执行。MESH / T_END / DT_PL3D / SPEC
    从文本里解析出来做校验，并把真实值写进 config.json，
    后续 p3d2volume / 前端读到的域范围和实际计算一致。
    """
    summary = validate_fds_text(fds_text)
    text = str(fds_text or '').strip()
    env = summary['env']

    session = mk_fds3d_session()
    cfg = merge_config(config)
    # config 记录解析出的真实值，p3d2volume / 前端都以它为准
    cfg.update({
        'spec_id': str(cfg.get('spec_id') or env.get('spec_id')),
        'title': env.get('title') or cfg.get('title') or '',
        't_end': summary['t_end'],
        'dt_pl3d': summary['dt_pl3d'],
        'xb': summary['xb'],
        'ijk': summary['ijk'],
        'n_volume_frames': summary['n_frames'],
        'cells': summary['cells'],
    })

    dst = SIMULATION_DIR / session
    dst.mkdir(parents=True, exist_ok=True)

    (dst / FDS_INPUT_NAME).write_text(text, encoding='utf-8')
    (dst / SENSORS_NAME).write_text(
        json.dumps(sensors or [], ensure_ascii=False, indent=2),
        encoding='utf-8')
    (dst / CONFIG_NAME).write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')

    _spawn_run3d(dst)
    return session


def simulation_status(session_dir: Path) -> str:
    """success / failed / pending。"""
    session_dir = Path(session_dir)
    if (session_dir / SUCCESS_MARKER).exists():
        return 'success'
    if (session_dir / FAILED_MARKER).exists():
        return 'failed'
    return 'pending'


def _read_marker(path: Path) -> str:
    try:
        return path.read_text(encoding='utf-8', errors='replace').strip()
    except OSError:
        return ''


def simulation_dir(session: str) -> Path:
    """只允许访问 simulation 目录下的直接子目录，挡掉路径穿越。"""
    session = str(session or '').strip()
    if not session or '/' in session or '\\' in session or '..' in session:
        return SIMULATION_DIR / '__invalid__'
    return SIMULATION_DIR / session


def volume_path(session: str, name: str) -> Path:
    """体数据文件路径。只允许 volume/ 下的 .bin 文件。"""
    name = str(name or '').strip()
    if not name or '/' in name or '\\' in name or '..' in name:
        return None
    if not name.lower().endswith('.bin'):
        return None
    return simulation_dir(session) / VOLUME_DIR / name


def _read_frames_meta(d: Path) -> dict:
    """frames.json 里的元信息：frames / n_frames / v_min / v_max / ijk / xb。"""
    p = d / FRAMES_NAME
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def list_fds3d_simulations() -> list:
    """按时间倒序列出全部三维模拟目录及其状态。

    v_min / v_max 也带出来：选历史结果时先让用户看到这场算出来的量程。
    """
    if not SIMULATION_DIR.is_dir():
        return []

    out = []
    for d in sorted(SIMULATION_DIR.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        status = simulation_status(d)
        meta = _read_frames_meta(d)
        n_frames = len(meta.get('frames') or [])
        if not n_frames:
            vol = d / VOLUME_DIR
            if vol.is_dir():
                n_frames = sum(1 for f in vol.iterdir()
                               if f.suffix.lower() == '.bin')
        out.append({
            'session': d.name,
            'status': status,
            'n_frames': n_frames,
            'v_min': meta.get('v_min'),
            'v_max': meta.get('v_max'),
            'created': d.stat().st_mtime,
            'note': _read_marker(d / (FAILED_MARKER if status == 'failed'
                                      else SUCCESS_MARKER)),
        })
    return out


def get_fds3d_simulation_result_history() -> list:
    """已经跑成功的会话 ID 列表（历史下拉用）。"""
    return [e['session'] for e in list_fds3d_simulations()
            if e['status'] == 'success']


def get_fds3d_simulation_template(session: str) -> str:
    """取回该次模拟实际用的 template3d.fds 原文。"""
    p = simulation_dir(session) / FDS_INPUT_NAME
    if not p.is_file():
        return ''
    return p.read_text(encoding='utf-8', errors='replace')


def get_fds3d_simulation_result(session: str) -> dict:
    """一次三维模拟的完整状态：状态、帧、体网格、环境、配置、检测点读数。"""
    d = simulation_dir(session)

    result = {
        'session': session,
        'exists': d.is_dir(),
        'status': 'missing',
        'note': '',
        'files': [],
        'frames': [],
        'n_frames': 0,
        'config': {},
        'environment': {},
        'template_name': FDS_INPUT_NAME,
        'template': '',
        'volume': {},
        'sensors': [],
        'quantity': VOLUME_QUANTITY,
        'v_min': None,
        'v_max': None,
        'devc': {'names': [], 'units': [], 'times': [], 'values': {}},
    }

    if not d.is_dir():
        return result

    result['status'] = simulation_status(d)
    marker = SUCCESS_MARKER if result['status'] == 'success' else FAILED_MARKER
    result['note'] = _read_marker(d / marker)
    result['files'] = sorted([f.name for f in d.iterdir()
                              if f.is_file() and not f.name.startswith('.')
                              and f.name.lower() != 'desktop.ini'])

    cfg = {}
    p = d / CONFIG_NAME
    if p.is_file():
        try:
            cfg = json.loads(p.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            cfg = {}
    result['config'] = cfg

    template_path = d / FDS_INPUT_NAME
    if template_path.is_file():
        text = template_path.read_text(encoding='utf-8', errors='replace')
        result['template'] = text
        result['environment'] = parse_fds_environment(text)
    else:
        result['environment'] = parse_fds_environment('')

    meta = _read_frames_meta(d)
    frames = []
    for i, item in enumerate(meta.get('frames') or []):
        frames.append({
            'index': i,
            'file': item.get('file') or f'frame_{i:03d}.bin',
            'time': item.get('time'),
            'v_min': item.get('v_min'),
            'v_max': item.get('v_max'),
        })
    result['frames'] = frames
    result['n_frames'] = len(frames)
    result['v_min'] = meta.get('v_min')
    result['v_max'] = meta.get('v_max')
    result['volume'] = {
        'ijk': meta.get('ijk'),
        'xb': meta.get('xb') or cfg.get('xb'),
        'quantity': meta.get('quantity') or VOLUME_QUANTITY,
        'units': meta.get('units'),
        'downsample': meta.get('downsample') or 1,
    }

    devc_files = sorted(d.glob('*_devc.csv'))
    if devc_files:
        result['devc'] = read_devc_series(devc_files[0])

    sensors_path = d / SENSORS_NAME
    if sensors_path.is_file():
        try:
            result['sensors'] = json.loads(
                sensors_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            result['sensors'] = []

    return result


def _namelist_spans(text: str, name_upper: str) -> list:
    """返回 text 里所有 `&<name_upper> ... /` 的 (start, end) 字符区间。

    引号里的 '/' 不算结束，跟 FDS 自己读输入卡的规则一致。
    """
    spans = []
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
        if name == name_upper:
            spans.append((i, m + 1))
        i = m + 1
    return spans


def parse_obst_list(fds_text: str) -> list:
    """从 FDS 文本解析 OBST 列表，给页面表格联动用。"""
    env = parse_fds_environment(fds_text or '')
    out = []
    for i, o in enumerate(env.get('obst') or []):
        out.append({
            'id': o.get('id') or f'OBST {i + 1}',
            'xb': o['xb'],
            'surf_id': o.get('surf_id') or 'INERT',
        })
    return out


def replace_obst_namelists(fds_text: str, obsts: list) -> str:
    """把文本里全部 &OBST 块替换成表格生成的版本（表格 -> 文本联动）。

    新块统一插在 &TAIL 之前（没有 TAIL 就追加到末尾），一行一个 OBST，
    保证 FDS 结构合法。表格为空时等于把 OBST 全部清掉。
    """
    text = str(fds_text or '')
    lines = []
    for i, o in enumerate(obsts or []):
        xb = o.get('xb') or []
        if len(xb) != 6:
            continue
        oid = str(o.get('id') or f'OBST {i + 1}').replace("'", '')
        surf = str(o.get('surf_id') or 'INERT').replace("'", '')
        vals = ','.join(f'{float(v):g}' for v in xb)
        lines.append(f"&OBST ID='{oid}', XB={vals}, SURF_ID='{surf}'/")

    out = text
    for s, e in reversed(_namelist_spans(text, 'OBST')):
        out = out[:s] + out[e:]
    out = re.sub(r'\n{3,}', '\n\n', out).rstrip() + '\n'

    if lines:
        block = ('! ========= OBST（由页面 OBST 表格生成）=========\n'
                 + '\n'.join(lines) + '\n')
        tail = out.find('&TAIL')
        if tail >= 0:
            out = out[:tail] + block + '\n' + out[tail:]
        else:
            out = out.rstrip() + '\n\n' + block
    return out


# %% ---- 2026-09-15 ------------------------
# Play ground

if __name__ == '__main__':
    print(mk_fds3d_session())
    print('fds bin:', fds_bin_dir() or '(not found)')
    print(json.dumps(list_fds3d_simulations(), ensure_ascii=False, indent=2))


# %% ---- 2026-09-15 ------------------------
# Pending
