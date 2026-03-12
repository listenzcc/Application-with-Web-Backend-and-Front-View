"""
File: check-fds.py
Author: Chuncheng Zhang
Date: 2026-03-12
Copyright & Email: chuncheng.zhang@ia.ac.cn

Purpose:
    Check the results for the fds simulation.

Functions:
    1. Requirements and constants
    2. Function and class
    3. Play ground
    4. Pending
    5. Pending
"""


# %% ---- 2026-03-12 ------------------------
# Requirements and constants
import matplotlib.pyplot as plt
import random
import numpy as np
from PIL import Image
from pathlib import Path

# %%
FDS_DIR = Path('./fds/simulation')

# %% ---- 2026-03-12 ------------------------
# Function and class


# %% ---- 2026-03-12 ------------------------
# Play ground
folders = []
for folder in FDS_DIR.iterdir():
    check_file = folder.joinpath('generated.gif')
    if not folder.is_dir() or not check_file.is_file():
        continue
    folders.append(folder)
print(folders)

# Choose one folder randomly
random.shuffle(folders)
folder = folders[0]
print(f'{folder=}')

# Get images
mat = np.array([np.array(Image.open(e))
                for e in folder.joinpath('img').iterdir()])
print(mat.shape)

mat = np.reshape(mat, (mat.shape[0], -1))
std = np.std(mat, axis=0)
sorted_indices = np.argsort(std)[::-1]  # [::-1] 表示从大到小
mat_sorted = mat[:, sorted_indices]

plt.style.use('ggplot')
plt.plot(mat_sorted[:, :10])
plt.show()

# %% ---- 2026-03-12 ------------------------
# Pending


# %% ---- 2026-03-12 ------------------------
# Pending
