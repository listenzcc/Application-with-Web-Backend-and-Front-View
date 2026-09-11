"""
File: simulate.py
Author: Chuncheng Zhang
Date: 2025-12-27 (rewritten 2026-09-11)

Purpose:
    Simulate with FDS.

    一次模拟 = fds/simulation/<session>/ 一个目录，session 为
    `YYYY-MM-DD-HH-MM-SS-<uuid>`。目录里放齐这次模拟的全部产物，
    跑完（或失败）后由 fds/runme.ps1 落 success / failed 标记文件。

Functions:
    1. Requirements and constants
    2. Function and class
    3. Play ground
    4. Pending
    5. Pending
"""


# %% ---- 2025-12-27 ------------------------
# Requirements and constants
import re
import sys
import json
import uuid
import subprocess

from datetime import datetime
from pathlib import Path

from .parse_fds import parse_fds_environment, parse_fds_file, read_devc_series


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FDS_DIR = PROJECT_ROOT / 'fds'
SIMULATION_DIR = FDS_DIR / 'simulation'
TEMPLATE_PATH = FDS_DIR / 'template.fds'
RUN_SCRIPT = FDS_DIR / 'runme.ps1'

# 渲染后的输入文件在模拟目录里的固定名字，前端要靠它画环境图
FDS_INPUT_NAME = 'template.fds'
CONFIG_NAME = 'config.json'
SENSORS_NAME = 'sensors.json'
SUCCESS_MARKER = 'success'
FAILED_MARKER = 'failed'
FRAMES_NAME = 'frames.json'

# FDS 会写的其它输出名字
GIF_NAME = 'generated.gif'
IMG_DIR = 'img'
OUTPUT_DIR = 'output'

#: 一次模拟最多允许多少帧，避免把 fds2ascii 调用次数打爆
MAX_FRAMES = 400

#: 已在本机 FDS6 上实测可用的预定义组分名，改动前先用 fds.exe 单独跑一遍确认
SPEC_ID_OPTIONS = [
    'CO', 'METHANE', 'HYDROGEN', 'AMMONIA', 'PROPANE', 'ETHYLENE', 'ETHANE',
    'HYDROGEN SULFIDE', 'NITROGEN', 'OXYGEN', 'CARBON DIOXIDE',
    'WATER VAPOR', 'CHLORINE', 'METHANOL', 'PHOSGENE', 'PROPYLENE',
    'ACETYLENE', 'BUTANE', 'SULFUR DIOXIDE', 'HYDROGEN CYANIDE',
    'HYDROGEN CHLORIDE', 'NITROGEN DIOXIDE', 'ACRYLONITRILE', 'BENZENE',
    'FORMALDEHYDE', 'ETHYL ACETATE', 'PROPIONALDEHYDE',
]

#: 气体库中文名 -> FDS 组分名。只做精确匹配，匹配不到就让用户手填
SPEC_ID_BY_GAS_NAME = {
    '一氧化碳': 'CO',
    '甲烷': 'METHANE',
    '天然气': 'METHANE',
    '氢气': 'HYDROGEN',
    '氨': 'AMMONIA',
    '液氨': 'AMMONIA',
    '丙烷': 'PROPANE',
    '乙烯': 'ETHYLENE',
    '乙烷': 'ETHANE',
    '硫化氢': 'HYDROGEN SULFIDE',
    '氮气': 'NITROGEN',
    '氧气': 'OXYGEN',
    '二氧化碳': 'CARBON DIOXIDE',
    '水蒸气': 'WATER VAPOR',
    '氯气': 'CHLORINE',
    '甲醇': 'METHANOL',
    '光气': 'PHOSGENE',
    '丙烯': 'PROPYLENE',
    '乙炔': 'ACETYLENE',
    '丁烷': 'BUTANE',
    '二氧化硫': 'SULFUR DIOXIDE',
    '氰化氢': 'HYDROGEN CYANIDE',
    '氯化氢': 'HYDROGEN CHLORIDE',
    '二氧化氮': 'NITROGEN DIOXIDE',
    '丙烯腈': 'ACRYLONITRILE',
    '苯': 'BENZENE',
    '甲醛': 'FORMALDEHYDE',
    '乙酸乙酯': 'ETHYL ACETATE',
    '丙醛': 'PROPIONALDEHYDE',
}

DEFAULT_XB = [0.0, 10.0, 0.0, 10.0, 0.0, 3.0]
DEFAULT_IJK = [50, 50, 15]

DEFAULT_CONFIG = {
    'gas_name': '',
    'spec_id': 'CO',
    'title': '',
    't_end': 20.0,
    'dt': 0.5,
    'slice_z': 1.5,
    'ijk': list(DEFAULT_IJK),
    'xb': list(DEFAULT_XB),
    'devices': [
        {'id': 'CO_NEAR_LEAK', 'x': 1.3, 'y': 4.5, 'z': 1.5},
    ],
    'obstacles': [],
    'extra_spec': '',
    'velocity_slice': True,
    'v_min': 0.0,
    'v_max': None,
    # 危险区阈值（体积分数）。留空则查看结果时按量程自动取，
    # 这两个值只是「看结果」的参数，不参与 FDS 计算本身。
    'lvl1': None,
    'lvl2': None,
}

# 供 subprocess 写日志用，避免文件对象被 GC 提前关掉
_OPEN_LOGS = []


# %% ---- 2025-12-27 ------------------------
# Function and class


def guess_spec_id(gas_name: str) -> str:
    """按气体库里的中文名猜 FDS 组分名，猜不到返回空串。"""
    if not gas_name:
        return ''
    name = str(gas_name).strip()
    if name in SPEC_ID_BY_GAS_NAME:
        return SPEC_ID_BY_GAS_NAME[name]
    return ''


def mk_fds_session() -> str:
    """生成 `YYYY-MM-DD-HH-MM-SS-<uuid>` 形式的会话 ID。"""
    now = datetime.now()
    return '-'.join([now.strftime('%Y-%m-%d-%H-%M-%S'), str(uuid.uuid4())])


def _mk_chid(session: str) -> str:
    """把 session 压成 FDS 能接受的 CHID（字母数字，长度可控）。"""
    flat = re.sub(r'[^0-9a-zA-Z]', '', session)
    return ('fds' + flat)[:30]


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _num(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _fds_id(text, fallback='ID') -> str:
    """FDS 的 ID 用单引号包着，里头不能再出现单引号。"""
    s = str(text if text not in (None, '') else fallback)
    s = s.replace("'", ' ').strip()
    return s or fallback


def _fk(value) -> str:
    """Format a float for the FDS file."""
    return f'{_num(value):.4f}'.rstrip('0').rstrip('.') or '0'


def assert_within_domain(blocks, bounds, where='几何'):
    """保险丝：几何跑出计算域时 FDS 会静默丢掉那个件，这里先把它炸出来。"""
    x0, x1, y0, y1, z0, z1 = bounds
    tol = 1e-6
    for text in blocks:
        m = re.search(r'XB=([-\d.,eE+]+)', text)
        if not m:
            continue
        vals = [float(v) for v in m.group(1).split(',') if v.strip()]
        if len(vals) != 6:
            continue
        inside = (
            x0 - tol <= vals[0] <= x1 + tol and x0 - tol <= vals[1] <= x1 + tol
            and y0 - tol <= vals[2] <= y1 + tol and y0 - tol <= vals[3] <= y1 + tol
            and z0 - tol <= vals[4] <= z1 + tol and z0 - tol <= vals[5] <= z1 + tol
        )
        if not inside:
            raise ValueError(f'{where}超出计算域: XB={vals}，计算域={bounds}')


def _snap_span(lo_value, hi_value, origin, size, n, min_cells=1):
    """把 [lo, hi] 吸附到网格面，返回格索引 (i, j)，保证 j - i >= min_cells。

    FDS 会把几何吸附到最近的网格面上，跨度不足一格的几何会被压成零面积后丢掉。
    这里提前算好，免得泄漏面（只有 0.2 m 高）在大网格下静默失效。
    """
    if size <= 0 or n <= 0:
        return 0, max(min_cells, 1)
    i = int(round((_num(lo_value) - origin) / size))
    j = int(round((_num(hi_value) - origin) / size))
    i = int(max(0, min(n - min_cells, i)))
    j = int(max(i + min_cells, min(n, j)))
    return i, j


def merge_config(config: dict = None) -> dict:
    """把用户配置并到默认值上，None 表示“用默认值”。"""
    return {**DEFAULT_CONFIG,
            **{k: v for k, v in (config or {}).items() if v is not None}}


def render_fds(template_text: str, cfg: dict, sensors: list,
               session: str) -> str:
    """把 template.fds 里的占位符填成一次具体模拟的输入文件。

    `cfg` 必须是 merge_config() 的结果；函数会把吸附后的真实值
    （slice_z / ijk / xb）写回 cfg，便于一起落盘。
    """
    chid = _mk_chid(session)
    spec_id = str(cfg.get('spec_id') or '').strip()
    if not spec_id:
        raise ValueError('FDS 组分名 (SPEC_ID) 不能为空。')

    t_end = _num(cfg.get('t_end'), 20.0)
    dt = _num(cfg.get('dt'), 0.5)
    slice_z = _num(cfg.get('slice_z'), 1.5)

    if t_end <= 0:
        raise ValueError('模拟时长 T_END 必须大于 0。')
    if dt <= 0:
        raise ValueError('输出时间间隔 DT 必须大于 0。')

    n_frames = int(t_end / dt) + 1
    if n_frames > MAX_FRAMES:
        raise ValueError(
            f'模拟时长 {t_end}s / 间隔 {dt}s 会产出 {n_frames} 帧，'
            f'超过上限 {MAX_FRAMES}，请调大间隔或缩短时长。')

    xb = list(cfg['xb'])
    ijk = list(cfg['ijk'])
    if len(xb) != 6:
        raise ValueError('计算域 XB 需要 6 个数。')
    if len(ijk) != 3:
        raise ValueError('网格数 IJK 需要 3 个数。')

    x0, x1, y0, y1, z0, z1 = [_num(e) for e in xb]
    nx, ny, nz = [max(1, int(_num(e, 1))) for e in ijk]
    dx = (x1 - x0) / nx
    dy = (y1 - y0) / ny
    dz = (z1 - z0) / nz

    # 切片高度吸附到某一层的中心，保证 SLCF 一定落在真实网格层上
    k = int(_clamp((slice_z - z0) / dz, 0, nz - 1))
    slice_z = z0 + (k + 0.5) * dz

    # ---- 传感器 -> SURF / OBST / VENT ----
    # 几何一律吸附到网格面上。泄漏面本身只有 0.2 m 高，
    # 网格粗一点就会被 FDS 吸附成零面积，VENT 直接失效（模拟出来全 0）。
    surfs, obsts, source_vents = [], [], []

    def span(origin, size, i, j):
        """格索引 (i, j) -> '坐标,坐标'。索引和坐标别混用，混用会把几何扔出域外。"""
        return f'{_fk(origin + i * size)},{_fk(origin + j * size)}'

    for sensor in sensors or []:
        value = sensor.get('value')
        if value is None:
            continue

        # 传感器位置是 0~1 归一化坐标，映射到计算域
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

        # 障碍物（传感器底座），画环境图时会以矩形呈现
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

        # 泄漏面贴在障碍物朝向 +x 的面上，高度占切片所在的那一层
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

    # 保险丝：所有几何都必须在计算域内
    assert_within_domain(obsts + source_vents + walls,
                         [x0, x1, y0, y1, z0, z1], '障碍物/通风口')

    # ---- 检测点 ----
    devices = []
    for i, dev in enumerate(cfg.get('devices') or []):
        dx = _clamp(_num(dev.get('x'), 1.0), x0, x1)
        dy = _clamp(_num(dev.get('y'), 1.0), y0, y1)
        dz = _clamp(_num(dev.get('z'), slice_z), z0, z1)
        devices.append(
            f"&DEVC ID='{_fds_id(dev.get('id'), f'DEVC {i + 1}')}',\n"
            f"      QUANTITY='VOLUME FRACTION',\n"
            f"      SPEC_ID='{spec_id}',\n"
            f"      XYZ={_fk(dx)},{_fk(dy)},{_fk(dz)}/"
        )

    # ---- 切片：气体切片必须排在第一个，fds2ascii 按序号 1 取它 ----
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
        '{{TITLE}}': _fds_id(cfg.get('title') or f'ForceProject {session}'),
        '{{T_END}}': _fk(t_end),
        '{{DT_DEVC}}': _fk(dt),
        '{{DT_SLCF}}': _fk(dt),
        '{{DT_BNDF}}': _fk(dt * 2),
        '{{DT_PL3D}}': _fk(t_end),
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
        raise ValueError(f'template.fds 里有没填的占位符: {leftovers}')

    # 把吸附后的真实值写回配置，落盘后前端读到的和跑的一致
    cfg['slice_z'] = round(slice_z, 6)
    cfg['ijk'] = [nx, ny, nz]
    cfg['xb'] = [x0, x1, y0, y1, z0, z1]

    return text


def simulate_with_fds(sensors: list, config: dict = None) -> str:
    """渲染输入文件、开跑 FDS，返回 session。

    所有产物都落在 fds/simulation/<session>/ 里。函数本身不等 FDS 跑完，
    runme.ps1 会在结束时写 success / failed 标记。
    """
    session = mk_fds_session()
    cfg = merge_config(config)

    # 先把输入文件渲染好，配置不合法就直接抛错，不留下半个空目录
    template_text = TEMPLATE_PATH.read_text(encoding='utf-8')
    fds_text = render_fds(template_text, cfg, sensors, session)

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
        f'cd /d "{FDS_DIR}" && powershell -ExecutionPolicy Bypass '
        f'-File "{RUN_SCRIPT}" -folder "{dst}" -filename {FDS_INPUT_NAME} '
        f'-python "{sys.executable}"'
    )

    # 后台跑，不等它结束
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


def _read_frames_meta(d: Path) -> dict:
    """frames.json 里的元信息：times / files / v_min / v_max。"""
    p = d / FRAMES_NAME
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def list_fds_simulations() -> list:
    """按时间倒序列出全部模拟目录及其状态。

    v_min / v_max 也带出来：选历史结果时先让用户看到这场算出来的量程，
    才知道致伤 / 致死阈值该定在哪。
    """
    if not SIMULATION_DIR.is_dir():
        return []

    out = []
    for d in sorted(SIMULATION_DIR.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        status = simulation_status(d)
        meta = _read_frames_meta(d)
        n_frames = len(meta.get('files') or [])
        if not n_frames:
            img_dir = d / IMG_DIR
            if img_dir.is_dir():
                n_frames = sum(1 for f in img_dir.iterdir()
                               if f.suffix.lower() == '.png')
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


def get_fds_simulation_result_history() -> list:
    """已经跑成功的会话 ID 列表（历史下拉用）。"""
    return [e['session'] for e in list_fds_simulations()
            if e['status'] == 'success']


def get_fds_simulation_template(session: str) -> str:
    """取回该次模拟实际用的 template.fds 原文。"""
    p = simulation_dir(session) / FDS_INPUT_NAME
    if not p.is_file():
        return ''
    return p.read_text(encoding='utf-8', errors='replace')


def _frames_of(d: Path, config: dict) -> list:
    """帧列表：[{index, file, time}]，优先用 txt2gif 写的 frames.json。"""
    meta = _read_frames_meta(d)

    times = meta.get('times') or []
    img_dir = d / IMG_DIR
    files = sorted([f.name for f in img_dir.iterdir()
                    if f.suffix.lower() == '.png']) if img_dir.is_dir() else []

    dt = _num((config or {}).get('dt'), 0.0)
    frames = []
    for i, name in enumerate(files):
        if i < len(times):
            t = _num(times[i])
        elif dt:
            t = i * dt
        else:
            t = None
        frames.append({'index': i, 'file': name, 'time': t})
    return frames


def get_fds_simulation_result(session: str) -> dict:
    """一次模拟的完整状态：状态、产物、帧、环境、配置、检测点读数。"""
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
        'devc': {'names': [], 'units': [], 'times': [], 'values': {}},
        'v_min': None,
        'v_max': None,
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

    result['frames'] = _frames_of(d, cfg)
    result['n_frames'] = len(result['frames'])

    meta = _read_frames_meta(d)
    result['v_min'] = meta.get('v_min')
    result['v_max'] = meta.get('v_max')

    devc_files = sorted(d.glob('*_devc.csv'))
    if devc_files:
        result['devc'] = read_devc_series(devc_files[0])

    return result


# %% ---- 2025-12-27 ------------------------
# Play ground

if __name__ == '__main__':
    print(mk_fds_session())
    print(json.dumps(list_fds_simulations(), ensure_ascii=False, indent=2))


# %% ---- 2025-12-27 ------------------------
# Pending


# %% ---- 2025-12-27 ------------------------
# Pending
