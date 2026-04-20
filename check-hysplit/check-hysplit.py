"""
File: check-hysplit.py
Author: Chuncheng Zhang
Date: 2026-04-20
Copyright & Email: chuncheng.zhang@ia.ac.cn

Purpose:
    Analysis the hysplit results.

Functions:
    1. Requirements and constants
    2. Function and class
    3. Play ground
    4. Pending
    5. Pending
"""


# %% ---- 2026-04-20 ------------------------
# Requirements and constants
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from pathlib import Path
import pandas as pd

# %%
target_dir = Path(__file__).parent.parent.joinpath(
    'hysplit/simulation/4afd9285-2483-4fe2-af03-623261f379ae')

files = list(target_dir.glob('concentration.txt_*'))

dfs = []
for p in files:
    df = pd.read_csv(p, delimiter='\s+', header=0)
    dfs.append(df)
df = pd.concat(dfs, ignore_index=True)
print(df)

# %% ---- 2026-04-20 ------------------------
# Function and class


# %% ---- 2026-04-20 ------------------------
# Play ground

# 假设您的 DataFrame 名为 df

# 创建时间列（DAY + HR 的组合）
df['TIME'] = df['DAY'] + df['HR'] / 24  # 将小时转换为天的小数
# 或者创建字符串时间标签
df['TIME_LABEL'] = df['DAY'].astype(str) + '-' + df['HR'].astype(str)

# Scale LAT and LON into (0, 1)
for c in ['LON', 'LAT', 'Gas']:
    df[c] = (df[c] - df[c].min()) / (df[c].max() - df[c].min())

print(df)


# %%

# 方案1：3D 散点图（最直接）
fig1 = go.Figure(data=[go.Scatter3d(
    x=df['LON'],
    y=df['LAT'],
    z=df['TIME'],
    mode='markers',
    marker=dict(
        # size=df['Gas'],  # 调整大小，注意您的数据是 0.23E-09 格式
        color=np.log(df['Gas']),  # 转换为正常数值用于颜色映射
        # colorscale='Viridis',
        colorscale='RdBu',
        colorbar=dict(title="Gas"),
        showscale=True,
        opacity=0.5
    ),
    name='Gas Concentration'
)])

fig1.update_layout(
    title='3D Gas Concentration Visualization',
    scene=dict(
        xaxis_title='Longitude',
        yaxis_title='Latitude',
        zaxis_title='Time (DAY + HR/24)',
        camera=dict(
            eye=dict(x=1.5, y=1.5, z=1.5)
        )
    ),
    width=1000,
    height=800
)

fig1.show()

# %% ---- 2026-04-20 ------------------------
# Pending


# %% ---- 2026-04-20 ------------------------
# Pending
