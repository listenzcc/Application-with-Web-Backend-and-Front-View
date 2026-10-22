# %%
"""城市监测点与监测数据（与 sensors 库解绑）。

旧做法：HYSPLIT 的释放点来自 `db/sensor_data.db` 里的传感器，坐标是归一化
的 x/y，再按固定的 30~31°N / 110~111°E 框换算成经纬度。这套映射有两个
问题：换城市后传感器位置和地图对不上；传感器库一改，扩散计算结果也跟着变。

现在城市是一等公民：
    * 每个城市自带一套监测点，用真实经纬度（相对城市中心的 km 偏移定义，
      按纬度做经度压缩），名字是站点名；
    * 监测数据由本模块按「城市 + 站点 + 时段」确定性生成，缓存在
      data/stations/<slug>.json，页面上可查看、可重新生成；
    * HYSPLIT 三个模型只读这里的监测点，不再碰 sensors 库。

数据是模拟的，但生成规则固定：每个站点有基线噪声，泄漏点附近的站点在
泄漏时段叠加一个高斯形状的抬升。同一个城市同一个时段重复读，结果一致；
点「重新生成」才会换一组。
"""
import json
import math
import random
from datetime import datetime, timedelta
from pathlib import Path

# python/hysplit/stations.py -> python/hysplit -> python -> <root>
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = PROJECT_ROOT / 'data' / 'stations'

#: 1 度纬度对应的公里数（经度按 cos(lat) 压缩）
KM_PER_DEG_LAT = 111.32

#: 计算域相对城市中心的半宽（度）。与旧的 1°x1° 域同尺寸，
#: 保证 HYSPLIT 浓度网格与后处理表现和以前一致。
BBOX_HALF_DEG = 0.5


# %%
# ---- 城市预设 ----
# 站点偏移量单位是公里，dx 向东为正、dy 向北为正。
# kind 只用于展示分组：厂区 / 厂界 / 敏感点。

CITIES = {
    '北京': {
        'slug': 'beijing',
        'lat': 39.9042, 'lon': 116.4074, 'zoom': 9,
        'desc': '华北平原 · 石化园区',
        'stations': [
            ('BJ-01', '储罐区北', 0.0, 2.4, '厂区'),
            ('BJ-02', '装卸车台', 1.6, 1.1, '厂区'),
            ('BJ-03', '装置区东', 2.5, -0.4, '厂区'),
            ('BJ-04', '污水处理场', -1.5, -1.7, '厂区'),
            ('BJ-05', '园区西门', -2.6, 0.9, '厂界'),
            ('BJ-06', '北厂界', 0.7, 3.6, '厂界'),
            ('BJ-07', '办公生活区', 0.5, -3.1, '敏感点'),
            ('BJ-08', '下风向 3km', 3.7, -2.7, '敏感点'),
        ],
    },
    '北京bj': {
        'slug': 'beijing',
        'lat': 39.9042, 'lon': 116.4074, 'zoom': 9,
        'desc': '华北平原 · 石化园区',
        'stations': [
            ('BJ-01', '储罐区北a', 0.0, 2.4, '厂区'),
            ('BJ-02', '装卸车台a', 1.6, 1.1, '厂区'),
            ('BJ-03', '装置区东a', 2.5, -0.4, '厂区'),
            ('BJ-04', '污水处理场a', -1.5, -1.7, '厂区'),
            ('BJ-05', '园区西门a', -2.6, 0.9, '厂界'),
            ('BJ-06', '北厂界a', 0.7, 3.6, '厂界'),
            ('BJ-07', '办公生活区a', 0.5, -3.1, '敏感点'),
            ('BJ-08', '下风向 3kma', 3.7, -2.7, '敏感点'),
        ],
    },
    '上海': {
        'slug': 'shanghai',
        'lat': 31.2304, 'lon': 121.4737, 'zoom': 9,
        'desc': '长江口 · 化工区',
        'stations': [
            ('SH-01', '乙烯装置区', 0.0, 2.0, '厂区'),
            ('SH-02', '罐区南', 1.3, -0.8, '厂区'),
            ('SH-03', '码头作业区', 2.8, 1.6, '厂区'),
            ('SH-04', '火炬区', -1.2, 1.4, '厂区'),
            ('SH-05', '西厂界', -3.0, -0.5, '厂界'),
            ('SH-06', '东厂界', 3.6, -1.8, '厂界'),
            ('SH-07', '滨海社区', 1.0, -3.4, '敏感点'),
            ('SH-08', '下风向 4km', 4.2, -3.0, '敏感点'),
        ],
    },
    '南京': {
        'slug': 'nanjing',
        'lat': 32.0603, 'lon': 118.7969, 'zoom': 9,
        'desc': '长江北岸 · 新材料园区',
        'stations': [
            ('NJ-01', '芳烃装置', 0.0, 2.2, '厂区'),
            ('NJ-02', '罐区东', 1.8, 0.6, '厂区'),
            ('NJ-03', '装卸区', -1.4, 1.9, '厂区'),
            ('NJ-04', '污水处理', -0.9, -2.2, '厂区'),
            ('NJ-05', '南厂界', 0.6, -3.5, '厂界'),
            ('NJ-06', '西厂界', -3.1, -0.8, '厂界'),
            ('NJ-07', '临江居民点', 2.9, -2.9, '敏感点'),
        ],
    },
    '武威': {
        'slug': 'wuwei',
        'lat': 37.9282, 'lon': 102.6346, 'zoom': 9,
        'desc': '河西走廊 · 工业园区',
        'stations': [
            ('WW-01', '中心装置区', 0.0, 1.5, '厂区'),
            ('WW-02', '储罐区', 1.7, -0.6, '厂区'),
            ('WW-03', '北厂界', -0.4, 3.2, '厂界'),
            ('WW-04', '东厂界', 3.3, 0.9, '厂界'),
            ('WW-05', '生活区', -2.6, -1.8, '敏感点'),
            ('WW-06', '下风向 2km', 1.2, -3.3, '敏感点'),
        ],
    },
    '张掖': {
        'slug': 'zhangye',
        'lat': 38.9259, 'lon': 100.4498, 'zoom': 9,
        'desc': '河西走廊 · 绿洲边缘',
        'stations': [
            ('ZY-01', '装置区北', 0.0, 1.8, '厂区'),
            ('ZY-02', '罐区', 1.5, -1.0, '厂区'),
            ('ZY-03', '南厂界', -0.3, -3.0, '厂界'),
            ('ZY-04', '西厂界', -2.9, 0.4, '厂界'),
            ('ZY-05', '东侧村舍', 3.1, 1.2, '敏感点'),
            ('ZY-06', '下风向 2km', 2.4, -2.6, '敏感点'),
        ],
    },
}

DEFAULT_CITY = '北京'

#: 监测读数单位（相对体积分数，与 build_points 的 mass = 100 * value 对应）
VALUE_UNIT = '相对体积分数（0~1）'


# %%
# ---- 城市 / 站点几何 ----


def city_names() -> list:
    return list(CITIES.keys())


def _preset(city: str) -> dict:
    """取城市预设，名字不认识就退回默认城市。"""
    return CITIES.get(str(city or '').strip()) or CITIES[DEFAULT_CITY]


def resolve_city(city: str) -> str:
    """把可能的脏输入收敛成合法城市名。"""
    name = str(city or '').strip()
    return name if name in CITIES else DEFAULT_CITY


def offset_to_lonlat(lat0: float, lon0: float, dx_km: float, dy_km: float):
    """以 (lat0, lon0) 为原点，向东 dx_km、向北 dy_km 的经纬度。"""
    lat = lat0 + dy_km / KM_PER_DEG_LAT
    lon = lon0 + dx_km / \
        (KM_PER_DEG_LAT * max(math.cos(math.radians(lat0)), 1e-6))
    return round(lat, 5), round(lon, 5)


def city_stations(city: str) -> list:
    """城市的监测点（真实经纬度）。每次调用现算，不缓存可变对象。"""
    preset = _preset(city)
    lat0, lon0 = preset['lat'], preset['lon']
    out = []
    for sid, name, dx, dy, kind in preset['stations']:
        lat, lon = offset_to_lonlat(lat0, lon0, dx, dy)
        out.append({
            'station_id': sid,
            'name': name,
            'kind': kind,
            'lat': lat,
            'lon': lon,
            'dx_km': dx,
            'dy_km': dy,
        })
    return out


def city_center(city: str) -> dict:
    preset = _preset(city)
    return {'lat': preset['lat'], 'lon': preset['lon'], 'zoom': preset['zoom']}


def city_bbox(city: str, half_deg: float = BBOX_HALF_DEG) -> dict:
    """城市计算域。前端地图与结果页都用它当参考框。"""
    preset = _preset(city)
    lat, lon = preset['lat'], preset['lon']
    return {
        'lat1': round(lat - half_deg, 4),
        'lat2': round(lat + half_deg, 4),
        'lon1': round(lon - half_deg, 4),
        'lon2': round(lon + half_deg, 4),
    }


def city_info(city: str) -> dict:
    """城市概览，给页面和 /get_city_stations 用。"""
    name = resolve_city(city)
    preset = _preset(name)
    return {
        'city': name,
        'slug': preset['slug'],
        'desc': preset.get('desc', ''),
        'center': city_center(name),
        'bbox': city_bbox(name),
        'station_count': len(city_stations(name)),
    }


# %%
# ---- 监测数据生成 ----


def _window_key(year: int, month: int, day: int, start_hour: int,
                duration_hours: int) -> str:
    return f'{year:04d}-{month:02d}-{day:02d}T{start_hour:02d}+{duration_hours}'


def _parse_window(config: dict) -> dict:
    """从 config 里取出时段。缺项用默认值兜住，避免页面半填时炸掉。"""
    def _int(key, default):
        try:
            v = int(config.get(key))
        except (TypeError, ValueError):
            return default
        return v

    year = _int('year', 2024)
    month = _int('month', 5)
    day = _int('day', 2)
    start_hour = min(max(_int('start_hour', 0), 0), 23)
    duration = _int('duration_hours', 24)
    if duration == 0:
        duration = 24
    return {
        'year': year, 'month': month, 'day': day,
        'start_hour': start_hour, 'duration_hours': duration,
    }


def _hour_labels(window: dict, n: int) -> list:
    """按起始时刻推 n 个小时标签（跨日用 datetime 算，不手搓进位）。"""
    t0 = datetime(window['year'], window['month'], window['day'],
                  window['start_hour'])
    return [(t0 + timedelta(hours=i)).strftime('%m-%d %H:00')
            for i in range(n)]


def _make_series(rng: random.Random, n: int, leak_hour: float,
                 amplitude: float, width: float) -> list:
    """单站时序：基线 + 高斯形状的泄漏抬升 + 噪声。"""
    base = rng.uniform(0.02, 0.06)
    phase = rng.uniform(0, 2 * math.pi)
    values = []
    for h in range(n):
        drift = 0.008 * math.sin(2 * math.pi * h / 12.0 + phase)
        bump = amplitude * math.exp(-((h - leak_hour) ** 2) / (2 * width ** 2))
        v = base + drift + bump + rng.gauss(0, 0.006)
        values.append(round(min(max(v, 0.002), 0.999), 4))
    return values


def generate_monitoring(city: str, config: dict = None, refresh: bool = False,
                        seed_extra: str = '') -> dict:
    """生成（或从缓存读出）一个城市的监测数据。

    缓存键 = 城市 + 时段；时段变了自动重算。refresh=True 换一组随机数，
    对应页面上的「重新生成」。
    """
    config = config or {}
    name = resolve_city(city)
    preset = _preset(name)
    window = _parse_window(config)
    key = _window_key(**window)

    cache_path = CACHE_DIR / f"{preset['slug']}.json"
    if not refresh and cache_path.is_file():
        try:
            cached = json.loads(cache_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            cached = None
        if cached and cached.get('window_key') == key:
            return cached

    # 负时长（追溯模型）用绝对值决定时序长度
    n = abs(int(window['duration_hours'])) + 1
    n = min(max(n, 2), 241)

    seed = f"{preset['slug']}|{key}|{datetime.now().timestamp() if refresh else ''}" \
        f"|{seed_extra}"
    rng = random.Random(seed)

    stations = city_stations(name)
    # 泄漏位置取某个站点，附近站点受影响的幅度按距离衰减
    leak_idx = rng.randrange(len(stations))
    leak = stations[leak_idx]
    leak_hour = rng.uniform(1.0, max(1.5, n - 2.0))

    labels = _hour_labels(window, n)
    records = []
    for st in stations:
        dist = math.hypot(st['dx_km'] - leak['dx_km'],
                          st['dy_km'] - leak['dy_km'])
        # 5 km 外基本不受影响；峰值幅度 0.35 ~ 0.9
        influence = math.exp(-(dist ** 2) / (2 * 2.6 ** 2))
        amplitude = (0.35 + rng.uniform(0.0, 0.45)) * influence
        if st['station_id'] == leak['station_id']:
            amplitude = max(amplitude, 0.55)
        width = rng.uniform(1.6, 3.2)
        values = _make_series(rng, n, leak_hour, amplitude, width)
        peak = max(values)
        records.append({
            'station_id': st['station_id'],
            'name': st['name'],
            'kind': st['kind'],
            'lat': st['lat'],
            'lon': st['lon'],
            'value': values[0],
            'peak': peak,
            'peak_hour': values.index(peak),
            'series': values,
        })

    doc = {
        'city': name,
        'slug': preset['slug'],
        'desc': preset.get('desc', ''),
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'window_key': key,
        'window': window,
        'labels': labels,
        'peak_hour_label': labels[min(int(leak_hour), n - 1)],
        'unit': VALUE_UNIT,
        'center': city_center(name),
        'bbox': city_bbox(name),
        'stations': records,
    }

    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2),
                              encoding='utf-8')
    except OSError:
        pass  # 写不了缓存不影响页面显示

    return doc


def monitoring(city: str, config: dict = None, refresh: bool = False) -> dict:
    """页面用的入口：读缓存 / 重算，并补齐便于展示的字段。"""
    doc = generate_monitoring(city, config, refresh=refresh)
    # 最新读数 = 时序最后一个点（模拟时段结束时），比第一个点更符合「当前」
    for s in doc['stations']:
        s['latest'] = s['series'][-1] if s['series'] else s['value']
        s['value'] = s['latest']
    doc['n_hours'] = len(doc.get('labels') or [])
    doc['max_latest'] = max((s['value'] for s in doc['stations']), default=0.0)
    return doc


def stations_for_simulation(city: str, config: dict = None,
                            refresh: bool = False) -> list:
    """给 HYSPLIT 用的释放点输入（带真实经纬度和释放强度）。

    释放强度取该站点在模拟时段内的**峰值读数**：HYSPLIT 的 CONTROL 一次
    释放只能给一个污染物速率，用峰值折算才反映「这一小时的泄漏量」，
    用起始时刻读数会因为泄漏还没发生而算成 0。
    """
    doc = monitoring(city, config, refresh=refresh)
    return [{
        'station_id': s['station_id'],
        'name': s['name'],
        'kind': s['kind'],
        'lat': s['lat'],
        'lon': s['lon'],
        'value': s['peak'],
    } for s in doc['stations']]


# %%
if __name__ == '__main__':
    for cname in city_names():
        doc = monitoring(cname, {'year': 2024, 'month': 5, 'day': 2,
                                 'start_hour': 0, 'duration_hours': 24})
        print(f"{cname:4s} {doc['slug']:9s} {len(doc['stations'])} 站 "
              f"峰值 {max(s['peak'] for s in doc['stations']):.3f} "
              f"最新最大 {doc['max_latest']:.3f} "
              f"域 {doc['bbox']}")
