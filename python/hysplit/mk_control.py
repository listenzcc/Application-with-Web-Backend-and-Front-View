from pathlib import Path
from datetime import datetime


def mk_emitimes(points: list, year: int, month: int, day: int, hour: int, minute: int, duration_hours: int, duration_minutes: int):
    records = len(points)
    lines = []

    lines.extend([
        'YYYY MM DD HH DURATION(hhhh) RECORDS',
        'YYYY MM DD HH MM DURATION(hhmm) LAT LON HGT(m) RATE(/h) AREA(m2) HEAT(w)'
    ])

    lines.append(
        # YYYY   MM          DD        HH         DURATION(hhhh)      RECORDS
        f'{year} {month:02d} {day:02d} {hour:04d} {duration_hours:04d} {records:04d}',
    )

    for pnt in points:
        lat = pnt['lat']
        lon = pnt['lon']
        height = pnt['height']
        mass = pnt['mass']
        area = pnt.get('area', 0)
        heat = pnt.get('heat', 0)
        lines.append(
            # YYYY   MM          DD        HH         MM           DURATION(hhmm)                           LAT   LON   HGT(m)   RATE(/h) AREA(m2) HEAT(w)
            f'{year} {month:02d} {day:02d} {hour:02d} {minute:02d} {duration_hours:02d}{duration_minutes:02d} {lat} {lon} {height} {mass} {area} {heat}',
        )

    return '\n'.join(lines)


def mk_control(points: list, year: int, month: int, day: int,
               meteorology_dir: str = "D:/WeatherData/",
               meteorology_files: list = None,
               start_hour: int = 0,
               duration_hours: int = -6,
               top_height: float = 10000.0,
               output_dir: str = "./",
               output_file: str = "cdump",
               vertical_method: int = 0):
    """
    生成HYSPLIT CONTROL文件

    参数:
    ----------
    points : list of dict
        每个点包含以下键:
        - 'lat': 纬度 (float)
        - 'lon': 经度 (float)
        - 'height': 释放高度(m) (float)
        - 'mass': 释放量 (float)
        - 'gas': 污染物标识符 (str)
        - 'name': 点名称 (str, 可选)
    year : int
        年份，如 2024
    month : int
        月份，1-12
    day : int
        日期，1-31
    meteorology_dir : str
        气象数据目录（当meteorology_files为None时使用）
    meteorology_files : list of tuple
        气象文件列表，格式: [(路径1, 文件1), (路径2, 文件2), ...]
    start_hour : int
        起始小时 (0-23)
    duration_hours : int
        模拟时长（负值表示后向轨迹）
    top_height : float
        模型顶层高度 (m)
    output_dir : str
        输出目录
    output_file : str
        输出文件名
    vertical_method : int
        垂直运动计算方法 (0=气象数据垂直速度, 1=等熵, 2=等密度面)

    返回:
    ----------
    str : CONTROL文件内容
    """

    # 格式检查
    if not (1 <= month <= 12):
        raise ValueError(f"月份必须在1-12之间，当前: {month}")
    if not (1 <= day <= 31):
        raise ValueError(f"日期必须在1-31之间，当前: {day}")
    if not (0 <= start_hour <= 23):
        raise ValueError(f"起始小时必须在0-23之间，当前: {start_hour}")

    # 起始时间字符串 (YY MM DD HH)
    start_time = f"{year % 100:02d} {month:02d} {day:02d} {start_hour:02d}"
    # 释放时间字符串 (YY MM DD HH MM)
    release_time = f"{year % 100:02d} {month:02d} {day:02d} {start_hour:02d} 00"

    # 构建CONTROL文件内容
    lines = []

    # 1. 起始时间
    lines.append(start_time)

    # 2. 轨迹数量（点数）
    lines.append(str(len(points)))

    # 3. 各点坐标
    for point in points:
        lines.append(
            f"{point['lat']:.3f} {point['lon']:.3f}   {point['height']:.0f}")

    # 4. 模拟时长（小时）
    lines.append(str(duration_hours))

    # 5. 垂直运动计算方法
    lines.append(str(vertical_method))

    # 6. 模型顶层高度 (m)
    lines.append(f"{top_height:.1f}")

    # 7. 气象文件数量
    if meteorology_files:
        lines.append(str(len(meteorology_files)))
        # 8-... 气象文件路径和名称
        for path, filename in meteorology_files:
            lines.append(path)
            lines.append(filename)
    else:
        # 使用默认气象文件命名规则
        # 月份缩写
        month_abbr = ["jan", "feb", "mar", "apr", "may", "jun",
                      "jul", "aug", "sep", "oct", "nov", "dec"]
        # 计算周数（基于1号开始）
        week_num = (day - 1) // 7 + 1
        week_num = min(week_num, 5)  # 最多5周

        meteorology_file = f"gdas1.{month_abbr[month-1]}{year % 100:02d}.w{week_num}"

        lines.append("1")  # 气象文件数量
        lines.append(meteorology_dir)
        lines.append(meteorology_file)

    # 污染物种类数量（等于点数）
    lines.append(str(len(points[:1])))

    # 各污染物标识符
    for point in points[:1]:
        lines.append(point['gas'])

    # 各污染物释放量
    for point in points[:1]:
        lines.append(str(point['mass']))

    # 释放时间分布（3=一次性释放）
    lines.append("3")

    # 释放时间
    lines.append(release_time)

    # 释放点数量
    lines.append(str(len(points[:1])))

    # 固定参数部分
    lines.extend([
        "0.0   0.0",          # 释放网格偏移
        "0.05 0.05",          # 释放网格间距
        "30 30",              # 释放网格点数
        output_dir,           # 输出目录
        output_file,          # 输出文件名
        "1",                  # 输出时间平均选项
        "100",                # 输出时间间隔（分钟）
        "00 00 00 00 00",     # 采样开始时间
        "00 00 00 00 00",     # 采样结束时间
        "00 01 00",           # 浓度网格设置
        "1",                  # 浓度网格数量
        "0.0 0.0 0.0",        # 浓度网格间距
        "0.0 0.0 0.0 0.0 0.0",  # 垂直层次设置
        "0.0 0.0 0.0",        # 其他参数
        "0.0",                # 平滑参数
        "0.0"                 # 保留字段
    ])

    return "\n".join(lines)


def generate_meteorology_files_for_period(start_datetime: datetime,
                                          duration_hours: int,
                                          base_dir: str = "D:/WeatherData/"):
    """
    根据模拟时段自动生成所需的气象文件列表

    参数:
    ----------
    start_datetime : datetime
        起始时间
    duration_hours : int
        模拟时长（可为负值）
    base_dir : str
        气象数据基础目录

    返回:
    ----------
    list : 气象文件列表 [(路径, 文件名), ...]
    """

    month_abbr = ["jan", "feb", "mar", "apr", "may", "jun",
                  "jul", "aug", "sep", "oct", "nov", "dec"]

    # 计算结束时间
    if duration_hours < 0:  # 后向轨迹
        end_datetime = start_datetime
        start_datetime = start_datetime + timedelta(hours=duration_hours)
    else:  # 前向轨迹
        end_datetime = start_datetime + timedelta(hours=duration_hours)

    # 确保起始时间早于结束时间
    if start_datetime > end_datetime:
        start_datetime, end_datetime = end_datetime, start_datetime

    # 计算所需周数（HYSPLIT气象数据按周存储）
    files_needed = []
    current_date = start_datetime

    while current_date <= end_datetime:
        year_short = current_date.year % 100
        month = current_date.month
        day = current_date.day

        # 计算周数（基于1号开始）
        week_num = (day - 1) // 7 + 1
        week_num = min(week_num, 5)  # 最多5周

        filename = f"gdas1.{month_abbr[month-1]}{year_short:02d}.w{week_num}"
        files_needed.append((base_dir, filename))

        # 移动到下一周
        current_date += timedelta(days=7)

    # 去重
    unique_files = []
    seen = set()
    for path, filename in files_needed:
        if filename not in seen:
            seen.add(filename)
            unique_files.append((path, filename))

    return unique_files


# 使用示例
if __name__ == "__main__":
    from datetime import datetime, timedelta

    # 示例1：基本用法
    points = [
        {
            'lat': 32.03,
            'lon': 118.46,
            'height': 10,
            'mass': 100.0,
            'gas': 'Cl',
            'name': '南京'
        },
        {
            'lat': 31.23,
            'lon': 121.47,
            'height': 10,
            'mass': 100.0,
            'gas': 'Cl',
            'name': '上海'
        }
    ]

    # 生成CONTROL文件
    control_content = mk_control(
        points=points,
        year=2024,
        month=5,    # 5月
        day=2,      # 2日
        start_hour=0,
        duration_hours=24,  # 24小时后向轨迹
        meteorology_dir="D:/WeatherData/",
        output_dir="./output/",
        output_file="trajectory_20240502"
    )

    # 保存文件
    with open("CONTROL_multi.txt", "w", encoding="utf-8") as f:
        f.write(control_content)

    print("CONTROL文件已生成")
    print("-" * 50)
    print(control_content[:500])  # 打印前500字符预览

    # 示例2：使用多个气象文件（长时间模拟）
    print("\n" + "="*50)
    print("示例2：长时间模拟，自动计算所需气象文件")

    start_dt = datetime(2024, 5, 2, 0)
    meteorology_files = generate_meteorology_files_for_period(
        start_datetime=start_dt,
        duration_hours=-72,  # 3天后向轨迹
        base_dir="D:/WeatherData/"
    )

    print(f"所需气象文件: {len(meteorology_files)} 个")
    for path, filename in meteorology_files:
        print(f"  {path}{filename}")

    # 生成CONTROL文件
    control_content2 = mk_control(
        points=points,
        year=2024,
        month=5,
        day=2,
        meteorology_files=meteorology_files,
        start_hour=0,
        duration_hours=-72,
        output_file="trajectory_3day"
    )

    with open("CONTROL_3day.txt", "w", encoding="utf-8") as f:
        f.write(control_content2)

    print("\nCONTROL文件已生成: CONTROL_3day.txt")

    # 示例3：不同高度的释放点
    print("\n" + "="*50)
    print("示例3：不同高度的释放点")

    points_multi_height = [
        {'lat': 32.03, 'lon': 118.46, 'height': 10,
            'mass': 100, 'gas': 'A', 'name': '南京-10m'},
        {'lat': 32.03, 'lon': 118.46, 'height': 100,
            'mass': 100, 'gas': 'A', 'name': '南京-100m'},
        {'lat': 32.03, 'lon': 118.46, 'height': 500,
            'mass': 100, 'gas': 'A', 'name': '南京-500m'},
        {'lat': 32.03, 'lon': 118.46, 'height': 1000,
            'mass': 100, 'gas': 'A', 'name': '南京-1000m'},
    ]

    control_content3 = mk_control(
        points=points_multi_height,
        year=2024,
        month=6,
        day=15,
        start_hour=12,
        duration_hours=-12,
        output_file="vertical_profile"
    )

    with open("CONTROL_vertical.txt", "w", encoding="utf-8") as f:
        f.write(control_content3)

    print("垂直剖面CONTROL文件已生成")
