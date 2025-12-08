# sensors_ui.py
from nicegui import ui, app
from datetime import datetime, timedelta
import asyncio

from .sensor_reader import SensorDataReader


class SensorsUI:
    def __init__(self, data_reader):
        self.auto_refresh = True
        self.reader = data_reader
        self.current_page = 1
        self.page_size = 10
        self.selected_sensor = None
        self.refresh_interval = 5  # 自动刷新间隔（秒）

    async def create_sensors_page(self):
        """创建传感器页面"""
        # 页面标题
        with ui.row().classes('w-full'):
            ui.label('传感器管理系统').classes('text-2xl font-bold')
            ui.space()
            with ui.row().classes('items-center'):
                ui.button('刷新数据', icon='refresh',
                          on_click=self.refresh_data).classes('bg-green-500')
                ui.button('添加传感器', icon='add', on_click=self.show_add_sensor_dialog).classes(
                    'bg-blue-500')

        # 主内容区域
        with ui.row().classes('w-full p-4'):
            # 左侧 - 传感器列表
            with ui.column().classes('w-full'):
                # 搜索和筛选区域
                with ui.row().classes('w-full items-center mb-4 gap-4'):
                    self.search_input = ui.input(
                        placeholder='搜索传感器ID...',
                        on_change=self.filter_sensors
                    ).classes('w-64')

                    # self.time_filter = ui.select(
                    #     options=[
                    #         {'label': '最近1小时', 'value': 60},
                    #         {'label': '最近6小时', 'value': 360},
                    #         {'label': '最近24小时', 'value': 1440},
                    #         {'label': '最近7天', 'value': 10080},
                    #         {'label': '所有数据', 'value': 0}
                    #     ],
                    #     value=60,
                    #     label='时间范围',
                    #     on_change=self.refresh_data
                    # ).classes('w-40')

                    ui.space()
                    ui.switch('自动刷新', value=True, on_change=self.toggle_auto_refresh).classes(
                        'ml-auto')
                    ui.label(f'刷新间隔: {self.refresh_interval}秒').classes(
                        'text-gray-500')

                # 传感器表格
                columns = [
                    {'name': 'sensor_id', 'label': '传感器ID',
                        'field': 'sensor_id', 'sortable': True, 'align': 'left'},
                    {'name': 'value', 'label': '当前值', 'field': 'value',
                        'sortable': True, 'align': 'center'},
                    {'name': 'position', 'label': '位置', 'field': 'position',
                        'sortable': False, 'align': 'center'},
                    {'name': 'timestamp', 'label': '更新时间', 'field': 'timestamp',
                        'sortable': True, 'align': 'center'},
                    {'name': 'status', 'label': '状态', 'field': 'status',
                        'sortable': True, 'align': 'center'},
                    {'name': 'actions', 'label': '操作', 'field': 'actions',
                        'sortable': False, 'align': 'center'}
                ]

                self.table = ui.table(
                    columns=columns,
                    rows=[],
                    row_key='sensor_id',
                    selection='single',
                    pagination={'rowsPerPage': 10},
                    on_select=self.on_sensor_select
                ).classes('w-full h-96').props('''
                    dense
                    flat
                    bordered
                    row-key="sensor_id"
                    :pagination.sync="pagination"
                    :rows-per-page-options="[10, 20, 50, 100]"
                ''')

                self.table.add_slot('body-cell-status', '''
                    <q-td key="status" :props="props">
                        <q-badge :color="props.value ==='在线'? 'green' : 'red'">
                            {{ props.value }}
                        </q-badge>
                    </q-td>
                ''')

            # 右侧 - 传感器详情和图表
            with ui.row().classes('w-full pl-6 border-l'):

                # 详情卡片
                with ui.card().classes('w-1/3 mb-6'):
                    ui.label('传感器详情').classes('text-xl font-bold mb-4')
                    with ui.column().classes('w-full'):
                        self.detail_id = ui.label(
                            '传感器ID: -').classes('text-lg font-semibold')
                        self.detail_value = ui.label(
                            '当前值: -').classes('text-2xl text-blue-600 font-bold')
                        with ui.row().classes('w-full'):
                            self.detail_position = ui.label(
                                '位置: -').classes('text-gray-600')
                            self.detail_status = ui.chip(
                                '离线', color='red').props('outline')

                        self.detail_last_update = ui.label(
                            '最后更新: -').classes('text-sm text-gray-500')

                        with ui.row().classes('w-full justify-end mt-2'):
                            ui.button('查看历史', icon='history',
                                      on_click=self.show_history).props('flat')
                            ui.button('编辑', icon='edit', on_click=self.show_edit_dialog).props(
                                'flat')
                            ui.button('删除', icon='delete', color='red',
                                      on_click=self.show_delete_dialog).props('flat')

                # 实时图表
                with ui.card().classes('w-1/2'):
                    ui.label('实时数据趋势').classes('text-xl font-bold mb-4')
                    # 这里可以使用echarts或plotly创建图表
                    # ui.label(
                    #     '图表区域 - 需要echarts扩展').classes('text-center text-gray-400')
                    # ui.linear_progress().props('indeterminate').classes('mt-2')

                    self.echart = ui.echart({
                        'xAxis': {
                            'type': 'category',
                            'name': '时间'
                        },
                        'yAxis': {
                            'type': 'value',
                            'name': '数值'
                        }
                    })

        # 初始化数据
        await self.refresh_data()

        # 启动自动刷新
        self.auto_refresh_task = asyncio.create_task(self.auto_refresh_loop())
        print(self.auto_refresh_task)

    async def load_sensor_data(self):
        """加载传感器数据"""
        try:
            # 获取传感器基本信息
            sensors = self.reader.get_sensor_info()

            # 获取每个传感器的最新数据
            latest_data = self.reader.get_latest_data()
            latest_dict = {data['sensor_id']: data for data in latest_data}

            # 准备表格数据
            rows = []
            for sensor in sensors:
                sensor_id = sensor['sensor_id']
                latest = latest_dict.get(sensor_id, {})

                # 判断传感器状态（基于最后更新时间）
                status = '在线'
                color = 'green'
                if 'timestamp' in latest:
                    last_update = datetime.fromisoformat(
                        latest['timestamp'].replace('Z', '+00:00'))
                    time_diff = datetime.now() - last_update
                    if time_diff > timedelta(minutes=5):
                        status = '离线'
                        color = 'red'
                    elif time_diff > timedelta(minutes=1):
                        status = '延迟'
                        color = 'orange'

                rows.append({
                    'sensor_id': sensor_id,
                    'value': f"{latest.get('value', 'N/A'):.2f}" if 'value' in latest else 'N/A',
                    'position': f"({sensor['x_position']:.1f}, {sensor['y_position']:.1f})",
                    'timestamp': latest.get('timestamp', 'N/A'),
                    'status': status,
                    '_status_color': color,
                    'actions': '--',
                    '_raw_data': {
                        'sensor': sensor,
                        'latest': latest
                    }
                })

            return rows

        except Exception as e:
            ui.notify(f'加载数据失败: {str(e)}', type='negative')
            return []

    def format_table_rows(self, rows):
        """格式化表格行，添加颜色和操作按钮"""
        formatted_rows = []
        for row in rows:
            formatted_row = row.copy()

            # 添加状态颜色
            if row['status'] == '在线':
                formatted_row['status'] = f'<span class="text-green-600">● {row["status"]}</span>'
            elif row['status'] == '延迟':
                formatted_row['status'] = f'<span class="text-orange-500">● {row["status"]}</span>'
            else:
                formatted_row['status'] = f'<span class="text-red-600">● {row["status"]}</span>'

            # 添加操作按钮（使用HTML）
            formatted_row['actions'] = f'''
                <div class="flex justify-center gap-2">
                    <button onclick="window.sensorDetail('{row["sensor_id"]}')" 
                            class="px-2 py-1 bg-blue-100 text-blue-600 rounded hover:bg-blue-200">
                        详情
                    </button>
                    <button onclick="window.sensorChart('{row["sensor_id"]}')" 
                            class="px-2 py-1 bg-green-100 text-green-600 rounded hover:bg-green-200">
                        图表
                    </button>
                </div>
            '''

            formatted_rows.append(formatted_row)

        return formatted_rows

    async def refresh_data(self):
        """刷新表格数据"""
        try:
            # 显示加载状态
            # ui.notify('正在刷新数据...', type='info', position='top')

            # 加载数据
            rows = await self.load_sensor_data()

            # 应用搜索筛选
            search_text = self.search_input.value.lower() if self.search_input.value else ''
            if search_text:
                rows = [r for r in rows if search_text in r['sensor_id'].lower()]

            # 格式化数据
            formatted_rows = self.format_table_rows(rows)

            # 更新表格
            self.table.rows = rows

            # 如果有选中的传感器，更新详情
            if self.selected_sensor:
                await self.update_sensor_detail(self.selected_sensor)

            # ui.notify(f'已更新 {len(rows)} 个传感器的数据', type='positive')

        except Exception as e:
            # ui.notify(f'刷新失败: {str(e)}', type='negative')
            pass

    async def on_sensor_select(self, event):
        """传感器选中事件"""
        if event.selection:
            sensor_id = event.selection[0]['sensor_id']
            self.selected_sensor = sensor_id
            await self.update_sensor_detail(sensor_id)

    async def update_sensor_detail(self, sensor_id):
        """更新传感器详情"""
        try:
            # 获取传感器信息
            sensors = self.reader.get_sensor_info()
            sensor_info = next(
                (s for s in sensors if s['sensor_id'] == sensor_id), None)

            if sensor_info:
                # 获取最新数据
                latest_data = self.reader.get_latest_data(sensor_id)
                latest = latest_data[0] if latest_data else {}

                # 更新详情显示
                self.detail_id.set_text(f'传感器ID: {sensor_id}')

                if 'value' in latest:
                    value = latest['value']
                    self.detail_value.set_text(f'当前值: {value:.2f}')

                    # 根据数值改变颜色
                    if value > 30:
                        self.detail_value.classes(
                            replace='text-red-600 text-2xl font-bold')
                    elif value > 25:
                        self.detail_value.classes(
                            replace='text-orange-500 text-2xl font-bold')
                    else:
                        self.detail_value.classes(
                            replace='text-green-600 text-2xl font-bold')

                self.detail_position.set_text(
                    f"位置: ({sensor_info['x_position']:.1f}, {sensor_info['y_position']:.1f})")

                if 'timestamp' in latest:
                    self.detail_last_update.set_text(
                        f'最后更新: {latest["timestamp"]}')

                    # 更新状态
                    last_update = datetime.fromisoformat(
                        latest['timestamp'].replace('Z', '+00:00'))
                    time_diff = datetime.now() - last_update

                    if time_diff <= timedelta(minutes=1):
                        self.detail_status.set_text('在线')
                        self.detail_status.props('color=green')
                    elif time_diff <= timedelta(minutes=5):
                        self.detail_status.set_text('延迟')
                        self.detail_status.props('color=orange')
                    else:
                        self.detail_status.set_text('离线')
                        self.detail_status.props('color=red')

                sensor_data = self.reader.get_recent_data(sensor_id)
                # 提取时间和数值数据
                times = []
                values = []

                if sensor_data:
                    # 假设每个传感器有多个历史数据点
                    for data_point in sensor_data:
                        # 时间数据（转换为合适格式）
                        timestamp = data_point.get('timestamp', '')
                        # 如果是datetime对象，转换为字符串
                        if hasattr(timestamp, 'strftime'):
                            time_str = timestamp.strftime('%H:%M:%S')
                        else:
                            time_str = str(timestamp)

                        times.append(time_str)
                        values.append(data_point.get('value', 0))

                self.echart.options['xAxis']['data'] = times
                self.echart.options['series'] = [{
                    'type': 'line',
                    'data': values,
                    'name': 'temp_001'
                }]
                self.echart.update()

        except Exception as e:
            ui.notify(f'更新详情失败: {str(e)}', type='negative')

    def filter_sensors(self):
        """过滤传感器"""
        self.refresh_data()

    def change_page(self, page):
        """切换页面"""
        if page > 0:
            self.current_page = page
            # 这里可以添加分页逻辑

    async def auto_refresh_loop(self):
        """自动刷新循环"""
        print('auto refresh started')
        while True:
            await asyncio.sleep(self.refresh_interval)
            if hasattr(self, 'auto_refresh') and self.auto_refresh:
                await self.refresh_data()

    def toggle_auto_refresh(self, event):
        """切换自动刷新"""
        self.auto_refresh = event.value

    def show_add_sensor_dialog(self):
        """显示添加传感器对话框"""
        with ui.dialog() as dialog, ui.card().classes('p-6 w-96'):
            ui.label('添加新传感器').classes('text-xl font-bold mb-4')

            sensor_id = ui.input('传感器ID').classes('w-full mb-4')
            x_position = ui.number('X坐标', value=0.0).classes('w-full mb-4')
            y_position = ui.number('Y坐标', value=0.0).classes('w-full mb-4')

            with ui.row().classes('w-full justify-end gap-2'):
                ui.button('取消', on_click=dialog.close)
                ui.button('添加', on_click=lambda: self.add_sensor(
                    sensor_id.value, x_position.value, y_position.value, dialog
                )).props('color=primary')

        dialog.open()

    async def add_sensor(self, sensor_id, x, y, dialog):
        """添加传感器"""
        if not sensor_id:
            ui.notify('请输入传感器ID', type='warning')
            return

        try:
            # 这里需要调用写入器添加传感器
            # writer.register_sensor(sensor_id, x, y)
            ui.notify(f'传感器 {sensor_id} 添加成功', type='positive')
            dialog.close()
            await self.refresh_data()
        except Exception as e:
            ui.notify(f'添加失败: {str(e)}', type='negative')

    def show_history(self):
        """显示历史数据"""
        if self.selected_sensor:
            ui.notify(f'显示 {self.selected_sensor} 的历史数据', type='info')
            # 这里可以打开历史数据对话框或跳转到历史页面

    def show_edit_dialog(self):
        """显示编辑对话框"""
        if self.selected_sensor:
            ui.notify(f'编辑 {self.selected_sensor}', type='info')

    def show_delete_dialog(self):
        """显示删除对话框"""
        if self.selected_sensor:
            ui.notify(f'删除 {self.selected_sensor}', type='warning')
