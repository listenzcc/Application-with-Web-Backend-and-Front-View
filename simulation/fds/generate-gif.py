# %%
import time
import multiprocessing as mp
import os
import imageio
from scipy.interpolate import griddata
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from pathlib import Path
from tqdm.auto import tqdm

# %%
# Constants
WD = Path('../../received/4/')
GIF_PATH = Path.cwd().joinpath('generated.gif')

# cd to
os.chdir(WD)

# %%


def read_file(path: Path):
    df = pd.read_csv(path)
    df = df.iloc[1:]
    df.columns = ['x', 'y', 'v']
    for c in df.columns:
        df[c] = df[c].map(float)
    df['t'] = float(path.stem.split('-')[1])
    return df


# %%
dfs = [read_file(e) for e in Path('./output').iterdir()]
df = pd.concat(dfs)
df = df[df['v'] != 0]
df

# %%
x_range = (df['x'].min(), df['x'].max())
y_range = (df['y'].min(), df['y'].max())
ratio = (x_range[1] - x_range[0]) / (y_range[1] - y_range[0])


# %%

# 简化版：只创建等高线图动画
temp_dir = 'temp_simple'
os.makedirs(temp_dir, exist_ok=True)

times = np.array(sorted(df['t'].unique()))
print(times)

# 创建统一的颜色映射范围
# v_log = np.log10(df['v'])
# v_min, v_max = v_log.min(), v_log.max()
v_min, v_max = df['v'].min(), df['v'].max()
v_min, v_max = 0.05, 0.2

# 创建插值网格
x = np.linspace(x_range[0], x_range[1], 100)
y = np.linspace(y_range[0], y_range[1], 100)
X, Y = np.meshgrid(x, y)


def draw_frame(df_t, i, t_val):
    fig, ax = plt.subplots(figsize=(10, 10/ratio))

    # 插值
    points = df_t[['x', 'y']].values
    values = df_t['v'].values
    Z = griddata(points, values, (X, Y), method='cubic')

    cmap = 'Reds'

    # 绘制等高线
    contour = ax.contourf(
        X, Y, Z,
        levels=np.linspace(v_min, v_max, 20),
        cmap=cmap,
        vmin=v_min,
        vmax=v_max)

    # 绘制数据点
    ax.scatter(
        df_t['x'], df_t['y'],
        c=df_t['v'],
        s=5,
        alpha=0.2,
        #    edgecolor='white',
        linewidth=0.1)

    # Create rectangle patch
    rect = patches.Rectangle(
        (4, 0),  # (x, y) of bottom-left corner
        1,       # width (x-direction)
        2,       # height (y-direction)
        linewidth=2,
        edgecolor='red',
        facecolor='lightblue',
        #  alpha=0.5,
        label='Rectangle')

    # Add rectangle to axes
    ax.add_patch(rect)

    ax.set_xlabel('y', fontsize=12)
    ax.set_ylabel('z', fontsize=12)
    ax.set_title(
        f'Contour Plot - t = {t_val}', fontsize=14, fontweight='bold')

    # plt.colorbar(contour, label='log10(v)')
    # plt.colorbar(contour, label='v')
    fig.colorbar(contour, label='v')
    fig.tight_layout()

    # 保存
    img_path = os.path.join(temp_dir, f'frame_{i:03d}.png')
    fig.savefig(img_path)
    print(f'> {img_path}')
    plt.close(fig)
    return img_path


# %%
if __name__ == '__main__':
    num_processes = min(mp.cpu_count(), len(times))

    tic = time.time()
    print(
        f"Processing {len(times)} time points using {num_processes} processes...")

    # for i, t_val in tqdm(enumerate(times), total=len(times)):
    #     df_t = df[df['t'] == t_val]
    #     draw_frame(df_t, i, t_val)

    with mp.Pool(processes=num_processes) as pool:
        args = []
        for i, t_val in tqdm(enumerate(times), total=len(times)):
            df_t = df[df['t'] == t_val]
            args.append((df_t, i, t_val))

        # Process time points in parallel with progress bar
        results = []
        for result in tqdm(
            pool.starmap(draw_frame, args),
            total=len(times),
            desc='Computing times'
        ):
            results.append(result)

    passed = time.time() - tic
    print(f"Processing complete ({passed:.4f} seconds)!")

    # 创建GIF

    images = []
    for img_path in sorted(results):
        images.append(imageio.v2.imread(img_path))
    imageio.mimsave(GIF_PATH, images, duration=0.5)

    # 清理
    # for img_path in image_paths:
    #     os.remove(img_path)
    # os.rmdir(temp_dir)

    print(f"GIF已创建: {GIF_PATH}")

# %%
