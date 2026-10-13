"""事故教育页面的图表数据准备。

两件事：

1. 「造成损失及危害」列是一段中文描述，用逗号/顿号/句号等标点切成若干小段，
   每段按关键词判断说的是死亡还是受伤，段里出现的数字就是人数。
2. 「泄漏气体」列同一类气体写法五花八门（后面常带括号注释），
   按关键字归成有限的几类，才能做饼图。

最后拼成 ECharts 的 option 字典，页面直接丢给 ui.echart。
"""
from __future__ import annotations

import html
import re


# ---------------------------------------------------------------- 伤亡人数

# 分段标点：中英文逗号、顿号、分号、句号、冒号、叹号、问号。
# 不切空格——「8 人死亡」里的空格不能把数字和人分开。
_SEG_SPLIT = re.compile(r'[，,、。．.；;：:！!？?]+')

# 段内取第一个数字
_NUM = re.compile(r'\d+(?:\.\d+)?')

# 同段里死亡和受伤关键词都出现时，按死亡算
_DEATH_KEYS = ('死亡',)
_INJURY_KEYS = ('伤', '中毒', '昏迷')
# 这些段讲的是财物损失，不能当伤亡人数
_NON_PERSON_KEYS = ('经济', '损失', '万元', '元', '设备', '损毁',
                    '建筑', '房屋', '财产', '管道', '管路')


def _num(seg: str) -> int:
    m = _NUM.search(seg)
    return int(float(m.group())) if m else 0


def parse_casualties(text) -> tuple[int, int]:
    """从「造成损失及危害」文本里抠出 (死亡人数, 受伤人数)。

    没写数字的（比如「多人中毒」）算 0——数不出来就不硬编。
    """
    if text is None:
        return 0, 0
    deaths = injured = 0
    for seg in _SEG_SPLIT.split(str(text)):
        seg = seg.strip()
        if not seg:
            continue
        if any(k in seg for k in _NON_PERSON_KEYS):
            continue
        if any(k in seg for k in _DEATH_KEYS):
            deaths += _num(seg)
        elif any(k in seg for k in _INJURY_KEYS):
            injured += _num(seg)
    return deaths, injured


# ---------------------------------------------------------------- 气体归类

# 一行里可能写好几种气体（「二氧化硫（SO2）、一氧化碳（CO）有毒烟气」），
# 按位置上最先出现的那一种归类，比固定优先级更贴近原文。
_GAS_RULES = (
    ('高炉煤气', ('高炉',)),
    ('转炉煤气', ('转炉',)),
    ('焦炉煤气', ('焦炉',)),
    ('一氧化碳', ('一氧化碳', 'CO')),
    ('硫化氢', ('硫化氢', 'H2S')),
    ('二氧化硫', ('二氧化硫', 'SO2')),
    ('氮气', ('氮气',)),
    ('氨气', ('氨',)),
    ('煤气', ('煤气',)),
)


def gas_category(name) -> str:
    """把五花八门的「泄漏气体」写法归到一个主类别上。"""
    s = str(name or '').strip()
    if not s:
        return '未标注'
    # 「混合煤气」必然是多个厂的煤气混在一起，单独一类
    if '混合煤气' in s:
        return '混合煤气'
    best = None  # (位置, 规则序号, 类别)
    for order, (label, keys) in enumerate(_GAS_RULES):
        pos = min((s.find(k) for k in keys if k in s), default=-1)
        if pos < 0:
            continue
        if best is None or (pos, order) < (best[0], best[1]):
            best = (pos, order, label)
    return best[2] if best else '其他气体'


# ---------------------------------------------------------------- 聚合

def casualty_points(df) -> list[dict]:
    """每起事故一条散点：[死亡人数, 受伤人数]。"""
    points = []
    for _, row in df.iterrows():
        deaths, injured = parse_casualties(row.get('造成损失及危害'))
        points.append({
            'name': str(row.get('案例名称') or ''),
            'value': [deaths, injured],
            'case': str(row.get('案例编号') or ''),
            'gas': str(row.get('泄漏气体') or ''),
            'lossharm': str(row.get('造成损失及危害') or ''),
        })
    return points


def gas_counts(df) -> list[tuple[str, int]]:
    """按主类别统计起数，从多到少。"""
    counts: dict[str, int] = {}
    for v in df['泄漏气体'] if '泄漏气体' in df.columns else []:
        label = gas_category(v)
        counts[label] = counts.get(label, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


# ---------------------------------------------------------------- 配色

_TEXT = '#dbe4f4'
_MUTED = '#8fa3c8'
_LINE = '#3a5a8f'
_GRID = 'rgba(58, 90, 143, 0.35)'
_PALETTE = ['#4ea8de', '#7ee2a0', '#ffd75e', '#ff9b9b', '#c4a5ff',
            '#5ee6d0', '#ffb26b', '#8fa3c8', '#f6a6c1', '#a3d977']
_FONT = "'Helvetica Neue', Arial, 'Microsoft YaHei', sans-serif"


def _axis(name: str) -> dict:
    return {
        'type': 'value',
        'name': name,
        'min': 0,
        'minInterval': 1,
        'nameTextStyle': {'color': _MUTED, 'fontSize': 12},
        'axisLabel': {'color': _MUTED},
        'axisLine': {'lineStyle': {'color': _LINE}},
        'splitLine': {'lineStyle': {'color': _GRID}},
    }


def scatter_option(points: list[dict]) -> dict:
    """死亡人数-受伤人数 散点图。

    tooltip 的 HTML 在这里预编码进每个点的 name；ECharts 会把字符串模板
    插值里的 HTML 全部转义，所以富文本 tooltip 必须挂真函数——
    NiceGUI 的 echart 支持 ":key" 写法，前端会把它 eval 成真正的函数。
    """
    data = []
    for p in points:
        deaths, injured = p['value']
        tip = (
            f"<b>{html.escape(p['name'] or p['case'] or '事故')}</b><br/>"
            f"死亡：{deaths} 人　受伤：{injured} 人<br/>"
            f"泄漏气体：{html.escape(p['gas'])}<br/>"
            f"{html.escape(p['lossharm'])}"
        )
        data.append({'name': tip, 'value': [deaths, injured]})

    return {
        'backgroundColor': 'transparent',
        'textStyle': {'fontFamily': _FONT},
        'title': {
            'text': '事故伤亡分布',
            'subtext': f'共 {len(points)} 起事故　x=死亡人数　y=受伤人数',
            'left': 'center',
            'textStyle': {'color': _TEXT, 'fontSize': 15, 'fontWeight': 'bold'},
            'subtextStyle': {'color': _MUTED, 'fontSize': 11},
        },
        'tooltip': {
            'trigger': 'item',
            # 字符串模板会被转义，这里挂真函数、直接吐预编码好的 HTML
            ':formatter': '(p) => p.data.name',
            'backgroundColor': '#10233f',
            'borderColor': _LINE,
            'textStyle': {'color': _TEXT, 'fontSize': 12},
            'extraCssText': 'max-width:320px; white-space:normal;',
        },
        'grid': {'left': 62, 'right': 30, 'top': 76, 'bottom': 52},
        'xAxis': _axis('死亡人数'),
        'yAxis': _axis('受伤人数'),
        'series': [{
            'type': 'scatter',
            'symbolSize': 14,
            'itemStyle': {'color': '#ffd75e', 'opacity': 0.75,
                          'borderColor': '#ffb26b', 'borderWidth': 1},
            'emphasis': {'itemStyle': {'opacity': 1, 'borderWidth': 2}},
            'data': data,
            'label': {'show': False},
        }],
    }


def pie_option(counts: list[tuple[str, int]]) -> dict:
    """泄漏气体构成饼图。"""
    # 只用于标题里的「共 N 起」；筛选到空集时要如实显示 0
    total = sum(c for _, c in counts)
    return {
        'backgroundColor': 'transparent',
        'textStyle': {'fontFamily': _FONT},
        'title': {
            'text': '泄漏气体构成',
            'subtext': f'共 {total} 起事故　按主类别归并',
            'left': 'center',
            'textStyle': {'color': _TEXT, 'fontSize': 15, 'fontWeight': 'bold'},
            'subtextStyle': {'color': _MUTED, 'fontSize': 11},
        },
        'color': _PALETTE,
        'tooltip': {
            'trigger': 'item',
            'backgroundColor': '#10233f',
            'borderColor': _LINE,
            'textStyle': {'color': _TEXT, 'fontSize': 12},
            'formatter': '{b}<br/>{c} 起（{d}%）',
        },
        'legend': {
            'type': 'scroll',
            'orient': 'vertical',
            'right': 8,
            'top': 'middle',
            'itemWidth': 10,
            'itemHeight': 10,
            # 每次重建都把所有类别设回选中：筛选后类别会变，
            # 不显式重置的话上一次手动取消的图例会继续残留
            'selected': {k: True for k, _ in counts},
            'textStyle': {'color': _MUTED, 'fontSize': 12},
            'pageTextStyle': {'color': _MUTED},
            'pageIconColor': _MUTED,
            'pageIconInactiveColor': _LINE,
        },
        'series': [{
            'type': 'pie',
            'radius': ['36%', '64%'],
            'center': ['38%', '58%'],
            'avoidLabelOverlap': True,
            'itemStyle': {'borderColor': '#10233f', 'borderWidth': 2},
            'label': {
                'color': _TEXT,
                'fontSize': 12,
                'formatter': '{b}\n{c} 起',
            },
            'labelLine': {'lineStyle': {'color': _LINE}},
            'emphasis': {
                'label': {'fontSize': 13, 'fontWeight': 'bold'},
                'itemStyle': {'shadowBlur': 12,
                              'shadowColor': 'rgba(0, 0, 0, 0.45)'},
            },
            'data': [{'name': k, 'value': v} for k, v in counts],
        }],
    }
