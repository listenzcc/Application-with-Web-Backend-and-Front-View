"""
File: txt2gif.py
Author: Chuncheng Zhang
Date: 2026-09-11

Purpose:
    把 ./output 里的切片文本插值成图片序列（./img/frame_XXX.png），
    再合成 generated.gif。

    在单个模拟目录里运行（cwd = fds/simulation/<session>/）。
    同目录的 config.json 可以覆盖 v_min / v_max / grid。

Functions:
    1. Requirements and constants
    2. Function and class
    3. Play ground
"""


# %%
# Requirements and constants
import os
import json
import time
import shutil
import imageio
import numpy as np
import pandas as pd
import PIL.Image as Image
import multiprocessing as mp

from pathlib import Path
from tqdm.auto import tqdm
from scipy.interpolate import griddata

GIF_NAME = 'generated.gif'
IMG_DIR = Path('img')
FRAMES_NAME = 'frames.json'
CONFIG_NAME = 'config.json'


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


def read_file(path: Path):
    """读一个 fds2ascii 输出文件。前两行是表头（单位行在第二行）。"""
    df = pd.read_csv(path)
    df = df.iloc[1:]
    df.columns = ['x', 'y', 'v']
    for c in df.columns:
        df[c] = df[c].map(float)
    df['t'] = float(path.stem.split('-')[1])
    return df


def draw_frame(df_t, i, v_min, v_max, X, Y, temp_dir):
    img_path = os.path.join(temp_dir, f'frame_{i:03d}.png')

    points = df_t[['x', 'y']].values
    values = df_t['v'].values
    # 零值点必须留着，否则 nearest 插值会把浓度糊满整个画面
    Z = griddata(points, values, (X, Y), method='nearest')
    Z = np.nan_to_num(Z, nan=v_min)
    gray = ((Z - v_min) / (v_max - v_min) * 255)
    gray = np.clip(gray, 0, 255).astype(np.uint8)

    Image.fromarray(gray).save(img_path)

    return img_path


# %%
if __name__ == '__main__':
    GIF_PATH = Path.cwd().joinpath(GIF_NAME)
    cfg = read_config()
    grid_n = int(cfg.get('grid_n') or 100)

    print('Reading data in main process...')
    txt_files = sorted(Path('./output').glob('*.txt'))
    if not txt_files:
        raise SystemExit('./output 里没有切片文本，先跑 fds2txt.py。')

    dfs = [read_file(e) for e in tqdm(txt_files, 'Read txt files')]
    df = pd.concat(dfs)
    df = df.dropna(subset=['x', 'y', 'v'])
    if df.empty:
        raise SystemExit('切片数据是空的。')
    print(f'Data loaded: {len(df)} rows')

    times = np.array(sorted(df['t'].unique()))
    print(f'Time points: {len(times)}')

    df_by_time = {t: df[df['t'] == t]
                  for t in tqdm(times, 'Preparing data by time')}

    x_range = (df['x'].min(), df['x'].max())
    y_range = (df['y'].min(), df['y'].max())
    print(f'Domain: x={x_range}, y={y_range}')

    # 灰度映射区间：config.json 里的 v_min / v_max 优先，
    # v_max 留空则按本次模拟的实测最大值自适应，保证弱浓度也看得见
    v_min = float(cfg['v_min']) if cfg.get('v_min') is not None else 0.0
    v_max = cfg.get('v_max')
    if v_max is None:
        v_max = float(df['v'].max())
    v_max = float(v_max)
    if not np.isfinite(v_max) or v_max <= v_min:
        v_max = v_min + 1e-9
    print(f'Gray scale: {v_min} ~ {v_max}')

    x = np.linspace(x_range[0], x_range[1], grid_n)
    y = np.linspace(y_range[0], y_range[1], grid_n)
    X, Y = np.meshgrid(x, y)

    if IMG_DIR.exists():
        shutil.rmtree(IMG_DIR)
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    temp_dir = str(IMG_DIR)

    num_processes = max(1, min(mp.cpu_count(), len(times)))

    tic = time.time()
    print(f'Processing {len(times)} time points using {num_processes} '
          f'processes...')

    with mp.Pool(processes=num_processes) as pool:
        args = [(df_by_time[t_val], i, v_min, v_max, X, Y, temp_dir)
                for i, t_val in enumerate(times)]
        results = list(tqdm(pool.starmap(draw_frame, args),
                            total=len(times), desc='Processing frames'))

    print(f'Processing complete ({time.time() - tic:.4f} seconds)!')

    images = [imageio.v2.imread(p) for p in sorted(results)]
    imageio.mimsave(GIF_PATH, images, duration=0.5)
    print(f'GIF已创建: {GIF_PATH}')

    # 帧清单，前端滑块靠它拿每帧对应的时间
    (Path.cwd() / FRAMES_NAME).write_text(
        json.dumps({
            'times': [float(t) for t in times],
            'files': [Path(p).name for p in sorted(results)],
            'v_min': v_min,
            'v_max': v_max,
        }, ensure_ascii=False, indent=2),
        encoding='utf-8')
