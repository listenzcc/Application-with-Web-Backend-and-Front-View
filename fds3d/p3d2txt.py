"""
File: p3d2txt.py
Author: Chuncheng Zhang
Date: 2026-09-15

Purpose:
    把 FDS 的 PL3D 体数据（<CHID>_*_*p*.q）用 fds2ascii 导成文本，
    落到 ./p3d/frame_XXX.txt，并写 ./p3d/index.json 记下每帧对应的时间。

    在单个模拟目录里运行（cwd = fds3d/simulation/<session>/）。
    CHID 从 *_devc.csv 自动识别。

    fds2ascii 是交互式程序，这里把全部回答一次性喂进 stdin：
        <CHID> / 1(PL3D) / 1(全点采样) / n(不限域)
        然后每帧一次： <序号> <输出文件名>
        最后 0 结束
    它还会读 <CHID>.smv，缺了这个文件会直接报 fatal error。

Functions:
    1. Requirements and constants
    2. Function and class
    3. Play ground
"""


# %%
# Requirements and constants
import os
import re
import sys
import json
import shutil
import subprocess

from pathlib import Path

P3D_DIR = Path('p3d')
INDEX_NAME = 'index.json'
LOG_NAME = 'fds2ascii.log'

#: fds2ascii 找不到时用它兜底
FDS_BIN_CANDIDATES = [
    r'C:\Program Files\firemodels\FDS6\bin',
    r'C:\Program Files (x86)\firemodels\FDS6\bin',
]


# %%
# Function and class


def find_job_id(cwd: Path = Path('.')) -> str:
    """从 *_devc.csv 反推 CHID。"""
    files = sorted(Path(cwd).glob('*_devc.csv'))
    if not files:
        return ''
    return files[0].name[:-len('_devc.csv')]


def fds_bin_dir() -> str:
    for p in FDS_BIN_CANDIDATES:
        if Path(p).is_dir():
            return p
    return ''


def q_sort_key(path: Path):
    """`<CHID>_1_24p10.q` -> (网格号, 时间)。时间在文件名里写成 24p10。

    排序必须按数值时间，不能按字符串，否则 100.00 会排到 20.00 前面。
    """
    m = re.search(r'_(\d+)_(\d+)p(\d+)\.q$', path.name)
    if not m:
        return (0, 0.0)
    return (int(m.group(1)), float(f'{m.group(2)}.{m.group(3)}'))


def collect_q_files(chid: str) -> list:
    """这次模拟落下的全部 .q，按（网格号, 时间）排序。"""
    files = [p for p in Path('.').glob(f'{chid}_*.q') if q_sort_key(p)[1] > 0]
    files.sort(key=q_sort_key)
    return files


def run_fds2ascii(chid: str, q_files: list) -> str:
    """喂脚本给 fds2ascii，返回它的输出（日志用）。"""
    if P3D_DIR.exists():
        shutil.rmtree(P3D_DIR)
    P3D_DIR.mkdir(parents=True, exist_ok=True)

    lines = [chid, '1', '1', 'n']
    for i, _ in enumerate(q_files):
        lines.append(str(i + 1))
        lines.append(f'{P3D_DIR.as_posix()}/frame_{i:03d}.txt')
    lines.append('0')

    env = dict(os.environ)
    bin_dir = fds_bin_dir()
    if bin_dir:
        env['PATH'] = bin_dir + os.pathsep + env.get('PATH', '')

    proc = subprocess.run(
        'fds2ascii',
        input='\n'.join(lines) + '\n',
        text=True,
        capture_output=True,
        env=env,
        shell=True,
    )
    log = (proc.stdout or '') + (proc.stderr or '')
    Path(LOG_NAME).write_text(log, encoding='utf-8', errors='replace')
    return log


# %%
if __name__ == '__main__':
    JOB_ID = find_job_id()
    if not JOB_ID:
        raise SystemExit('找不到 *_devc.csv，FDS 可能没跑成功。')
    print(f'Job ID (CHID): {JOB_ID}')

    if not Path(f'{JOB_ID}.smv').is_file():
        raise SystemExit(f'缺少 {JOB_ID}.smv，fds2ascii 读不了 PL3D。')

    q_files = collect_q_files(JOB_ID)
    if not q_files:
        raise SystemExit(f'没找到 {JOB_ID}_*.q，DUMP 里 DT_PL3D 可能没配上。')
    print(f'PL3D files: {len(q_files)}')

    log = run_fds2ascii(JOB_ID, q_files)

    items = []
    for i, q in enumerate(q_files):
        out = P3D_DIR / f'frame_{i:03d}.txt'
        if not out.is_file() or out.stat().st_size == 0:
            tail = '\n'.join(log.strip().splitlines()[-12:])
            raise SystemExit(f'fds2ascii 没有产出 {out.name}。日志尾部：\n{tail}')
        _, t = q_sort_key(q)
        items.append({'file': out.name, 'time': t, 'q': q.name})
        print(f'  {out.name}  t={t:g}s  {out.stat().st_size / 1e6:.1f} MB')

    (P3D_DIR / INDEX_NAME).write_text(
        json.dumps({'chid': JOB_ID, 'n_frames': len(items), 'items': items},
                   ensure_ascii=False, indent=2),
        encoding='utf-8')
    print(f'Wrote {P3D_DIR / INDEX_NAME}')
