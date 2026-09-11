# %%
"""HYSPLIT 拉格朗日模型的模拟调度。

产物组织与 FDS 保持一致：一次模拟 = 一个会话目录

    hysplit/simulation/<YYYY-MM-DD-HH-MM-SS-UUID>/

会话名里带 UUID，避免同一秒内两次模拟互相覆盖。
完成判定不再看 generated.gif，而是看 success / failed 标记文件
（generated.gif 仍然是产物之一，但只是产物，不作为状态依据）。

会话目录内容：
    config.json      本次运行参数（含界面上填的气象条件，存档用）
    sensors.json     本次用的传感器与读数
    CONTROL          主输入卡（= FDS 那边 template.fds 的对应物）
    EMITIMES         释放源文件
    SETUP.CFG        HYSPLIT 设置（从 hysplit/template/ 复制）
    ASCDATA.CFG      地形设置（从 hysplit/template/ 复制）
    concplot.bat / conctxt.bat   后处理命令（存档，便于手工复跑）
    cdump            模型输出
    concentration.txt_*          后处理出的浓度文本
    img/{day:03d}-{hr:02d}.png   逐时次帧图
    frames.json      帧清单
    table.json       点表
    generated.gif    动图
    success / failed 状态标记
    run.log          运行日志

关于气象条件（重要）：
    HYSPLIT 的流场完全来自气象文件（gdas1.*），不读界面上的
    温度/湿度/风力/风向。所以界面上的气象输入对计算结果没有影响，
    只是随运行一起存档。要真正让这些输入参与计算，得把配置里的
    weather_mode 切到 manual 并合成气象文件（见 synth_met 模块）。
"""
import json
import time
import uuid
import subprocess
import traceback
import multiprocessing as mp
from datetime import datetime
from pathlib import Path

from .mk_control import mk_control, mk_emitimes, met_file_name, weather_data_folder
from .mk_images import collect_and_generate_images

# %%
# python/hysplit/simulate.py -> python/hysplit -> python -> <root>
PROJECT_ROOT = Path(__file__).resolve().parents[2]
HYSPLIT_DIR = PROJECT_ROOT / 'hysplit'
SIMULATION_DIR = HYSPLIT_DIR / 'simulation'
TEMPLATE_DIR = HYSPLIT_DIR / 'template'

HYSPLIT_HOME = Path('C:/hysplit')
HYSPLIT_EXEC = HYSPLIT_HOME / 'exec'
HYSPLIT_GRAPHICS = HYSPLIT_HOME / 'graphics'

SESSION_TS_FMT = '%Y-%m-%d-%H-%M-%S'

CONFIG_NAME = 'config.json'
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

#: 从 hysplit/template/ 复制进会话目录的配置文件
COPIED_TEMPLATES = ('SETUP.CFG', 'ASCDATA.CFG')

#: 气象数据目录候选。conf/simulation.yml 里配的那个优先，
#: 取不到或里面没有需要的文件时按这个列表兜底找。
MET_DIR_CANDIDATES = ('D:/WeatherData', 'E:/WeatherData')

#: 计算域（经纬度框）。HYSPLIT 的释放点都落在这个框里。
DEFAULT_BBOX = {'lat1': 30.0, 'lat2': 31.0, 'lon1': 110.0, 'lon2': 111.0}

#: 传感器归一化坐标 -> 经纬度时用的框（与 DEFAULT_BBOX 保持一致）
BBOX_LAT1, BBOX_LAT2 = 30.0, 31.0
BBOX_LON1, BBOX_LON2 = 110.0, 111.0

WEATHER_OPTIONS = ['晴', '多云', '阴', '雨', '雪', '雾']
WIND_DIRECTIONS = ['北', '东北', '东', '东南', '南', '西南', '西', '西北']

LOCATION_CANDIDATES = {
    '北京': {'lat': 39.9042, 'lon': 116.4074, 'zoom': 4},
    '上海': {'lat': 31.2304, 'lon': 121.4737, 'zoom': 4},
    '武威': {'lat': 37.9282, 'lon': 102.6346, 'zoom': 4},
    '张掖': {'lat': 38.9259, 'lon': 100.4498, 'zoom': 4},
}

DEFAULT_CONFIG = {
    # ---- 界面上的地理 / 气象（气象部分不参与计算，随运行存档）----
    'location': '北京',
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
    'weather_mode': 'file',      # file=用 gdas1 气象文件；manual=由界面输入合成
}

# %%
# ---- 会话目录 ----


def mk_hysplit_session() -> str:
    """会话名：YYYY-MM-DD-HH-MM-SS-<uuid>，与 FDS 一致。"""
    now = datetime.now()
    return '-'.join([now.strftime(SESSION_TS_FMT), str(uuid.uuid4())])


def simulation_dir(session: str) -> Path:
    """会话名 -> 目录。挡掉路径穿越。"""
    s = str(session or '').strip()
    if not s or any(c in s for c in ('/', '\\', '..')):
        raise ValueError(f'非法 session: {session!r}')
    return SIMULATION_DIR / s


def merge_config(config: dict = None) -> dict:
    """界面传来的 config 与默认值合并。None 值不覆盖默认值。"""
    merged = dict(DEFAULT_CONFIG)
    if config:
        for k, v in config.items():
            if v is not None:
                merged[k] = v
    return merged


# %%
# ---- 气象文件定位 ----


def resolve_met_file(year: int, month: int, day: int):
    """找出该日期需要的 gdas1 气象文件。

    返回 (目录, 文件名)；找不到目录时目录为 None。
    """
    name = met_file_name(year, month, day)

    candidates = []
    conf_dir = weather_data_folder()
    if conf_dir:
        candidates.append(Path(conf_dir))
    candidates += [Path(p) for p in MET_DIR_CANDIDATES]

    seen = set()
    for d in candidates:
        key = str(d).lower()
        if key in seen:
            continue
        seen.add(key)
        try:
            if (d / name).is_file():
                return d, name
        except OSError:
            continue

    return None, name


# %%
# ---- 输入文件 ----


def build_points(sensors: list, config: dict) -> list:
    """传感器 -> HYSPLIT 释放点（经纬度 + 质量）。

    质量取传感器读数，读数为空的点质量记 0。
    """
    height = float(config.get('release_height') or 10.0)
    points = []
    for s in sensors or []:
        try:
            x = float(s['x_position'])
            y = float(s['y_position'])
        except (KeyError, TypeError, ValueError):
            continue
        value = s.get('value')
        try:
            mass = 100.0 * float(value)
        except (TypeError, ValueError):
            mass = 0.0
        points.append({
            'sensor_id': s.get('sensor_id', ''),
            'height': height,
            'mass': round(mass, 6),
            'lon': BBOX_LON1 + x * (BBOX_LON2 - BBOX_LON1),
            'lat': BBOX_LAT1 + (1 - y) * (BBOX_LAT2 - BBOX_LAT1),
            'gas': 'Gas',
        })
    return points


def prepare_files(dst: Path, points: list, config: dict, met_dir: Path,
                  met_name: str):
    """把一次模拟需要的输入文件全部写进会话目录。"""
    dst = Path(dst)
    dst.mkdir(parents=True, exist_ok=True)

    # 模板配置原样复制进会话目录，保证目录自包含
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
    """CONTROL 里的气象目录必须以路径分隔符结尾，否则 HYSPLIT 找不到文件。

    这就是为什么之前配 conf 时写的是 "E:/WeatherData/"（带斜杠）。
    """
    s = str(met_dir)
    return s if s.endswith(('\\', '/')) else s + '\\'


# %%
# ---- 跑模型 ----


def _run_exe(exe: Path, args: list, cwd: Path, log):
    """跑一个 exe 并把结果写进日志。返回 CompletedProcess 或 None。"""
    exe = Path(exe)
    if not exe.is_file():
        log(f'[skip] 找不到 {exe}')
        return None

    cmd = [str(exe)] + [str(a) for a in args]
    log(f'[run ] {exe.name} {" ".join(str(a) for a in args)}')
    try:
        r = subprocess.run(cmd, cwd=str(cwd),
                           capture_output=True, text=True)
    except OSError as e:
        log(f'[fail] {exe.name} 启动失败: {e}')
        return None

    log(f'[ret ] {exe.name} rc={r.returncode}')
    if r.stdout and r.stdout.strip():
        log('  stdout: ' + r.stdout.strip()[:2000])
    if r.stderr and r.stderr.strip():
        log('  stderr: ' + r.stderr.strip()[:2000])
    return r


def simulate_with_hysplit(sensors: list, session: str = None,
                          config: dict = None) -> str:
    """起一次 HYSPLIT 模拟（后台进程），立刻返回 session。"""
    session = session or mk_hysplit_session()
    cfg = merge_config(config)

    dst = simulation_dir(session)
    dst.mkdir(parents=True, exist_ok=True)

    (dst / SENSORS_NAME).write_text(
        json.dumps(sensors or [], ensure_ascii=False, indent=2),
        encoding='utf-8')
    (dst / CONFIG_NAME).write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')

    # 清掉上次残留的标记，免得新跑的一开始就被当成已完成
    for marker in (SUCCESS_MARKER, FAILED_MARKER):
        try:
            (dst / marker).unlink()
        except FileNotFoundError:
            pass

    p = mp.Process(target=_run_hysplit_job,
                   kwargs=dict(sensors=sensors or [], config=cfg,
                               session=session),
                   daemon=False)
    p.start()
    return session


def _run_hysplit_job(sensors: list, config: dict, session: str):
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

    log(f'HYSPLIT job start: {session}')
    try:
        # 1) 释放点
        points = build_points(sensors, config)
        if not points:
            finish(FAILED_MARKER, '失败：没有可用的传感器作为释放点')
            return
        if sum(p['mass'] for p in points) <= 0:
            finish(FAILED_MARKER,
                   '失败：所有传感器读数都是空的，没有有效释放质量')
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

        # 3) 输入文件
        prepare_files(dst, points, config, met_dir, met_name)
        log(f'prepared {len(points)} release point(s)')

        # 4) 跑模型。hycs_std 自己从当前目录读 CONTROL
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


def simulation_status(dst: Path):
    """读标记文件判断状态。返回 (status, note)。"""
    dst = Path(dst)
    for marker, status in ((SUCCESS_MARKER, 'success'),
                           (FAILED_MARKER, 'failed')):
        f = dst / marker
        if f.is_file():
            try:
                note = f.read_text(encoding='utf-8').strip()
            except OSError:
                note = ''
            return status, note
    return 'pending', ''


def _read_json(p: Path, default=None):
    try:
        return json.loads(Path(p).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


def list_hysplit_simulations() -> list:
    """所有会话的概览，新的排在前面。"""
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
            'created': datetime.fromtimestamp(d.stat().st_mtime).strftime(
                '%Y-%m-%d %H:%M:%S'),
        })

    return sorted(entries, key=lambda e: e['session'], reverse=True)


def get_hysplit_simulation_result_history() -> list:
    """旧接口：只要会话名列表。保留是为了兼容老调用方。"""
    return [e['session'] for e in list_hysplit_simulations()]


def get_hysplit_simulation_template(session: str) -> str:
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


def build_environment(dst: Path, config: dict, sensors: list) -> dict:
    """前端画图需要的环境信息：经纬度框、释放点、气象来源。"""
    year = int(config.get('year') or 0)
    month = int(config.get('month') or 0)
    day = int(config.get('day') or 0)
    met_name = met_file_name(year, month, day) if year and month and day else ''
    met_dir, _ = resolve_met_file(year, month, day) if met_name else (None, '')

    release_points = []
    for p in build_points(sensors, config):
        release_points.append({
            'sensor_id': p['sensor_id'],
            'lon': round(p['lon'], 4),
            'lat': round(p['lat'], 4),
            'height': p['height'],
            'mass': p['mass'],
        })

    return {
        **DEFAULT_BBOX,
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
    }


def get_hysplit_simulation_result(session: str) -> dict:
    """一次模拟的完整状态。结构对齐 FDS 的 result 接口。"""
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

    sensors = _read_json(dst / SENSORS_NAME, []) or []

    frames_doc = _read_json(dst / FRAMES_NAME, {}) or {}
    out['frames'] = frames_doc.get('frames') or []
    out['n_frames'] = int(frames_doc.get('n_frames') or len(out['frames']))
    out['v_min'] = frames_doc.get('v_min')
    out['v_max'] = frames_doc.get('v_max')

    if (dst / GIF_NAME).is_file():
        out['gif'] = GIF_NAME

    out['template'] = get_hysplit_simulation_template(session)
    out['environment'] = build_environment(dst, config, sensors)

    return out


# %%
