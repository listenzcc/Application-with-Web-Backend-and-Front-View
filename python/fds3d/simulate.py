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

from fds.simulate import (
    SPEC_ID_BY_GAS_NAME,
    SPEC_ID_OPTIONS,
    guess_spec_id,
    _clamp,
    _fds_id,
    _fk,
    _num,
    _snap_span,
    assert_within_domain,
)

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


def _mk_chid(session: str) -> str:
    """把 session 压成 FDS 能接受的 CHID（只留字母数字）。"""
    flat = re.sub(r'[^0-9a-zA-Z]', '', session)
    return ('fds3d' + flat)[:30]


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


def render_fds3d(template_text: str, cfg: dict, sensors: list,
                 session: str) -> str:
    """把 template3d.fds 里的占位符填成一次具体模拟的输入文件。

    几何部分跟二维版本完全一套做法（传感器吸到网格面、六面墙、DEVC），
    区别只有体数据输出：DUMP 里 DT_PL3D 用「体数据输出间隔」，
    这样一次模拟能落好几帧体数据给前端做动画。
    """
    chid = _mk_chid(session)
    spec_id = str(cfg.get('spec_id') or '').strip()
    if not spec_id:
        raise ValueError('FDS 组分名 (SPEC_ID) 不能为空。')

    t_end = _num(cfg.get('t_end'), 20.0)
    dt = _num(cfg.get('dt'), 0.5)
    dt_pl3d = _num(cfg.get('dt_pl3d'), 2.0)
    slice_z = _num(cfg.get('slice_z'), 1.5)

    if t_end <= 0:
        raise ValueError('模拟时长 T_END 必须大于 0。')
    if dt <= 0:
        raise ValueError('DEVC/SLCF 输出间隔必须大于 0。')
    if dt_pl3d <= 0:
        raise ValueError('体数据输出间隔必须大于 0。')

    n_vol = int(t_end / dt_pl3d) + 1
    if n_vol > MAX_VOLUME_FRAMES:
        raise ValueError(
            f'模拟时长 {t_end}s / 体数据间隔 {dt_pl3d}s 会产出 {n_vol} 帧体数据，'
            f'超过上限 {MAX_VOLUME_FRAMES}，请调大间隔或缩短时长。')

    xb = list(cfg['xb'])
    ijk = list(cfg['ijk'])
    if len(xb) != 6:
        raise ValueError('计算域 XB 需要 6 个数。')
    if len(ijk) != 3:
        raise ValueError('网格数 IJK 需要 3 个数。')

    x0, x1, y0, y1, z0, z1 = [_num(e) for e in xb]
    nx, ny, nz = [max(1, int(_num(e, 1))) for e in ijk]
    if nx * ny * nz > MAX_CELLS:
        raise ValueError(
            f'网格 {nx}×{ny}×{nz} = {nx * ny * nz} 格，超过上限 {MAX_CELLS}。'
            f'三维体数据每格都要落盘，请把网格调粗一些。')

    dx = (x1 - x0) / nx
    dy = (y1 - y0) / ny
    dz = (z1 - z0) / nz

    # 切片高度吸附到某一层的中心
    k = int(_clamp((slice_z - z0) / dz, 0, nz - 1))
    slice_z = z0 + (k + 0.5) * dz

    # ---- 传感器 -> SURF / OBST / VENT ----
    surfs, obsts, source_vents = [], [], []

    def span(origin, size, i, j):
        return f'{_fk(origin + i * size)},{_fk(origin + j * size)}'

    for sensor in sensors or []:
        value = sensor.get('value')
        if value is None:
            continue

        sx = _clamp(x0 + _num(sensor.get('x_position')) * (x1 - x0), x0, x1)
        sy = _clamp(y0 + _num(sensor.get('y_position')) * (y1 - y0), y0, y1)
        mass_flux = _num(value) * 10

        sid = _fds_id(sensor.get('sensor_id'), 'Sensor')
        name = re.sub(r'\s+', '_', sid)

        surfs.append(
            f"&SURF ID='{name}_SURF',\n"
            f"      COLOR='RED',\n"
            f"      MASS_FLUX={_fk(mass_flux)},\n"
            f"      SPEC_ID='{spec_id}',\n"
            f"      TAU_MF=1.0/"
        )

        ox = _snap_span(sx - 0.3, sx, x0, dx, nx)
        oy = _snap_span(sy - 0.1, sy + 0.4, y0, dy, ny)
        oz1 = int(_clamp(round((min(2.0, z1) - z0) / dz), 1, nz))
        if ox[1] > ox[0] and oy[1] > oy[0]:
            obsts.append(
                f"&OBST ID='Obst #{name}',\n"
                f"      XB={span(x0, dx, *ox)},{span(y0, dy, *oy)},"
                f"{_fk(z0)},{_fk(z0 + oz1 * dz)},\n"
                f"      SURF_ID='CONVERTER_SURF'/"
            )

        # 泄漏面贴在障碍物朝 +x 的面上
        vy = _snap_span(sy, sy + 0.3, y0, dy, ny)
        if ox[1] > ox[0] and vy[1] > vy[0]:
            vx = x0 + ox[1] * dx
            source_vents.append(
                f"&VENT ID='Vent #{name}',\n"
                f"      SURF_ID='{name}_SURF',\n"
                f"      XB={_fk(vx)},{_fk(vx)},{span(y0, dy, *vy)},"
                f"{_fk(z0 + k * dz)},{_fk(z0 + (k + 1) * dz)}/"
            )

    # ---- 用户自定义障碍物 ----
    for i, obst in enumerate(cfg.get('obstacles') or []):
        ob = list(obst.get('xb') or [])
        if len(ob) != 6:
            continue
        bx = _snap_span(_num(ob[0]), _num(ob[1]), x0, dx, nx)
        by = _snap_span(_num(ob[2]), _num(ob[3]), y0, dy, ny)
        bz = _snap_span(_num(ob[4]), _num(ob[5]), z0, dz, nz)
        if bx[1] <= bx[0] or by[1] <= by[0] or bz[1] <= bz[0]:
            continue
        obsts.append(
            f"&OBST ID='{_fds_id(obst.get('id'), f'Obst {i + 1}')}',\n"
            f"      XB={span(x0, dx, *bx)},{span(y0, dy, *by)},"
            f"{span(z0, dz, *bz)},\n"
            f"      SURF_ID='{_fds_id(obst.get('surf_id') or 'CONVERTER_SURF')}'/"
        )

    # ---- 计算域六面 ----
    walls = [
        f"&VENT ID='WALL_XMIN_SUPPLY',\n"
        f"      SURF_ID='Supply',\n"
        f"      XB={_fk(x0)},{_fk(x0)},{_fk(y0)},{_fk(y1)},{_fk(z0)},{_fk(z1)}/",
        f"&VENT ID='WALL_XMAX_OPEN',\n"
        f"      SURF_ID='OPEN',\n"
        f"      XB={_fk(x1)},{_fk(x1)},{_fk(y0)},{_fk(y1)},{_fk(z0)},{_fk(z1)}/",
        f"&VENT ID='WALL_YMIN_OPEN',\n"
        f"      SURF_ID='OPEN',\n"
        f"      XB={_fk(x0)},{_fk(x1)},{_fk(y0)},{_fk(y0)},{_fk(z0)},{_fk(z1)}/",
        f"&VENT ID='WALL_YMAX_OPEN',\n"
        f"      SURF_ID='OPEN',\n"
        f"      XB={_fk(x0)},{_fk(x1)},{_fk(y1)},{_fk(y1)},{_fk(z0)},{_fk(z1)}/",
        f"&VENT ID='WALL_ZMIN_CLOSED',\n"
        f"      SURF_ID='WALL_SURF',\n"
        f"      XB={_fk(x0)},{_fk(x1)},{_fk(y0)},{_fk(y1)},{_fk(z0)},{_fk(z0)}/",
        f"&VENT ID='WALL_ZMAX_OPEN',\n"
        f"      SURF_ID='OPEN',\n"
        f"      XB={_fk(x0)},{_fk(x1)},{_fk(y0)},{_fk(y1)},{_fk(z1)},{_fk(z1)}/",
    ]

    assert_within_domain(obsts + source_vents + walls,
                         [x0, x1, y0, y1, z0, z1], '障碍物/通风口')

    # ---- 检测点 ----
    devices = []
    for i, dev in enumerate(cfg.get('devices') or []):
        dx_ = _clamp(_num(dev.get('x'), 1.0), x0, x1)
        dy_ = _clamp(_num(dev.get('y'), 1.0), y0, y1)
        dz_ = _clamp(_num(dev.get('z'), slice_z), z0, z1)
        devices.append(
            f"&DEVC ID='{_fds_id(dev.get('id'), f'DEVC {i + 1}')}',\n"
            f"      QUANTITY='VOLUME FRACTION',\n"
            f"      SPEC_ID='{spec_id}',\n"
            f"      XYZ={_fk(dx_)},{_fk(dy_)},{_fk(dz_)}/"
        )

    # ---- 切片：三维主体是体数据，这里只留一张气体切片便于对照 ----
    slices = [
        f"&SLCF QUANTITY='VOLUME FRACTION',\n"
        f"      SPEC_ID='{spec_id}',\n"
        f"      PBZ={_fk(slice_z)}/"
    ]
    if cfg.get('velocity_slice'):
        slices.append(
            f"&SLCF QUANTITY='VELOCITY',\n"
            f"      VECTOR=.TRUE.,\n"
            f"      PBZ={_fk(slice_z)}/"
        )

    mesh = (f"&MESH ID='Mesh01', IJK={nx},{ny},{nz}, "
            f"XB={_fk(x0)},{_fk(x1)},{_fk(y0)},{_fk(y1)},{_fk(z0)},{_fk(z1)}/")

    replacements = {
        '{{CHID}}': chid,
        '{{SESSION}}': session,
        '{{GENERATED_AT}}': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        '{{TITLE}}': _fds_id(cfg.get('title') or f'ForceProject3D {session}'),
        '{{T_END}}': _fk(t_end),
        '{{DT_DEVC}}': _fk(dt),
        '{{DT_SLCF}}': _fk(dt),
        '{{DT_BNDF}}': _fk(dt * 2),
        '{{DT_PL3D}}': _fk(dt_pl3d),
        '{{DT_RESTART}}': _fk(t_end + 1),
        '{{SPEC_ID}}': spec_id,
        '{{MESH}}': mesh,
        '{{SPEC}}': str(cfg.get('extra_spec') or '').strip(),
        '{{DEVC}}': '\n'.join(devices),
        '{{SURF}}': '\n'.join(surfs),
        '{{OBST}}': '\n'.join(obsts),
        '{{VENT}}': '\n'.join(walls + source_vents),
        '{{SLCF}}': '\n'.join(slices),
    }

    text = template_text
    for key, value in replacements.items():
        text = text.replace(key, str(value))

    leftovers = re.findall(r'\{\{[A-Z_]+\}\}', text)
    if leftovers:
        raise ValueError(f'template3d.fds 里有没填的占位符: {leftovers}')

    # 吸附后的真实值写回配置，落盘后前端读到的和跑的一致
    cfg['slice_z'] = round(slice_z, 6)
    cfg['ijk'] = [nx, ny, nz]
    cfg['xb'] = [x0, x1, y0, y1, z0, z1]
    cfg['n_volume_frames'] = n_vol
    cfg['cells'] = nx * ny * nz

    return text


def simulate_with_fds3d(sensors: list, config: dict = None) -> str:
    """渲染输入文件、开跑 FDS 三维流程，返回 session。

    流程（run3d.ps1）：fds -> fds2ascii(PL3D) -> 体数据二进制。
    函数本身不等它跑完，run3d.ps1 结束时写 success / failed 标记。
    """
    session = mk_fds3d_session()
    cfg = merge_config(config)

    # 先把输入文件渲染好，配置不合法就直接抛错，不留下半个空目录
    template_text = TEMPLATE_PATH.read_text(encoding='utf-8')
    fds_text = render_fds3d(template_text, cfg, sensors, session)

    dst = SIMULATION_DIR / session
    dst.mkdir(parents=True, exist_ok=True)

    (dst / FDS_INPUT_NAME).write_text(fds_text, encoding='utf-8')
    (dst / SENSORS_NAME).write_text(
        json.dumps(sensors or [], ensure_ascii=False, indent=2),
        encoding='utf-8')
    (dst / CONFIG_NAME).write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')

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


# %% ---- 2026-09-15 ------------------------
# Play ground

if __name__ == '__main__':
    print(mk_fds3d_session())
    print('fds bin:', fds_bin_dir() or '(not found)')
    print(json.dumps(list_fds3d_simulations(), ensure_ascii=False, indent=2))


# %% ---- 2026-09-15 ------------------------
# Pending
