# %%
"""把 HYSPLIT 的浓度文本结果整理成帧图 + 帧清单。

产物（全部落在会话目录里）：
    img/{day:03d}-{hr:02d}.png   逐时次浓度散点图
    frames.json                  帧清单，前端时间轴直接吃这个
    table.json                   原始点表，前端画热力图用
    generated.gif                全部帧拼成的动图
"""
import json
import itertools
import numpy as np
import pandas as pd
import imageio.v2 as imageio
import matplotlib.pyplot as plt

from datetime import datetime, timedelta
from pathlib import Path
from tqdm.auto import tqdm


# %%
FRAMES_NAME = 'frames.json'
TABLE_NAME = 'table.json'
IMG_DIR = 'img'
GIF_NAME = 'generated.gif'


def frame_datetime(year: int, day_of_year: int, hour: int):
    """con2asc 的输出里 DAY 是「年内第几天」，HR 是小时。

    2024 年第 123 天 = 2024-05-02。转成真实时间，前端时间轴才有意义。
    转换不了就返回 None。
    """
    try:
        year = int(year)
        day_of_year = int(day_of_year)
        hour = int(hour)
        if not (1 <= year <= 9999) or not (1 <= day_of_year <= 366):
            return None
        return datetime(year, 1, 1) + timedelta(days=day_of_year - 1,
                                                hours=hour)
    except (TypeError, ValueError):
        return None


def collect_and_generate_images(folder: Path, year: int = None):
    """返回帧数量。同时写出 frames.json / table.json / generated.gif。"""
    folder = Path(folder)
    images_folder = folder / IMG_DIR

    # 清掉上一次的帧，避免重跑时新旧混在一起
    if images_folder.exists():
        for old in images_folder.glob('*.png'):
            old.unlink()
    images_folder.mkdir(parents=True, exist_ok=True)

    # Find concentration.txt_xxx_yy files
    txt_files = sorted(folder.glob('concentration.txt_*'))
    dfs = []
    for f in tqdm(txt_files):
        csv = pd.read_csv(f, sep=r'\s+', skiprows=0)
        dfs.append(csv)

    if not dfs:
        _write_frames(folder, [], None, None)
        return 0

    table = pd.concat(dfs)
    table['m'] = table[table.columns[4]]
    floor = table['m'].min() / 10
    # 原位归一化：把最小值推到 10，再取 log10。min<=0 时跳过，否则除零得 inf
    if np.isfinite(floor) and floor > 0:
        table['m'] = table['m'] / floor
    # 夹一下，避免 log10(0) = -inf 污染色标
    table['m'] = np.log10(np.clip(table['m'].to_numpy(dtype=float), 1e-30, None))
    vmin, vmax = float(table['m'].min()), float(table['m'].max())
    table.index = range(len(table))
    print(table)

    frames = []
    for day, hr in itertools.product(sorted(table['DAY'].unique()),
                                     sorted(table['HR'].unique())):
        df = table[(table['DAY'] == day) & (table['HR'] == hr)]
        if len(df) == 0:
            continue

        print(day, hr, len(df))
        img_filename = images_folder / f'{int(day):03d}-{int(hr):02d}.png'
        when = frame_datetime(year, day, hr)

        fig, ax = plt.subplots(figsize=(7, 6))
        sc = ax.scatter(df['LON'], df['LAT'], c=df['m'],
                        vmin=vmin, vmax=vmax, s=14)
        ax.set_xlim((table['LON'].min(), table['LON'].max()))
        ax.set_ylim((table['LAT'].min(), table['LAT'].max()))
        ax.set_xlabel('Longitude')
        ax.set_ylabel('Latitude')
        ax.set_title('Concentration  ' + (when.strftime('%Y-%m-%d %H:%M')
                                          if when else f'day {int(day):03d} hour {int(hr):02d}'))
        fig.colorbar(sc, ax=ax, label='log10 (relative)')
        fig.tight_layout()
        fig.savefig(img_filename, dpi=110)
        plt.close(fig)

        frames.append({
            'index': len(frames),
            'file': img_filename.name,
            'day': int(day),
            'hour': int(hr),
            'label': (when.strftime('%m-%d %H:%M') if when
                      else f'{int(day):03d}-{int(hr):02d}'),
            'datetime': when.strftime('%Y-%m-%d %H:%M') if when else None,
        })
        print(f"Generated image: {img_filename}")

    # Generate gif if we have multiple images
    if len(frames) > 1:
        gif_filename = folder / GIF_NAME
        images = [imageio.imread(images_folder / fr['file']) for fr in frames]
        # 0.5 seconds per frame
        imageio.mimsave(gif_filename, images, duration=0.5)
        print(f"Generated GIF: {gif_filename}")

    table.to_json(folder / TABLE_NAME)
    _write_frames(folder, frames, vmin, vmax)

    return len(frames)


def _write_frames(folder: Path, frames: list, v_min, v_max):
    (folder / FRAMES_NAME).write_text(
        json.dumps({
            'frames': frames,
            'n_frames': len(frames),
            'v_min': v_min,
            'v_max': v_max,
            'gif': GIF_NAME if len(frames) > 1 else None,
        }, ensure_ascii=False, indent=2),
        encoding='utf-8')


# %%
if __name__ == '__main__':
    collect_and_generate_images(
        './hysplit/simulation/2026-09-11-15-00-00-demo')
