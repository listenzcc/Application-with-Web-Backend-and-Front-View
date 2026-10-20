# %%
"""HYSPLIT 高斯模型的模拟调度。

与拉格朗日模型（python/hysplit/）的唯一区别：SETUP.CFG 用
hysplitGaussian/template/ 里姜老师给的版本（initd = 3，
从拉格朗日烟团换成高斯模型）。CONTROL、EMITIMES、后处理、
产物组织完全一样。

产物组织与 FDS / 拉格朗日模型保持一致：一次模拟 = 一个会话目录

    hysplitGaussian/simulation/<YYYY-MM-DD-HH-MM-SS-UUID>/

会话目录内容：
    config.json      本次运行参数（含城市、计算域、界面气象，存档用）
    stations.json    本次用的城市监测点与读数
    CONTROL          主输入卡
    EMITIMES         释放源文件
    SETUP.CFG        HYSPLIT 设置（initd = 3，高斯模型，从模板复制）
    ASCDATA.CFG      地形设置（从模板复制）
    concplot.bat / conctxt.bat   后处理命令（存档，便于手工复跑）
    cdump            模型输出
    concentration.txt_*          后处理出的浓度文本
    img/{day:03d}-{hr:02d}.png   逐时次帧图
    frames.json      帧清单
    table.json       点表
    generated.gif    动图
    success / failed 状态标记
    run.log          运行日志

CONTROL 拼装、气象文件定位、帧图/浓度表生成这些纯逻辑直接复用
python/hysplit/ 里的实现，两边不会漂移。
"""
import json
import time
import uuid
import subprocess
import traceback
import multiprocessing as mp
from datetime import datetime
from pathlib import Path

from hysplit.mk_control import mk_control, mk_emitimes, met_file_name
from hysplit.mk_images import collect_and_generate_images
from hysplit.simulate import (
    resolve_met_file,
    build_points,
    build_station_marks,
    simulation_status,
    _run_exe,
    read_stations,
)
from hysplit.stations import (city_bbox, city_center, resolve_city,
                              stations_for_simulation)

# %%
# python/hysplit_gaussian/simulate.py -> python/hysplit_gaussian -> python -> <root>
PROJECT_ROOT = Path(__file__).resolve().parents[2]
HYSPLIT_GAUSSIAN_DIR = PROJECT_ROOT / 'hysplitGaussian'
SIMULATION_DIR = HYSPLIT_GAUSSIAN_DIR / 'simulation'
TEMPLATE_DIR = HYSPLIT_GAUSSIAN_DIR / 'template'

HYSPLIT_HOME = Path('C:/hysplit')
HYSPLIT_EXEC = HYSPLIT_HOME / 'exec'
HYSPLIT_GRAPHICS = HYSPLIT_HOME / 'graphics'

SESSION_TS_FMT = '%Y-%m-%d-%H-%M-%S'

CONFIG_NAME = 'config.json'
#: 新会话写这个：城市监测点 + 读数
STATIONS_NAME = 'stations.json'
#: 旧会话的传感器文件，只读兼容
SENSORS_NAME = 'sensors.json'
SUCCESS_MARKER = 'success'
FAILED_MARKER = 'failed'
FRAMES_NAME = 'frames.json'
TABLE_NAME = 'table.json'
IMG_DIR = 'img'
GIF_NAME = 'generated.gif'
LOG_NAME = 'run.log'

CONTROL_NAME = 'CONTROL'
EMITIMES_NAME = 'EMITIMES'
CDUMP_NAME = 'cdump'

#: 从 hysplitGaussian/template/ 复制进会话目录的配置文件。
#: SETUP.CFG 与拉格朗日模型的区别就在这里（initd = 3 -> 高斯模型）。
COPIED_TEMPLATES = ('SETUP.CFG', 'ASCDATA.CFG')

#: 旧会话（sensors.json 归一化坐标）换算经纬度时用的框。
#: 新会话的计算域跟着城市走，见 stations.city_bbox()。
LEGACY_BBOX = {'lat1': 30.0, 'lat2': 31.0, 'lon1': 110.0, 'lon2': 111.0}
DEFAULT_BBOX = LEGACY_BBOX
BBOX_LAT1, BBOX_LAT2 = 30.0, 31.0
BBOX_LON1, BBOX_LON2 = 110.0, 111.0

WEATHER_OPTIONS = ['晴', '多云', '阴', '雨', '雪', '雾']
WIND_DIRECTIONS = ['北', '东北', '东', '东南', '南', '西南', '西', '西北']


def _location_candidates() -> dict:
    """老接口：城市名 -> 地图中心。数据源统一到 stations.CITIES。"""
    from hysplit.stations import city_names
    return {name: city_center(name) for name in city_names()}


LOCATION_CANDIDATES = _location_candidates()

DEFAULT_CONFIG = {
    # ---- 界面上的地理 / 气象（气象部分不参与计算，随运行存档）----
    'city': '北京',
    'weather': '晴',
    'temperature': 20.0,
    'humidity': 50.0,
    'wind_speed': 3,
    'wind_direction': '东',
    # ---- 真正决定计算的参数 ----
    'year': 2024,
    'month': 5,
    'day': 2,
    'start_hour': 0,
    'duration_hours': 24,
    'release_height': 10.0,
    'top_height': 10000.0,
    'output_interval_minutes': 100,
    'weather_mode': 'file',
    # 危险区阈值（与色标同单位，log10 相对值）。留空则查看结果时按量程自动取，
    # 这两个值只是「看结果」的参数，不参与 HYSPLIT 计算本身。
    'lvl1': None,
    'lvl2': None,
}

# %%
# ---- 会话目录 ----


def mk_hysplit_gaussian_session() -> str:
    """会话名：YYYY-MM-DD-HH-MM-SS-<uuid>，与 FDS / 拉格朗日一致。"""
    now = datetime.now()
    return '-'.join([now.strftime(SESSION_TS_FMT), str(uuid.uuid4())])


def simulation_dir(session: str) -> Path:
    """会话名 -> 目录。挡掉路径穿越。"""
    s = str(session or '').strip()
    if not s or any(c in s for c in ('/', '\\', '..')):
        raise ValueError(f'非法 session: {session!r}')
    return SIMULATION_DIR / s


def merge_config(config: dict = None) -> dict:
    """界面传来的 config 与默认值合并。None 值不覆盖默认值。

    顺便把城市收敛成合法值，并把计算域算好写进 config：历史会话回看时
    直接读存档的 bbox，不受以后改城市预设的影响。
    """
    merged = dict(DEFAULT_CONFIG)
    if config:
        for k, v in config.items():
            if v is not None:
                merged[k] = v

    merged['city'] = resolve_city(merged.get('city'))
    bbox = merged.get('bbox')
    if not isinstance(bbox, dict) or not {'lat1', 'lat2', 'lon1', 'lon2'} <= set(bbox):
        bbox = city_bbox(merged['city'])
    merged['bbox'] = {k: float(bbox[k]) for k in ('lat1', 'lat2', 'lon1', 'lon2')}
    merged['city_center'] = city_center(merged['city'])
    return merged


# %%
# ---- 输入文件 ----


def prepare_files(dst: Path, points: list, config: dict, met_dir: Path,
                  met_name: str):
    """把一次模拟需要的输入文件全部写进会话目录。"""
    dst = Path(dst)
    dst.mkdir(parents=True, exist_ok=True)

    # 模板配置原样复制进会话目录，保证目录自包含。
    # 这里的 SETUP.CFG 就是 initd = 3 的高斯模型版本。
    for name in COPIED_TEMPLATES:
        src = TEMPLATE_DIR / name
        if src.is_file():
            (dst / name).write_bytes(src.read_bytes())

    year = int(config['year'])
    month = int(config['month'])
    day = int(config['day'])
    start_hour = int(config['start_hour'])
    duration_hours = int(config['duration_hours'])

    # CONTROL
    control_content = mk_control(
        points=points,
        year=year,
        month=month,
        day=day,
        meteorology_dir=_met_dir_for_control(met_dir),
        meteorology_files=[(_met_dir_for_control(met_dir), met_name)],
        start_hour=start_hour,
        duration_hours=duration_hours,
        top_height=float(config.get('top_height') or 10000.0),
        output_dir='./',
        output_file=CDUMP_NAME,
        output_interval_minutes=int(
            config.get('output_interval_minutes') or 100),
    )
    (dst / CONTROL_NAME).write_text(control_content + '\n', encoding='utf-8')

    # EMITIMES
    emitimes_content = mk_emitimes(
        points, year, month, day, start_hour, 0, duration_hours, 0)
    (dst / EMITIMES_NAME).write_text(emitimes_content + '\n', encoding='utf-8')

    # 后处理命令：写进目录存档，便于手工复跑；实际执行时直接调 exe
    (dst / 'concplot.bat').write_text('\n'.join([
        'echo off',
        f'{_win(HYSPLIT_EXEC / "concplot.exe")} +g1 -81 -i./{CDUMP_NAME} '
        f'-oconcplot.html -j{_win(HYSPLIT_GRAPHICS / "arlmap")} '
        '-f0 -b100 -t100 -e0 -d1 -r1 -c0 -k1 -m0 -s1 -x1.0 -y1.0 '
        '-z50 -u -a0 -: -: -: -: -:',
        '',
    ]), encoding='utf-8')

    (dst / 'conctxt.bat').write_text('\n'.join([
        'echo off',
        f'{_win(HYSPLIT_EXEC / "con2asc.exe")} -i./{CDUMP_NAME} '
        '-oconcentration.txt',
        '',
    ]), encoding='utf-8')

    return dst


def _win(p: Path) -> str:
    """PosixPath -> Windows 路径字符串（.bat 里要用反斜杠）。"""
    return str(p).replace('/', '\\')


def _met_dir_for_control(met_dir) -> str:
    """CONTROL 里的气象目录必须以路径分隔符结尾，否则 HYSPLIT 找不到文件。"""
    s = str(met_dir)
    return s if s.endswith(('\\', '/')) else s + '\\'


# %%
# ---- 跑模型 ----


def simulate_with_hysplit_gaussian(stations: list = None, session: str = None,
                                   config: dict = None) -> str:
    """起一次高斯模型模拟（后台进程），立刻返回 session。

    stations 省略时按 config['city'] 现场生成城市监测点（含监测数据）。
    """
    session = session or mk_hysplit_gaussian_session()
    cfg = merge_config(config)
    stations = stations or stations_for_simulation(cfg['city'], cfg)

    dst = simulation_dir(session)
    dst.mkdir(parents=True, exist_ok=True)

    (dst / STATIONS_NAME).write_text(
        json.dumps(stations, ensure_ascii=False, indent=2),
        encoding='utf-8')
    (dst / CONFIG_NAME).write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')

    # 清掉上次残留的标记，免得新跑的一开始就被当成已完成
    for marker in (SUCCESS_MARKER, FAILED_MARKER):
        try:
            (dst / marker).unlink()
        except FileNotFoundError:
            pass

    p = mp.Process(target=_run_hysplit_gaussian_job,
                   kwargs=dict(stations=stations, config=cfg,
                               session=session),
                   daemon=False)
    p.start()
    return session


def _run_hysplit_gaussian_job(stations: list, config: dict, session: str):
    """后台工作进程：准备文件 -> 跑模型 -> 后处理 -> 写标记。"""
    dst = simulation_dir(session)
    started = time.time()

    log_path = dst / LOG_NAME
    log_file = open(log_path, 'w', encoding='utf-8')

    def log(msg: str):
        line = f'[{datetime.now().strftime("%H:%M:%S")}] {msg}'
        print(line)
        log_file.write(line + '\n')
        log_file.flush()

    def finish(status: str, note: str):
        elapsed = time.time() - started
        tail = f'finished at {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}, ' \
            f'total {elapsed:.1f}s'
        text = f'{note}\n{tail}\n' if note else f'{tail}\n'
        (dst / status).write_text(text, encoding='utf-8')
        log(f'[{status}] {text.strip()}')

    log(f'HYSPLIT Gaussian job start: {session}')
    try:
        # 1) 释放点
        points = build_points(stations, config)
        if not points:
            finish(FAILED_MARKER, '失败：没有可用的监测点作为释放点')
            return
        if sum(p['mass'] for p in points) <= 0:
            finish(FAILED_MARKER,
                   '失败：所有监测点读数都是空的，没有有效释放质量')
            return

        # 2) 气象文件
        year, month, day = (int(config['year']), int(config['month']),
                            int(config['day']))
        met_dir, met_name = resolve_met_file(year, month, day)
        if met_dir is None:
            finish(FAILED_MARKER,
                   f'失败：找不到气象文件 {met_name}，'
                   f'请确认 conf/simulation.yml 里的 weatherData 目录')
            return
        log(f'met file: {met_dir / met_name}')

        # 3) 输入文件（SETUP.CFG 带的是 initd = 3 的高斯模型配置）
        prepare_files(dst, points, config, met_dir, met_name)
        log(f'prepared {len(points)} release point(s)')

        # 4) 跑模型。hycs_std 自己从当前目录读 CONTROL / SETUP.CFG
        r = _run_exe(HYSPLIT_EXEC / 'hycs_std.exe', [], dst, log)
        if r is None or r.returncode != 0:
            finish(FAILED_MARKER, '失败：hycs_std 没能正常结束')
            return
        if not (dst / CDUMP_NAME).is_file():
            finish(FAILED_MARKER, f'失败：没有生成 {CDUMP_NAME}')
            return

        # 5) 后处理：画图 + 出浓度文本
        _run_exe(HYSPLIT_EXEC / 'concplot.exe', [
            '+g1', '-81', f'-i./{CDUMP_NAME}', '-oconcplot.html',
            f'-j{_win(HYSPLIT_GRAPHICS / "arlmap")}',
            '-f0', '-b100', '-t100', '-e0', '-d1', '-r1', '-c0', '-k1',
            '-m0', '-s1', '-x1.0', '-y1.0', '-z50', '-u', '-a0',
            '-:', '-:', '-:', '-:', '-:',
        ], dst, log)

        _run_exe(HYSPLIT_EXEC / 'con2asc.exe',
                 [f'-i./{CDUMP_NAME}', '-oconcentration.txt'], dst, log)

        # 6) 出帧图 + frames.json
        #    传 year 进去，才能把 con2asc 的「年内第几天」换算成真实日期
        n_frames = collect_and_generate_images(
            dst, year=int(config.get('year') or 0) or None)
        if not n_frames:
            finish(FAILED_MARKER, '失败：后处理没有产出任何浓度帧')
            return

        finish(SUCCESS_MARKER, f'完成，共 {n_frames} 帧')

    except Exception as e:
        log('EXCEPTION:\n' + traceback.format_exc())
        finish(FAILED_MARKER, f'失败：{type(e).__name__}: {e}')
    finally:
        log_file.close()


# %%
# ---- 查询 ----


def _read_json(p: Path, default=None):
    try:
        return json.loads(Path(p).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


def list_hysplit_gaussian_simulations() -> list:
    """所有会话的概览，新的排在前面。

    v_min / v_max 一并带出：选历史结果时要先让用户看到这场的量程，
    才知道致伤 / 致死阈值该定在哪。
    """
    if not SIMULATION_DIR.is_dir():
        return []

    entries = []
    for d in SIMULATION_DIR.iterdir():
        if not d.is_dir():
            continue
        status, note = simulation_status(d)
        frames = _read_json(d / FRAMES_NAME, {}) or {}
        entries.append({
            'session': d.name,
            'status': status,
            'note': note,
            'n_frames': int(frames.get('n_frames') or 0),
            'v_min': frames.get('v_min'),
            'v_max': frames.get('v_max'),
            'created': datetime.fromtimestamp(d.stat().st_mtime).strftime(
                '%Y-%m-%d %H:%M:%S'),
        })

    return sorted(entries, key=lambda e: e['session'], reverse=True)


def get_hysplit_gaussian_simulation_template(session: str) -> str:
    """把该次模拟实际用的 CONTROL 传回去（前端可查看原文）。"""
    try:
        dst = simulation_dir(session)
    except ValueError:
        return ''
    p = dst / CONTROL_NAME
    if not p.is_file():
        return ''
    try:
        return p.read_text(encoding='utf-8')
    except OSError:
        return ''


def build_environment(dst: Path, config: dict, stations: list) -> dict:
    """前端画图需要的环境信息：城市、经纬度框、监测点、气象来源。"""
    year = int(config.get('year') or 0)
    month = int(config.get('month') or 0)
    day = int(config.get('day') or 0)
    met_name = met_file_name(
        year, month, day) if year and month and day else ''
    met_dir, _ = resolve_met_file(year, month, day) if met_name else (None, '')

    release_points = []
    for p in build_points(stations, config):
        release_points.append({
            'station_id': p['station_id'],
            'sensor_id': p['sensor_id'],
            'name': p['name'],
            'lon': round(p['lon'], 4),
            'lat': round(p['lat'], 4),
            'height': p['height'],
            'mass': p['mass'],
        })

    city = resolve_city(config.get('city'))
    bbox = config.get('bbox') if isinstance(config.get('bbox'), dict) else None
    if not bbox:
        bbox = city_bbox(city) if config.get('city') else LEGACY_BBOX

    return {
        **{k: float(bbox[k]) for k in ('lat1', 'lat2', 'lon1', 'lon2')},
        'city': city if config.get('city') else '',
        'city_center': config.get('city_center') or city_center(city),
        'top_height': float(config.get('top_height') or 0),
        'release_height': float(config.get('release_height') or 0),
        'year': year, 'month': month, 'day': day,
        'start_hour': int(config.get('start_hour') or 0),
        'duration_hours': int(config.get('duration_hours') or 0),
        'met_file': met_name,
        'met_dir': str(met_dir) if met_dir else '',
        'met_available': met_dir is not None,
        'weather_mode': config.get('weather_mode', 'file'),
        'release_points': release_points,
        'stations': build_station_marks(stations),
    }


def get_hysplit_gaussian_simulation_result(session: str) -> dict:
    """一次模拟的完整状态。结构对齐拉格朗日模型的 result 接口。"""
    out = {
        'session': session,
        'exists': False,
        'status': 'missing',
        'note': '',
        'files': [],
        'frames': [],
        'n_frames': 0,
        'config': {},
        'environment': {},
        'template_name': CONTROL_NAME,
        'template': '',
        'gif': None,
        'v_min': None,
        'v_max': None,
    }

    try:
        dst = simulation_dir(session)
    except ValueError:
        out['note'] = '非法的 session'
        return out

    if not dst.is_dir():
        return out

    out['exists'] = True
    out['status'], out['note'] = simulation_status(dst)
    out['files'] = sorted(p.name for p in dst.iterdir() if p.is_file())

    config = _read_json(dst / CONFIG_NAME, {}) or {}
    out['config'] = config

    stations = read_stations(dst)

    frames_doc = _read_json(dst / FRAMES_NAME, {}) or {}
    out['frames'] = frames_doc.get('frames') or []
    out['n_frames'] = int(frames_doc.get('n_frames') or len(out['frames']))
    out['v_min'] = frames_doc.get('v_min')
    out['v_max'] = frames_doc.get('v_max')

    if (dst / GIF_NAME).is_file():
        out['gif'] = GIF_NAME

    out['template'] = get_hysplit_gaussian_simulation_template(session)
    out['environment'] = build_environment(dst, config, stations)

    return out


# %%
