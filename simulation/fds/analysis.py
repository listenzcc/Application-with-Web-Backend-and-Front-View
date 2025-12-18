# %%
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


def read_file(path: Path):
    df = pd.read_csv(path)
    df = df.iloc[1:]
    df.columns = ['y', 'z', 'v']
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
print(df['t'].unique())

# %%
y_range = (df['y'].min(), df['y'].max())
z_range = (df['z'].min(), df['z'].max())
ratio = (y_range[1] - y_range[0]) / (z_range[1] - z_range[0])


# %%

# 简化版：只创建等高线图动画
temp_dir = 'temp_simple'
os.makedirs(temp_dir, exist_ok=True)

t_values = sorted(df['t'].unique())
image_paths = []

# 创建统一的颜色映射范围
# v_log = np.log10(df['v'])
# v_min, v_max = v_log.min(), v_log.max()
v_min, v_max = df['v'].min(), df['v'].max()
v_min, v_max = 0.05, 0.2

for i, t_val in tqdm(enumerate(t_values), total=len(t_values)):
    df_t = df[df['t'] == t_val]

    if len(df_t) > 3:
        fig, ax = plt.subplots(figsize=(10, 10/ratio))

        # 创建插值网格
        x = np.linspace(y_range[0], y_range[1], 100)
        y = np.linspace(z_range[0], z_range[1], 100)
        X, Y = np.meshgrid(x, y)

        # 插值
        points = df_t[['y', 'z']].values
        # values = np.log10(df_t['v'].values)
        values = df_t['v'].values
        Z = griddata(points, values, (X, Y), method='cubic')

        # 绘制等高线
        contour = ax.contourf(X, Y, Z,
                              levels=np.linspace(v_min, v_max, 20),
                              cmap='RdYlBu_r',
                              vmin=v_min,
                              vmax=v_max)

        # 绘制数据点
        ax.scatter(df_t['y'], df_t['z'],
                   c=df_t['v'],
                   s=5,
                   alpha=0.6,
                   edgecolor='white',
                   linewidth=0.5)

        # Create rectangle patch
        rect = patches.Rectangle((4, 0),  # (x, y) of bottom-left corner
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
        ax.set_title(f'Contour Plot - t = {t_val}',
                     fontsize=14, fontweight='bold')

        # plt.colorbar(contour, label='log10(v)')
        plt.colorbar(contour, label='v')
        plt.tight_layout()

        # 保存
        img_path = os.path.join(temp_dir, f'frame_{i:03d}.png')
        plt.savefig(img_path, dpi=120)
        image_paths.append(img_path)
        plt.close()

# 创建GIF
gif_path = 'simple_contour_animation.gif'

images = []
for img_path in image_paths:
    images.append(imageio.imread(img_path))
imageio.mimsave(gif_path, images, duration=0.5)

# 清理
# for img_path in image_paths:
#     os.remove(img_path)
# os.rmdir(temp_dir)

print(f"GIF已创建: {gif_path}")

# %%
