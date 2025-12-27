"""
File: simulate.py
Author: Chuncheng Zhang
Date: 2025-12-27
Copyright & Email: chuncheng.zhang@ia.ac.cn

Purpose:
    Simulate with fds.

Functions:
    1. Requirements and constants
    2. Function and class
    3. Play ground
    4. Pending
    5. Pending
"""


# %% ---- 2025-12-27 ------------------------
# Requirements and constants
import json
import uuid
import subprocess
from pathlib import Path

# %% ---- 2025-12-27 ------------------------
# Function and class


def simulate_with_fds(sensors):
    '''
    使用 FDS 进行模拟，返回 session ID。

    :param list sensors: 传感器信息列表
    '''
    dir = 'fds'
    script = 'runme.ps1'
    session = str(uuid.uuid4())
    fds_file = Path(dir) / f'simulation_{session}.fds'
    sensors_file = Path(dir) / f'sensors_{session}.json'
    fds_template_setup = open(Path(dir) / 'template.fds').read()

    Path(dir, 'simulation').mkdir(exist_ok=True)

    print(sensors)

    # Make surf string for sensors
    surfs = ''
    vents = ''
    obsts = ''
    for sensor in sensors:
        x = sensor['x_position'] * 10
        y = sensor['y_position'] * 10
        v = sensor.get('value', None) * 10
        if v is None:
            continue
        sensor_id = sensor['sensor_id']
        surfs += f'''
&SURF ID='{sensor_id}_SURF',
COLOR='RED',
MASS_FLUX={v:0.2f},
SPEC_ID='CO',
TAU_MF=1.0/
'''
        obsts += f'''
&OBST ID='Obst #{sensor_id}',
XB={x-0.3:0.1f},{x:0.1f},{y-0.1:0.1f},{y+0.4:0.1f},0.0,2.0,
SURF_ID='CONVERTER_SURF'/
'''

        vents += f'''
&VENT ID='Vent #{sensor_id}',
SURF_ID='{sensor_id}_SURF',
XB={x:0.1f},{x:0.1f},{y:0.1f},{y+0.3:0.1f},1.4,1.6/
'''

    fds_setup = fds_template_setup.replace(
        '{{SURF}}', surfs).replace('{{VENT}}', vents).replace('{{OBST}}', obsts)

    # 保存 FDS 输入文件
    with open(fds_file, 'w') as f:
        f.write(fds_setup)

    # 保存传感器信息到 JSON 文件
    with open(sensors_file, 'w') as f:
        json.dump(sensors, f)

    args = f'-folder simulation/{session} -filename {fds_file.name}'
    cmd = f'cd {dir} && powershell -ExecutionPolicy Bypass -File {script} {args}'

    stdout = open(f'{dir}/simulation/stdout-{session}.txt', 'w')
    stderr = open(f'{dir}/simulation/stderr-{session}.txt', 'w')

    # 使用 subprocess.Popen 在后台运行
    subprocess.Popen(
        cmd,
        shell=True,
        stdout=stdout,
        stderr=stderr,
        # stdout=subprocess.DEVNULL,
        # stderr=subprocess.DEVNULL,
        start_new_session=True  # 创建新的进程组
    )

    return session


def get_fds_simulation_result_history():
    dir = 'fds'
    simulation_dir = Path(dir) / 'simulation'

    dirs = [d for d in simulation_dir.iterdir() if d.is_dir()]
    dirs = [d for d in dirs if (d / 'generated.gif').exists()]
    return [d.name for d in dirs]

# %% ---- 2025-12-27 ------------------------
# Play ground


# %% ---- 2025-12-27 ------------------------
# Pending


# %% ---- 2025-12-27 ------------------------
# Pending
