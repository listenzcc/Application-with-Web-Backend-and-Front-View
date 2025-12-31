# %%
import json
import itertools
import numpy as np
import pandas as pd
import imageio.v2 as imageio
import matplotlib.pyplot as plt

from pathlib import Path
from tqdm.auto import tqdm


# %%


def collect_and_generate_images(folder: Path):
    # Prepare folder
    folder = Path(folder)
    images_folder = folder / 'img'
    images_folder.mkdir(parents=True, exist_ok=True)

    # Find concentration.txt_xxx_yy files
    txt_files = sorted(folder.glob('concentration.txt_*'))
    dfs = []
    for f in tqdm(txt_files):
        csv = pd.read_csv(f, sep='\s+', skiprows=0)
        dfs.append(csv)

    table = pd.concat(dfs)
    table['m'] = table[table.columns[4]]
    table['m'] = table['m'] / (table['m'].min() / 10)
    table['m'] = np.log10(table['m'])
    vmin,  vmax = table['m'].min(), table['m'].max()
    table.index = range(len(table))
    print(table)

    image_files = []
    for day, hr in itertools.product(table['DAY'].unique(), table['HR'].unique()):
        df = table[(table['DAY'] == day) & (table['HR'] == hr)]
        if len(df) == 0:
            continue
        print(day, hr, len(df))
        img_filename = images_folder / f'{day:03d}-{hr:02d}.png'
        plt.scatter(df['LON'], df['LAT'], c=df['m'], vmin=vmin, vmax=vmax)
        plt.xlim((table['LON'].min(), table['LON'].max()))
        plt.ylim((table['LAT'].min(), table['LAT'].max()))
        plt.savefig(img_filename)
        plt.close()
        image_files.append(img_filename)
        print(f"Generated image: {img_filename}")

    # Generate gif if we have multiple images
    if len(image_files) > 1:
        gif_filename = folder / 'generated.gif'

        # Read all images
        images = []
        for img_file in image_files:
            images.append(imageio.imread(img_file))

        # Save as GIF
        # 0.5 seconds per frame
        imageio.mimsave(gif_filename, images, duration=0.5)
        print(f"Generated GIF: {gif_filename}")

    table.to_json(folder / 'table.json')

    return len(image_files)


# %%
if __name__ == '__main__':
    collect_and_generate_images(
        './hysplit_simulation/1767078539.772455-bc5c1b4e-e770-45b5-945f-5a0f9fb46434')
