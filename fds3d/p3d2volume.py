"""
File: p3d2volume.py
Author: Chuncheng Zhang
Date: 2026-09-15

Purpose:
    把 ./p3d/*.txt（fds2ascii 导出的 PL3D 文本）压成前端能直接喂给
    three.js 的体数据：./volume/frame_XXX.bin，每格 1 字节（uint8），
    并在模拟目录根下写 frames.json 作为时间轴与色标的唯一数据源。

    在单个模拟目录里运行（cwd = fds3d/simulation/<session>/）。

    数据布局：文本是「x 最快，其次 y，最后 z」，reshape 成 (nz, ny, nx)
    再展平，正好是 WebGL 三维纹理要求的顺序（width=nx, height=ny, depth=nz）。
    坐标是节点值（IJK + 1 个点），所以体块正好铺满整个计算域 XB。

    归一化：所有帧共用一套全局量程（frames.json 的 v_min / v_max），
    这样帧与帧之间颜色可比；每帧自己的极值另外记下来，前端拿它算不透明度。

Functions:
    1. Requirements and constants
    2. Function and class
    3. Play ground
"""


# %%
# Requirements and constants
import json
import shutil

import numpy as np
import pandas as pd

from pathlib import Path

VOLUME_DIR = Path('volume')
P3D_DIR = Path('p3d')
INDEX_NAME = 'index.json'
FRAMES_NAME = 'frames.json'
CONFIG_NAME = 'config.json'

#: 单帧体素上限，超了就等间隔抽稀（三维纹理本身撑得住，主要是显存和解析时间）
MAX_VOXELS = 4_000_000

QUANTITY = 'VOLUME FRACTION'


# %%
# Function and class


def read_config() -> dict:
    p = Path(CONFIG_NAME)
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def read_index() -> list:
    """P3D 目录里的帧清单，拿不到就退回目录扫描。"""
    p = P3D_DIR / INDEX_NAME
    if p.is_file():
        try:
            meta = json.loads(p.read_text(encoding='utf-8'))
            items = meta.get('items') or []
            if items:
                return items
        except (OSError, ValueError):
            pass
    return [{'file': f.name, 'time': None}
            for f in sorted(P3D_DIR.glob('*.txt'))]


def value_column(path: Path) -> tuple:
    """按表头单位找浓度列，返回 (列号, 单位)。

    fds2ascii 第一行是名（带 NUL 填充，不解析），第二行是单位：
        m,m,m, kg/kg, m/s, m/s, m/s, mol/mol
    PL3D 的列数会随 QUANTITY 数量变，所以按单位定位而不是写死第 8 列。
    """
    with open(path, 'r', errors='replace') as f:
        f.readline()
        units_line = f.readline()
    units = [u.strip() for u in units_line.split(',') if u.strip()]
    hits = [i for i, u in enumerate(units) if u == 'mol/mol']
    if hits:
        return hits[-1], 'mol/mol'
    return len(units) - 1, (units[-1] if units else '')


def read_frame(path: Path, value_col: int) -> np.ndarray:
    """读一帧文本，返回展平的一维数组（x 最快）。"""
    df = pd.read_csv(path, skiprows=2, header=None,
                     usecols=[0, 1, 2, value_col],
                     names=['x', 'y', 'z', 'v'], dtype=np.float32)
    return df


def frame_shape(df: pd.DataFrame) -> tuple:
    """从坐标反推节点网格 (nx, ny, nz)。"""
    nx = df['x'].nunique()
    ny = df['y'].nunique()
    nz = df['z'].nunique()
    return int(nx), int(ny), int(nz)


def frame_bounds(df: pd.DataFrame) -> list:
    """从帧坐标实测计算域 XB。

    config 里的 xb 可能是 UI 带进来的旧默认值（甲方自带完整 FDS 时
    根本没走渲染流程），体块的实际范围必须以数据自身坐标为准，
    否则整个域会被压进一个错误大小的小盒子里，模型全都对不上。
    """
    return [
        float(df['x'].min()), float(df['x'].max()),
        float(df['y'].min()), float(df['y'].max()),
        float(df['z'].min()), float(df['z'].max()),
    ]


def downsample_axis(n: int, stride: int) -> np.ndarray:
    """等间隔取 n/stride 个点，首尾都留着，体块才铺满计算域。"""
    m = max(2, int(round(n / stride)))
    return np.unique(np.linspace(0, n - 1, m).round().astype(int))


# %%
if __name__ == '__main__':
    cfg = read_config()
    items = read_index()
    if not items:
        raise SystemExit('p3d 里没有帧文本，先跑 p3d2txt.py。')
    print(f'frames to convert: {len(items)}')

    first = P3D_DIR / items[0]['file']
    value_col, units = value_column(first)
    print(f'value column: {value_col}  units: {units}')

    df0 = read_frame(first, value_col)
    nx, ny, nz = frame_shape(df0)
    print(f'nodes: {nx} x {ny} x {nz} = {nx * ny * nz}')
    # 计算域 XB 以帧坐标实测为准；config 里的 xb 只做兜底（老数据没坐标时）
    xb = frame_bounds(df0)
    print(f'bounds: {xb}')

    stride = 1
    while (nx // stride) * (ny // stride) * (nz // stride) > MAX_VOXELS:
        stride += 1
    if stride > 1:
        print(f'too many voxels, downsampling by stride {stride}')
    ix = downsample_axis(nx, stride)
    iy = downsample_axis(ny, stride)
    iz = downsample_axis(nz, stride)
    out_nx, out_ny, out_nz = len(ix), len(iy), len(iz)

    # 第一遍：逐帧极值 + 全局量程
    per_frame_range = []
    g_min, g_max = np.inf, -np.inf
    for it in items:
        df = read_frame(P3D_DIR / it['file'], value_col)
        v = df['v'].to_numpy(dtype=np.float32)
        v = v[np.isfinite(v)]
        lo = float(v.min()) if v.size else 0.0
        hi = float(v.max()) if v.size else 0.0
        per_frame_range.append((lo, hi))
        g_min = min(g_min, lo)
        g_max = max(g_max, hi)
    if not np.isfinite(g_min) or not np.isfinite(g_max) or g_max <= g_min:
        g_max = g_min + 1e-9

    # config.json 里写死的量程优先（跟二维那套一致）
    if cfg.get('v_min') is not None:
        g_min = float(cfg['v_min'])
    if cfg.get('v_max') is not None:
        g_max = float(cfg['v_max'])
    span = max(g_max - g_min, 1e-12)
    print(f'global range: {g_min:g} ~ {g_max:g}')

    if VOLUME_DIR.exists():
        shutil.rmtree(VOLUME_DIR)
    VOLUME_DIR.mkdir(parents=True, exist_ok=True)

    # 第二遍：写成 uint8 体数据
    frames = []
    for i, it in enumerate(items):
        df = read_frame(P3D_DIR / it['file'], value_col)
        v = df['v'].to_numpy(dtype=np.float32)
        if v.size != nx * ny * nz:
            raise SystemExit(
                f"{it['file']}: 数据行数 {v.size} 与网格 {nx}×{ny}×{nz} 不符。")
        vol = v.reshape(nz, ny, nx)
        vol = np.nan_to_num(vol, nan=g_min)
        if stride > 1:
            vol = vol[np.ix_(iz, iy, ix)]
        data = np.clip((vol - g_min) / span * 255.0, 0, 255).astype(np.uint8)

        name = f'frame_{i:03d}.bin'
        (VOLUME_DIR / name).write_bytes(np.ascontiguousarray(data).tobytes())

        lo, hi = per_frame_range[i]
        frames.append({
            'index': i,
            'file': name,
            'time': it.get('time'),
            'v_min': round(lo, 8),
            'v_max': round(hi, 8),
        })
        print(f"  {name}  t={it.get('time')}  range {lo:.4g} ~ {hi:.4g}"
              f"  {(VOLUME_DIR / name).stat().st_size / 1e6:.2f} MB")

    meta = {
        'quantity': QUANTITY,
        'units': units,
        'frames': frames,
        'n_frames': len(frames),
        'v_min': g_min,
        'v_max': g_max,
        'ijk': [out_nx, out_ny, out_nz],
        'ijk_full': [nx, ny, nz],
        'xb': xb or cfg.get('xb'),
        'downsample': stride,
    }
    Path(FRAMES_NAME).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Wrote {FRAMES_NAME}')

    # 体积文本每帧几十 MB，默认转完就删；.q 原始文件留着，随时能重导
    if not cfg.get('keep_p3d_txt'):
        shutil.rmtree(P3D_DIR, ignore_errors=True)
        print('Removed p3d/*.txt')
