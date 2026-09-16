# %%
"""HYSPLIT 向前追溯（后向浓度计算）。

甲方的说法：扩散时间（负数表示向前追溯）。CONTROL 里的模拟时长
写负数时，hycs_std 会沿时间轴向过去积分，浓度场给出的就是
「监测点这些空气在过去各时刻来自哪里」——已在真数据上验证
（hycs_std / concplot / con2asc 对负时长输出全部兼容）。

与拉格朗日前向（python/hysplit/）的差异只有三处：
    1. 会话目录落在 hysplitBackward/simulation/，历史列表分开；
    2. duration_hours 默认负值；
    3. 不写 EMITIMES：CONTROL 里的一次性释放即可触发后向计算
       （SETUP.CFG 里 efile 指向的 EMITIMES 缺失只会记一条无害
       WARNING，实测不影响结果）；后向的 EMITIMES 负时长格式
       存在不确定性，没必要冒这个险。

CONTROL 拼装、帧图/浓度表生成、状态判定这些纯逻辑直接复用
python/hysplit/ 里的实现，两边不会漂移。

产物组织与拉格朗日模型一致：一次模拟 = 一个会话目录

    hysplitBackward/simulation/<YYYY-MM-DD-HH-MM-SS-UUID>/
"""
import json
import time
import uuid
import traceback
import multiprocessing as mp
from datetime import datetime, timedelta
from pathlib import Path

from hysplit.mk_control import (
    mk_control, met_file_name, weather_data_folder,
    generate_meteorology_files_for_period,
)
from hysplit.mk_images import collect_and_generate_images
from hysplit.simulate import (
    build_points,
    simulation_status,
    _run_exe,
    _met_dir_for_control,
    MET_DIR_CANDIDATES,
    DEFAULT_CONFIG as FORWARD_DEFAULT_CONFIG,
    DEFAULT_BBOX,
    BBOX_LAT1, BBOX_LAT2, BBOX_LON1, BBOX_LON2,
    TEMPLATE_DIR as FORWARD_TEMPLATE_DIR,
    HYSPLIT_EXEC, HYSPLIT_GRAPHICS,
    SESSION_TS_FMT,
    CONFIG_NAME, SENSORS_NAME, SUCCESS_MARKER, FAILED_MARKER,
    FRAMES_NAME, TABLE_NAME, IMG_DIR, GIF_NAME, LOG_NAME,
    CONTROL_NAME, CDUMP_NAME,
)

# %%
# python/hysplit_backward/simulate.py -> python/hysplit_backward -> python -> <root>
PROJECT_ROOT = Path(__file__).resolve().parents[2]
HYSPLIT_BACKWARD_DIR = PROJECT_ROOT / 'hysplitBackward'
SIMULATION_DIR = HYSPLIT_BACKWARD_DIR / 'simulation'

#: SETUP.CFG / ASCDATA.CFG 与前向模型完全一样，直接用 hysplit/template/
TEMPLATE_DIR = FORWARD_TEMPLATE_DIR

#: 从模板复制进会话目录的配置文件
COPIED_TEMPLATES = ('SETUP.CFG', 'ASCDATA.CFG')

DEFAULT_CONFIG = {
    **FORWARD_DEFAULT_CONFIG,
    # 追溯场景默认从 12 点起往回追 12 小时（气象库只有 may24.w1，
    # 这个窗口正好完整落在里面）。
    'start_hour': 12,
    'duration_hours': -12,
}


# %%
# ---- 会话目录 ----


def mk_hysplit_backward_session() -> str:
    """会话名：YYYY-MM-DD-HH-MM-SS-<uuid>，与其他模型一致。"""
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

    注意：duration_hours 是负数也要能传进来，所以这里不能简单
    判 falsy，必须只挡 None。
    """
    merged = dict(DEFAULT_CONFIG)
    if config:
        for k, v in config.items():
            if v is not None:
                merged[k] = v
    return merged


# %%
# ---- 气象文件（后向要覆盖整段时间，可能跨周文件）----


def resolve_met_files_backward(year: int, month: int, day: int,
                               start_hour: int, duration_hours: int):
    """推出后向时段 [start+duration, start] 覆盖的所有 gdas1 周文件。

    返回 (files, missing)：
        files   = [(目录(带尾分隔符), 文件名), ...] 按时间顺序、已去重
        missing = 缺的第一个文件名，全齐时为 None
    """
    start_dt = datetime(year, month, day, int(start_hour or 0))
    needed = generate_meteorology_files_for_period(
        start_datetime=start_dt, duration_hours=int(duration_hours))
    # generate_... 返回的是 (base_dir, filename)；base_dir 只是候选之一，
    # 这里只保留文件名，按候选目录逐个找。
    names = [n for _, n in needed]

    conf_dir = weather_data_folder()
    candidates = []
    if conf_dir:
        candidates.append(Path(conf_dir))
    candidates += [Path(p) for p in MET_DIR_CANDIDATES]

    files = []
    missing = None
    seen = set()
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        found = None
        for d in candidates:
            try:
                if (d / name).is_file():
                    found = d
                    break
            except OSError:
                continue
        if found is None:
            missing = name
            break
        files.append((_met_dir_for_control(found), name))

    return files, missing


# %%
# ---- 输入文件 ----


def prepare_files(dst: Path, points: list, config: dict, met_files: list):
    """把一次追溯需要的输入文件全部写进会话目录。"""
    dst = Path(dst)
    dst.mkdir(parents=True, exist_ok=True)

    for name in COPIED_TEMPLATES:
        src = TEMPLATE_DIR / name
        if src.is_file():
            (dst / name).write_bytes(src.read_bytes())

    year = int(config['year'])
    month = int(config['month'])
    day = int(config['day'])
    start_hour = int(config['start_hour'])
    duration_hours = int(config['duration_hours'])

    # CONTROL：时长为负数即后向计算。一次性释放（type 3），
    # 不写 EMITIMES（原因见模块 docstring）。
    control_content = mk_control(
        points=points,
        year=year,
        month=month,
        day=day,
        meteorology_files=met_files,
        start_hour=start_hour,
        duration_hours=duration_hours,
        top_height=float(config.get('top_height') or 10000.0),
        output_dir='./',
        output_file=CDUMP_NAME,
        output_interval_minutes=int(
            config.get('output_interval_minutes') or 100),
    )
    (dst / CONTROL_NAME).write_text(control_content + '\n', encoding='utf-8')

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


# %%
# ---- 跑模型 ----


def simulate_with_hysplit_backward(sensors: list, session: str = None,
                                   config: dict = None) -> str:
    """起一次向前追溯计算（后台进程），立刻返回 session。"""
    session = session or mk_hysplit_backward_session()
    cfg = merge_config(config)

    dst = simulation_dir(session)
    dst.mkdir(parents=True, exist_ok=True)

    (dst / SENSORS_NAME).write_text(
        json.dumps(sensors or [], ensure_ascii=False, indent=2),
        encoding='utf-8')
    (dst / CONFIG_NAME).write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')

    for marker in (SUCCESS_MARKER, FAILED_MARKER):
        try:
            (dst / marker).unlink()
        except FileNotFoundError:
            pass

    p = mp.Process(target=_run_hysplit_backward_job,
                   kwargs=dict(sensors=sensors or [], config=cfg,
                               session=session),
                   daemon=False)
    p.start()
    return session


def _run_hysplit_backward_job(sensors: list, config: dict, session: str):
    """后台工作进程：准备文件 -> 跑模型 -> 后处理 -> 写标记。"""
    dst = simulation_dir(session)
    started = time.time()

    log_file = open(dst / LOG_NAME, 'w', encoding='utf-8')

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

    log(f'HYSPLIT backward job start: {session}')
    try:
        # 1) 释放点（即追溯起点，通常是监测到污染的传感器位置）
        points = build_points(sensors, config)
        if not points:
            finish(FAILED_MARKER, '失败：没有可用的传感器作为追溯起点')
            return
        if sum(p['mass'] for p in points) <= 0:
            finish(FAILED_MARKER,
                   '失败：所有传感器读数都是空的，没有有效释放质量')
            return

        # 2) 气象文件：要覆盖整段回溯时间，可能不止一个周文件
        year, month, day = (int(config['year']), int(config['month']),
                            int(config['day']))
        met_files, missing = resolve_met_files_backward(
            year, month, day,
            int(config.get('start_hour') or 0),
            int(config.get('duration_hours') or 0))
        if not met_files:
            finish(FAILED_MARKER,
                   f'失败：找不到气象文件 {missing or "?"}，'
                   f'请确认 conf/simulation.yml 里的 weatherData 目录')
            return
        log('met files: ' + ', '.join(n for _, n in met_files))

        # 3) 输入文件
        prepare_files(dst, points, config, met_files)
        log(f'prepared {len(points)} origin point(s)')

        # 4) 跑模型（CONTROL 时长为负 -> hycs_std 沿时间轴向过去积分）
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

        # 6) 出帧图 + frames.json（帧时刻是回溯窗口里的真实过去时刻）
        n_frames = collect_and_generate_images(
            dst, year=int(config.get('year') or 0) or None)
        if not n_frames:
            finish(FAILED_MARKER, '失败：后处理没有产出任何浓度帧')
            return

        finish(SUCCESS_MARKER, f'完成，向前追溯 {n_frames} 帧')

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


def list_hysplit_backward_simulations() -> list:
    """所有追溯会话的概览，新的排在前面（带量程）。"""
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


def get_hysplit_backward_simulation_template(session: str) -> str:
    """把该次追溯实际用的 CONTROL 传回去（前端可查看原文）。"""
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
    """前端画图需要的环境信息：经纬度框、追溯起点、气象来源。"""
    year = int(config.get('year') or 0)
    month = int(config.get('month') or 0)
    day = int(config.get('day') or 0)
    met_name = met_file_name(
        year, month, day) if year and month and day else ''

    release_points = []
    for p in build_points(sensors, config):
        release_points.append({
            'sensor_id': p['sensor_id'],
            'lon': round(p['lon'], 4),
            'lat': round(p['lat'], 4),
            'height': p['height'],
            'mass': p['mass'],
        })

    duration = int(config.get('duration_hours') or 0)
    return {
        **DEFAULT_BBOX,
        'top_height': float(config.get('top_height') or 0),
        'release_height': float(config.get('release_height') or 0),
        'year': year, 'month': month, 'day': day,
        'start_hour': int(config.get('start_hour') or 0),
        'duration_hours': duration,
        'backward': duration < 0,
        'met_file': met_name,
        'weather_mode': config.get('weather_mode', 'file'),
        'release_points': release_points,
    }


def get_hysplit_backward_simulation_result(session: str) -> dict:
    """一次追溯的完整状态。结构对齐拉格朗日模型的 result 接口。"""
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

    out['template'] = get_hysplit_backward_simulation_template(session)
    out['environment'] = build_environment(dst, config, sensors)

    return out


# %%
