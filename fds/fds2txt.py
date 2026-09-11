"""
File: fds2txt.py
Author: Chuncheng Zhang
Date: 2026-09-11

Purpose:
    把 FDS 的切片结果抽成文本，供 txt2gif.py 画图。
    在单个模拟目录里运行（cwd = fds/simulation/<session>/），
    CHID 从 *_devc.csv 自动识别，不再写死。

Functions:
    1. Requirements and constants
    2. Function and class
    3. Play ground
"""


# %%
# Requirements and constants
import os
import time
import shutil
import tempfile
import pandas as pd
import multiprocessing as mp

from pathlib import Path
from tqdm.auto import tqdm

OUTPUT_DIR = Path('./output')


# %%
# Function and class


def find_job_id(cwd: Path = Path('.')) -> str:
    """从 *_devc.csv 反推 CHID。"""
    files = sorted(Path(cwd).glob('*_devc.csv'))
    if not files:
        return ''
    return files[0].name[:-len('_devc.csv')]


def process_time_point(t, job_id, output_dir='output'):
    """用 fds2ascii 抽一个时刻的切片到文本文件。"""
    conf = {
        'jobID': job_id,
        'type': 2,
        'samplingFactor': 1,
        'domainSelection': 'n',
        'timeStarting': f'{t:0.1f}',
        'timeEnding': f'{t + 0.1:0.1f}',
        'variablesToRead': 1,
        'indexForVariables': 1,  # 切片变量序号，1 = 第一个 SLCF（气体浓度）
        'fileName': f'{output_dir}/u-{t:0.1f}-{t + 0.1:0.1f}.txt'
    }

    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt',
                                     delete=False) as f:
        f.write('\n'.join([str(e) for e in conf.values()]))
        temp_input_file = f.name

    try:
        # fds2ascii 的交互输出很吵，丢到 NUL；产物缺失会在后面被检查出来
        os.system(f'fds2ascii < "{temp_input_file}" > NUL 2>&1')
    finally:
        os.unlink(temp_input_file)

    return t


# %%
if __name__ == '__main__':
    JOB_ID = find_job_id()
    if not JOB_ID:
        raise SystemExit('找不到 *_devc.csv，FDS 可能没跑成功。')
    print(f'Job ID (CHID): {JOB_ID}')

    # 全新的 output 目录，避免混进上一次的残留
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    devc = pd.read_csv(f'{JOB_ID}_devc.csv', header=1)
    print(devc)
    if 'Time' not in devc.columns:
        raise SystemExit(f'{JOB_ID}_devc.csv 里没有 Time 列，表头格式不对。')

    times = devc['Time'] - devc['Time'] % 0.1
    times = sorted(set(times))
    print(times)

    num_processes = max(1, min(mp.cpu_count(), len(times)))

    tic = time.time()
    print(f'Processing {len(times)} time points using {num_processes} '
          f'processes...')

    with mp.Pool(processes=num_processes) as pool:
        args = [(t, JOB_ID, OUTPUT_DIR) for t in times]
        for _ in tqdm(pool.starmap(process_time_point, args),
                      total=len(times), desc='Computing times'):
            pass

    passed = time.time() - tic
    print(f'Processing complete ({passed:.4f} seconds)!')
