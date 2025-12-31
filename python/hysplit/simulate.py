# %%
import time
import uuid
import subprocess
from pathlib import Path

from .mk_control import mk_control, mk_emitimes
from .mk_images import collect_and_generate_images

# %%


def simulate_with_hysplit(sensors):
    session = str(uuid.uuid4())
    dir = 'hysplit'
    dst = Path(dir, 'simulation', session)
    dst.mkdir(exist_ok=True, parents=True)

    lat1, lat2 = 30, 33
    lon1, lon2 = 110, 121

    points = [{
        'height': 10,
        'mass': 100 * s.get('value', 0),
        'lon': lon1 + s['x_position'] * (lon2 - lon1),
        'lat': lat1 + (1-s['y_position']) * (lat2 - lat1),
        'gas': 'Gas',
    } for s in sensors]

    print(sensors)
    print(points)

    simulation_date = {
        'year': 2024,
        'month': 5,
        'day': 2,
        'start_hour': 0,
        'duration_hours': 24
    }

    prepare_files(dst, points, simulation_date)

    result = subprocess.run(
        ["c:\\hysplit\\exec\\hycs_std.exe"],        # 命令
        # stdin=open(Path(dst) / "CONTROL"),  # 输入文件
        cwd=dst,  # 切换到此目录
        capture_output=True,
        text=True
    )
    print(result)

    result = subprocess.run(
        ['cmd.exe', '/c', 'concplot.bat'],
        cwd=dst,  # 切换到此目录
        capture_output=True,
        text=True
    )
    print(result)

    result = subprocess.run(
        ['cmd.exe', '/c', 'conctxt.bat'],
        cwd=dst,  # 切换到此目录
        capture_output=True,
        text=True
    )
    print(result)

    collect_and_generate_images(dst)

    print(f'Done. {session}')

    return session


def get_hysplit_simulation_result_history():
    dir = 'hysplit'
    simulation_dir = Path(dir) / 'simulation'
    if not simulation_dir.is_dir():
        return []

    dirs = [d for d in simulation_dir.iterdir() if d.is_dir()]
    dirs = [d for d in dirs if (d / 'generated.gif').exists()]
    return [d.name for d in dirs]


def prepare_files(dst: Path, points: list, simulation_date: dict):
    """
    准备HYSPLIT所需的输入文件
    dst: 目标目录
    """
    # Path
    src_path = Path('./hysplit/template')
    dst_path = Path(dst)
    dst_path.mkdir(parents=True, exist_ok=True)

    # Date
    year = simulation_date['year']
    month = simulation_date['month']
    day = simulation_date['day']
    start_hour = simulation_date['start_hour']
    duration_hours = simulation_date['duration_hours']

    for name in ['SETUP.CFG', 'ASCDATA.CFG']:
        (dst_path / name).write_bytes((src_path / name).read_bytes())

    # 生成CONTROL文件，并保存文件
    control_content = mk_control(
        points=points,
        year=year,
        month=month,
        day=day,
        start_hour=start_hour,
        duration_hours=duration_hours,
        meteorology_dir="D:/WeatherData/",
        output_dir="./",
        output_file="cdump"
    )

    with open(dst_path / 'CONTROL', "w", encoding="utf-8") as f:
        f.write(control_content)
        f.write('\n')

    # 生成EMITIMES文件，并保存文件
    emitimes_content = mk_emitimes(
        points, year, month, day, start_hour, 0, duration_hours, 0)

    with open(dst_path / 'EMITIMES', "w", encoding="utf-8") as f:
        f.write(emitimes_content)
        f.write('\n')

    # Generate concplot.bat
    with open(dst_path / 'concplot.bat', 'w', encoding='utf-8') as f:
        f.writelines([
            'echo off\n',
            'C:/hysplit/exec/concplot.exe +g1 -81  -i./cdump -oconcplot.html -jC:/hysplit/graphics/arlmap -f0  -b100 -t100 -e0 -d1 -r1 -c0 -k1 -m0 -s1 -x1.0 -y1.0  -z50 -u -a0 -: -: -: -: -:'
        ])

    # Generate conctxt.bat
    with open(dst_path / 'conctxt.bat', 'w', encoding='utf-8') as f:
        f.writelines([
            'echo off\n',
            'C:/hysplit/exec/con2asc.exe -i./cdump -oconcentration.txt'
        ])

    return


# %%
