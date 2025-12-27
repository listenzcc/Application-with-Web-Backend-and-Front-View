# %%
import json
import contextlib
import pandas as pd

from typing import Optional
from pathlib import Path
from datetime import datetime
from omegaconf import OmegaConf

from nicegui import app, ui

from fastapi import Request
from fastapi.responses import RedirectResponse, FileResponse, HTMLResponse
from starlette.middleware.base import BaseHTTPMiddleware

from auth.models import RoleEnum
from auth.database import DatabaseManager
from auth.decorators import AuthContext
from auth.user_service import UserService
from auth.auth_manager import PermissionManager

from sensors.ui import SensorsUI
from sensors.sensor_reader import SensorDataReader
from sensors.sensor_writer import SensorDataWriter

from util.user_session_manager import UserSessionManager

from explorer.toxic_gas import ToxicGasDatabase

from components.layout import with_layout, with_layout_full_width

from fds.simulate import simulate_with_fds, get_fds_simulation_result_history

# %%
PROJECT = OmegaConf.load('conf/project.yml')
abstract = PROJECT['abstract']
abstract = abstract.replace('\n', '\n\n')

# %%
# Add static directory - This must be done BEFORE any UI elements
app.add_static_files('/static', 'static')  # URL path, local folder %%


# %%
# Gas explorer data
gas_db = ToxicGasDatabase()

# %%
# Cases
CASE_FOLDER = Path('./data/case')

# %%
# Accidents education
accidents_education_df = pd.read_excel('./data/accidents/a-20251221.xlsx')
accidents_education_df['案例场景分类'] = accidents_education_df['案例场景分类'].ffill()


# %%
# Auth system

# Auth db
# 1. 初始化数据库
db_manager = DatabaseManager('sqlite:///db/auth.db', echo=False)
db_manager.create_tables()
db_manager.initialize_data()

# 2. 创建服务实例
session = db_manager.get_session()
user_service = UserService(session)
permission_manager = PermissionManager(session)
auth_context = AuthContext(user_service, permission_manager)

try:
    # 3. 创建测试用户
    # 创建普通用户
    user1 = user_service.create_user(
        username="testuser",
        password="password123",
        role=RoleEnum.USER.value
    )

    # 创建访客
    guest = user_service.create_user(
        username="guest",
        password="guest123",
        role=RoleEnum.GUEST.value
    )
except:
    pass

# Auth middle ware
unrestricted_page_routes = {'/login', '/welcome', '/'}
session_manager = UserSessionManager()


# @app.add_middleware
# class AuthMiddleware(BaseHTTPMiddleware):
#     """This middleware restricts access to all NiceGUI pages.

#     It redirects the user to the login page if they are not authenticated.
#     """

#     async def dispatch(self, request: Request, call_next):
#         if not app.storage.user.get('authenticated', False):
#             if not request.url.path.startswith('/_nicegui') and request.url.path not in unrestricted_page_routes:
#                 return RedirectResponse(f'/login?redirect_to={request.url.path}')
#         return await call_next(request)

@app.add_middleware
class EnhancedAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self.user_sessions = {}  # {user_id: {sessions}}

    async def dispatch(self, request: Request, call_next):
        # 获取会话ID
        session_id = request.cookies.get('session_id')
        user_id = None

        if session_id and session_id in session_manager.active_sessions:
            # 更新活动时间
            session_manager.update_activity(session_id)
            user_data = session_manager.active_sessions[session_id]
            user_id = user_data.get('id')

            # 存储到请求状态
            request.state.user = user_data

        # 检查认证
        # if not user_id and not request.url.path.startswith('/_nicegui') \
        #    and request.url.path not in unrestricted_page_routes:
        #     return RedirectResponse(f'/login?redirect_to={request.url.path}')

        # 检查认证
        if not app.storage.user.get('authenticated', False):
            if not request.url.path.startswith('/_nicegui') and request.url.path not in unrestricted_page_routes:
                return RedirectResponse(f'/login?redirect_to={request.url.path}')

        response = await call_next(request)

        # 如果设置了新的会话，添加到cookie
        if hasattr(request.state, 'new_session_id'):
            response.set_cookie(
                key='session_id',
                value=request.state.new_session_id,
                httponly=True,
                max_age=3600 * 24  # 24小时
            )

        return response


class GasManagementUI:
    def __init__(self):
        self.current_df = None
        self.search_condition = "气体名称"
        self.search_value = ""
        self.toxicity_filter = ""
        self.sort_column = "气体名称"
        self.sort_ascending = True

        self.refresh_data()
        self.create_ui()

    def refresh_data(self):
        """刷新数据"""
        gases = gas_db.search_gases(
            condition=self.search_condition if self.search_value else None,
            value=self.search_value,
            toxicity_level=self.toxicity_filter if self.toxicity_filter else None
        )

        if gases:
            self.current_df = pd.DataFrame(gases)
            # 按列排序
            self.current_df = self.current_df.sort_values(
                by=self.sort_column,
                ascending=self.sort_ascending
            )
        else:
            self.current_df = pd.DataFrame()

    def on_search(self):
        """搜索按钮回调"""
        self.refresh_data()
        self.update_table()
        self.update_stats()

    def on_add_gas(self):
        """添加气体对话框"""
        with ui.dialog() as dialog, ui.card():
            ui.label('添加新气体').classes('text-h6')

            with ui.column():
                gas_name = ui.input('气体名称').classes('w-full')
                formula = ui.input('分子式').classes('w-full')
                cas_no = ui.input('CAS号').classes('w-full')
                mol_weight = ui.number('分子量', value=0.0).classes('w-full')
                toxicity = ui.select(
                    ['高毒', '中毒', '低毒'],
                    label='毒性等级'
                ).classes('w-full')
                boiling_pt = ui.number('沸点(℃)', value=0.0).classes('w-full')
                melting_pt = ui.number('熔点(℃)', value=0.0).classes('w-full')
                idlh = ui.input('IDLH浓度').classes('w-full')
                mac = ui.input('MAC浓度').classes('w-full')
                threshold1 = ui.input('安全阈值').classes('w-full')
                threshold2 = ui.input('警戒浓度').classes('w-full')
                threshold3 = ui.input('危险浓度').classes('w-full')

            with ui.row():
                ui.button('取消', on_click=dialog.close)
                ui.button('确认添加', on_click=lambda: self.add_gas_and_refresh(
                    {
                        '气体名称': gas_name.value,
                        '分子式': formula.value,
                        'CAS号': cas_no.value,
                        '分子量': mol_weight.value,
                        '毒性等级': toxicity.value,
                        '沸点_C': boiling_pt.value,
                        '熔点_C': melting_pt.value,
                        'IDLH浓度': idlh.value,
                        'MAC浓度': mac.value,
                        '安全阈值': threshold1.value,
                        '警戒浓度': threshold2.value,
                        '危险浓度': threshold3.value,
                    },
                    dialog
                ))

        dialog.open()

    def add_gas_and_refresh(self, gas_data, dialog):
        """添加气体并刷新界面"""
        if gas_db.add_gas(gas_data):
            dialog.close()
            self.refresh_data()
            self.update_table()
            self.update_stats()
            ui.notify(f"成功添加气体: {gas_data['气体名称']}")

    def on_delete_gas(self, formula):
        """删除气体"""
        with ui.dialog() as dialog, ui.card():
            ui.label(f'确认删除气体: {formula}?').classes('text-h6')

            with ui.row():
                ui.button('取消', on_click=dialog.close)
                ui.button('确认删除',
                          on_click=lambda: self.delete_gas_and_refresh(formula, dialog))

        dialog.open()

    def delete_gas_and_refresh(self, formula, dialog):
        """删除气体并刷新"""
        if gas_db.delete_gas(formula):
            dialog.close()
            self.refresh_data()
            self.update_table()
            self.update_stats()
            ui.notify(f"成功删除气体: {formula}")

    def update_table(self):
        """更新表格显示"""
        if self.current_df is not None and not self.current_df.empty:
            # 只显示需要的列，排除数据库内部字段
            display_df = self.current_df.copy()
            columns_to_show = [
                '气体名称', '分子式', 'CAS号', '分子量', '毒性等级',
                '沸点_C', '熔点_C', 'IDLH浓度', 'MAC浓度',
                '安全阈值', '警戒浓度', '危险浓度'
            ]

            # 确保列存在
            available_columns = [
                col for col in columns_to_show if col in display_df.columns]
            display_df = display_df[available_columns]

            # 重命名列显示
            # display_df = display_df.rename(columns={
            #     '沸点_C': '沸点(℃)',
            #     '熔点_C': '熔点(℃)'
            # })

            # 更新表格
            self.table.update_rows(display_df.to_dict('records'))
        else:
            self.table.update_rows([])

    def update_stats(self):
        """更新统计信息显示"""
        stats = gas_db.get_statistics()

        if stats:
            stats_text = f"""
            气体总数: {stats.get('total_gases', 0)}
            毒性分布: {', '.join([f'{k}:{v}' for k, v in stats.get(
                'toxicity_distribution', {}).items()])}
            平均分子量: {stats.get('avg_molecular_weight', 0):.2f}
            沸点范围: {stats.get('boiling_point_range', 'N/A')}
            """
            self.stats_label.set_text(stats_text)
        else:
            self.stats_label.set_text("暂无统计数据")

    def on_export_excel(self):
        """导出到Excel"""
        try:
            gas_db.export_to_excel('toxic_gases_export.xlsx')
            ui.notify("数据已导出到 toxic_gases_export.xlsx")
        except Exception as e:
            ui.notify(f"导出失败: {str(e)}", type='negative')

    def on_sort(self, column):
        """排序处理"""
        if column['column']['name'] in self.current_df.columns:
            self.sort_column = column['column']['name']
            self.sort_ascending = column['ascending']
            self.refresh_data()
            self.update_table()

    def create_ui(self):
        """创建UI界面"""
        # 标题
        ui.label('气体管理').classes('text-h4 text-primary')

        # 搜索和过滤区域
        with ui.row().classes('items-center gap-4 w-full'):
            # 搜索条件选择
            self.search_condition_select = ui.select(
                ['气体名称', '分子式', 'CAS号', '毒性等级'],
                label='搜索条件',
                value=self.search_condition,
                on_change=lambda e: setattr(self, 'search_condition', e.value)
            ).classes('w-32')

            # 搜索输入框
            self.search_input = ui.input(
                '搜索值',
                value=self.search_value,
                on_change=lambda e: setattr(self, 'search_value', e.value)
            ).classes('w-48')

            # 毒性等级过滤
            self.toxicity_select = ui.select(
                ['', '高毒', '中毒', '低毒'],
                label='毒性过滤',
                value=self.toxicity_filter,
                on_change=lambda e: setattr(self, 'toxicity_filter', e.value)
            ).classes('w-32')

            # 搜索按钮
            ui.button('搜索', icon='search', on_click=self.on_search)

            # 重置按钮
            ui.button('重置', icon='refresh',
                      on_click=lambda: (setattr(self, 'search_value', ''),
                                        setattr(self, 'toxicity_filter', ''),
                                        self.search_input.set_value(''),
                                        self.toxicity_select.set_value(''),
                                        self.on_search())).props('flat')

        # 操作按钮区域
        if permission_manager.check_permission(user_service.get_user_by_id(app.storage.user['id']), 'edit_content'):
            with ui.row().classes('gap-2'):
                ui.button('添加气体', icon='add', on_click=self.on_add_gas).props(
                    'color=positive')
                # ui.button('导出Excel', icon='download',
                #           on_click=self.on_export_excel)

        # 统计信息卡片
        with ui.card().classes('w-full'):
            with ui.card_section():
                ui.label('统计信息').classes('text-h6')
                self.stats_label = ui.label()
                self.update_stats()  # 初始显示统计信息

        # 数据表格
        with ui.card().classes('w-full'):
            with ui.card_section():
                ui.label('气体数据表').classes('text-h6')

                # 创建表格
                if self.current_df is not None and not self.current_df.empty:
                    display_df = self.current_df.copy()
                    columns_to_show = [
                        {'name': '气体名称', 'label': '气体名称',
                            'field': '气体名称', 'sortable': True},
                        {'name': '分子式', 'label': '分子式',
                            'field': '分子式', 'sortable': True},
                        {'name': 'CAS号', 'label': 'CAS号',
                            'field': 'CAS号', 'sortable': True},
                        {'name': '分子量', 'label': '分子量',
                            'field': '分子量', 'sortable': True},
                        {'name': '毒性等级', 'label': '毒性等级',
                            'field': '毒性等级', 'sortable': True},
                        {'name': '沸点_C',
                            'label': '沸点(℃)', 'field': '沸点_C', 'sortable': True},
                        {'name': '熔点_C',
                            'label': '熔点(℃)', 'field': '熔点_C', 'sortable': True},
                        {'name': 'IDLH浓度', 'label': 'IDLH浓度',
                            'field': 'IDLH浓度', 'sortable': True},
                        {'name': 'MAC浓度', 'label': 'MAC浓度',
                            'field': 'MAC浓度', 'sortable': True},
                        {'name': '安全阈值', 'label': '安全阈值',
                            'field': '安全阈值', 'sortable': True},
                        {'name': '警戒浓度', 'label': '警戒浓度',
                            'field': '警戒浓度', 'sortable': True},
                        {'name': '危险浓度', 'label': '危险浓度',
                            'field': '危险浓度', 'sortable': True},
                        {'name': 'actions', 'label': '操作', 'field': 'actions'}
                    ]

                    _allow_delete = permission_manager.check_permission(
                        user_service.get_user_by_id(app.storage.user['id']), 'delete_content')
                    rows = display_df.to_dict('records')
                    for row in rows:
                        row['actions'] = f"delete_{row['分子式']}" if _allow_delete else '--'

                    self.table = ui.table(
                        columns=columns_to_show,
                        rows=rows,
                        pagination={'rowsPerPage': 10},
                        # on_sort=self.on_sort
                    ).classes('max-w-6xl overflow-x-auto')

                    if _allow_delete:
                        # 为每行添加删除按钮
                        self.table.add_slot('body-cell-actions', '''
                            <q-td :props="props">
                                <q-btn @click="() => $parent.$emit('delete', props.row.分子式)"
                                    icon="delete" size="sm" color="negative" flat dense />
                            </q-td>
                        ''')

                        # 监听删除事件
                        self.table.on(
                            'delete', lambda e: self.on_delete_gas(e.args))
                else:
                    ui.label('暂无数据').classes('text-h6')

        # 底部信息
        # ui.label(f'共 {len(self.current_df) if self.current_df is not None else 0} 条记录').classes(
        #     'text-caption')


@contextlib.contextmanager
def make_it_center():
    with ui.column().classes('absolute-center items-center') as col:
        yield col
    return


def user_profile_pil(user, log_in_time):
    # Create a card-like container in the center
    with ui.column():  # .classes('items-center'):
        # Username with icon
        with ui.row().classes('items-center gap-2'):
            ui.icon('person').classes('text-xl')
            ui.label('Username:').classes('font-bold')
            username_label = ui.label(user.username).classes('text-lg')

        # Role with icon
        with ui.row().classes('items-center gap-2'):
            ui.icon('badge').classes('text-xl')
            ui.label('Role:').classes('font-bold')
            role_label = ui.label(user.role).classes('text-lg')

        # Permissions
        with ui.row().classes('items-center gap-2'):
            ui.icon('star').classes('text-xl')
            ui.label('Permissions:').classes('font-bold')
            for perm in PermissionManager.PERMISSIONS:
                if permission_manager.check_permission(user, perm['name']):
                    with ui.row():
                        ui.label(perm['name']).classes(
                            'font-bold text-gray-600 text-sm').classes('hover:text-blue-500')
                        ui.tooltip(perm['description'])

        # Time passed with icon (will update dynamically)
        with ui.row().classes('items-center gap-2'):
            ui.icon('schedule').classes('text-xl')
            ui.label('Time logged in:').classes('font-bold')
            passed_label = ui.label().classes('text-lg')

    ui.separator()

    # Function to update the passed time dynamically
    def update_passed_time():
        passed = datetime.now() - log_in_time
        # Format the timedelta to a readable format
        hours, remainder = divmod(passed.total_seconds(), 3600)
        minutes, seconds = divmod(remainder, 60)

        # Format based on duration
        if hours >= 1:
            passed_text = f"{int(hours)}h {int(minutes)}m {int(seconds)}s"
        elif minutes >= 1:
            passed_text = f"{int(minutes)}m {int(seconds)}s"
        else:
            passed_text = f"{int(seconds)}s"

        passed_label.set_text(passed_text)

    # Update immediately
    update_passed_time()

    # Set up a timer to update every second
    ui.timer(1.0, update_passed_time)
    return


def _edit_user_popup(name, updater, on_submit):
    u = user_service.get_user_by_username(name)
    with ui.dialog() as dialog, ui.card():
        ui.label(f'Edit User ({u.username})').classes(
            'text-xl font-semibold text-gray-800')
        password = ui.input(
            'Password', password=True, password_toggle_button=True)
        toBeActive = ui.switch(
            'ToBeActive', value=u.is_active)

        def _on_submit():
            if toBeActive.value:
                user_service.activate_user(
                    u.id, updater)
            else:
                user_service.deactivate_user(
                    u.id, updater)

            if password.value.strip():
                user_service.reset_user_passwd(
                    u.id, password.value.strip(), updater)

        with ui.row():
            ui.button('Cancel', on_click=dialog.close)
            ui.button('Submit', on_click=lambda: (
                _on_submit(),
                dialog.close(),
                on_submit()
            ))
    dialog.open()


def _delete_user_popup(name, updater, on_submit):
    u = user_service.get_user_by_username(name)

    def _on_submit():
        user_service.remove_user(u.username, updater)

    with ui.dialog() as dialog, ui.card():
        ui.icon('warning', color='orange', size='lg')
        ui.label(f'确认删除用户 ({u.username})').classes(
            'text-xl font-semibold text-gray-800')
        with ui.row():
            ui.button(
                'Cancel', on_click=lambda: dialog.close())
            ui.button('Submit',
                      color='red',
                      on_click=lambda: (
                            _on_submit(),
                            dialog.close(),
                            on_submit()
                      ))
    dialog.open()


@ui.page('/privilege')
@with_layout
async def privilege_page():
    ui.label('用户信息').classes('text-h5 font-bold mt-4 mb-2')

    this_user = user_service.get_user_by_id(app.storage.user['id'])
    log_in_time = app.storage.user['logInTime']
    if isinstance(log_in_time, str):
        log_in_time = datetime.fromisoformat(log_in_time)

    user_profile_pil(this_user, log_in_time)

    # View users, view_users
    if permission_manager.check_permission(this_user, 'view_users'):
        with ui.expansion('查看用户信息', icon='work').classes('w-full'):
            view_users_card = ui.card()

            columns = [
                {'name': 'name', 'label': '用户名', 'field': 'name',
                    'required': True, 'align': 'left', 'sortable': True},
                {'name': 'role', 'label': '角色',
                    'field': 'role', 'sortable': True},
                {'name': 'isActive', 'label': '是否激活',
                    'field': 'isActive', 'sortable': True},
                {'name': 'action', 'label': '编辑', 'align': 'center'},
                {'name': 'delete', 'label': '删除', 'align': 'center'}
            ]

            def update_view_users_card():
                users = user_service.list_users(active_only=False)
                view_users_card.clear()
                rows = sorted([
                    {'name': u.username, 'role': f'<u>{u.role}</u>',
                        'isActive': u.is_active}
                    for u in users], key=lambda e: e['role'] + e['name'])
                with view_users_card:
                    table = ui.table(
                        columns=columns, rows=rows, row_key='name')
                    table.add_slot('body-cell-role',
                                   '<q-td v-html="props.row.role"></q-td>')
                    table.add_slot('body-cell-isActive', '''
                        <q-td key="isActive" :props="props">
                            <q-badge :color="props.value? 'green' : 'gray'">
                                {{ props.value }}
                            </q-badge>
                        </q-td>
                    ''')
                    table.add_slot('body-cell-action', '''
                        <q-td :props="props">
                            <q-btn label="EDIT" @click="() => $parent.$emit('edit', props.row)" flat />
                        </q-td>
                    ''')
                    table.add_slot('body-cell-delete', '''
                        <q-td :props="props">
                            <q-btn label="Del" @click="() => $parent.$emit('delete', props.row)" flat />
                        </q-td>
                    ''')

                    table.on('edit', lambda e: _edit_user_popup(
                        e.args['name'], this_user, update_view_users_card))
                    table.on('delete', lambda e: _delete_user_popup(
                        e.args['name'], this_user, update_view_users_card))
            update_view_users_card()

            ui.button('刷新用户信息', on_click=update_view_users_card)
        pass

    # Signup, create_user
    if permission_manager.check_permission(this_user, 'create_user'):
        with ui.expansion('创建新用户', icon='settings').classes('w-full'):
            def try_signup():
                if user_service.create_user(
                    username=username.value,
                    email=email.value,
                    password=password.value,
                    role=role.value
                ):
                    ui.notify('成功创建新用户')
                else:
                    ui.notify('创建用户失败', color='negative')
                try:
                    update_view_users_card()
                except:
                    pass

            with ui.card():
                ui.label('注册新用户').classes('text-h6')
                username = ui.input('用户名').on('keydown.enter', try_signup)
                password = ui.input('密码', password=True, password_toggle_button=True).on(
                    'keydown.enter', try_signup)
                role = ui.select(['user', 'guest'],
                                 label='角色', value='guest')
                email = ui.input('电子邮箱地址').on('keydown.enter', try_signup)
                ui.button('注册新用户', on_click=try_signup)

    return


@ui.page('/gasExplorer')
@with_layout
async def gas_explorer_page():
    with ui.card().classes('w-full shadow-lg rounded-lg').style('background:#fafafaa0'):
        # ui.label('Gas explorer').classes('text-h4 font-bold text-primary')

        _ui = GasManagementUI()

        # 分割线
        ui.separator().classes('my-4')

        # 网站链接部分
        with ui.card_section():
            ui.label('气体知识学习材料').classes('text-h6 font-semibold mb-3')

            websites = {
                'Gazfinder': 'https://en.gazfinder.com/',
                'NIST Chemistry WebBook': 'https://webbook.nist.gov/chemistry/',
                'GESTIS-Database': 'https://www.dguv.de/ifa/gestis/gestis-stoffdatenbank/index-2.jsp',
                'EPA CompTox': 'https://comptox.epa.gov/dashboard/'
            }

            with ui.row().classes('gap-4'):
                for name, url in websites.items():
                    with ui.link(target=url, new_tab=True):
                        ui.button(name, icon='open_in_new').props('flat')

    return


@ui.page('/accidents')
@with_layout
async def accidents_page():
    # 标题区域
    with ui.row().classes('items-center mb-6'):
        ui.icon('warning').classes('text-red-600 text-2xl mr-2')
        ui.label('事故教育').classes('text-h4 font-bold')

    # 数据统计卡片
    with ui.row().classes('w-full mb-6 gap-4'):
        with ui.card().classes('flex-1 p-4'):
            with ui.row().classes('items-center'):
                ui.icon('folder_open').classes('text-blue-600 text-2xl mb-2')
                ui.label('总案例数量').classes(
                    'text-lg font-semibold text-gray-600')
                ui.label(str(len(accidents_education_df))).classes(
                    'text-3xl font-bold text-blue-700')

        with ui.card().classes('flex-1 p-4'):
            with ui.row().classes('items-center'):
                ui.icon('category').classes('text-green-600 text-2xl mb-2')
                # 统计不同的案例场景分类
                categories = accidents_education_df['案例场景分类'].nunique()
                ui.label('场景分类').classes('text-lg font-semibold text-gray-600')
                ui.label(str(categories)).classes(
                    'text-3xl font-bold text-green-700')

        with ui.card().classes('flex-1 p-4'):
            with ui.row().classes('items-center'):
                ui.icon('dangerous').classes('text-red-600 text-2xl mb-2')
                # 统计死亡人数（近似统计）
                ui.label('涉及泄漏气体').classes(
                    'text-lg font-semibold text-gray-600')
                gases = accidents_education_df['泄漏气体'].nunique()
                ui.label(str(gases)).classes('text-3xl font-bold text-red-700')

    # 分类选择器 & 搜索框
    with ui.row().classes('w-full items-center mb-4'):
        # 分类选择器
        ui.label('筛选案例类型:').classes('mr-2 font-medium')

        # 获取所有案例场景分类
        categories = [
            '所有案例'] + sorted(accidents_education_df['案例场景分类'].dropna().unique().tolist())

        category_select = ui.select(
            options=categories,
            value='所有案例',
            on_change=lambda e: filter_accidents(e.value)
        ).classes('w-64')

        # 搜索框
        ui.label('搜索:').classes('mr-2 font-medium')
        search_input = ui.input(
            placeholder='输入关键词搜索案例名称、泄漏气体等...',
            on_change=lambda e: filter_accidents(category_select.value)
        ).classes('flex-grow')

    # # 数据表格容器
    # table_container = ui.column().classes('w-full')
    # 数据表格容器 - 设置为可滚动
    table_container = ui.column().classes(
        'w-full h-[400px] overflow-y-auto border rounded')

    # 当前显示的数据
    current_df = accidents_education_df.copy()

    def filter_accidents(category: str, search_text: str = ''):
        """筛选事故案例"""
        nonlocal current_df

        # 清空容器
        table_container.clear()

        # 获取搜索文本
        search_text = search_input.value.lower() if search_input.value else ''

        # 筛选数据
        filtered_df = accidents_education_df.copy()

        # 按分类筛选
        if category != '所有案例':
            filtered_df = filtered_df[filtered_df['案例场景分类'] == category]

        # 按搜索词筛选
        if search_text:
            search_fields = ['案例名称', '泄漏气体', '泄漏设备（位置）', '事故经过概要']
            mask = False
            for field in search_fields:
                if field in filtered_df.columns:
                    mask = mask | filtered_df[field].astype(
                        str).str.lower().str.contains(search_text)
            filtered_df = filtered_df[mask]

        current_df = filtered_df
        update_table()

    def update_table():
        """更新表格显示"""
        table_container.clear()

        if current_df.empty:
            with table_container:
                ui.label('未找到相关案例').classes('text-center text-gray-500 py-8')
            return

        with table_container:
            # 创建表格
            columns = [
                '案例编号', '案例场景分类', '案例名称', '泄漏气体',
                '泄漏设备（位置）', '事故经过概要', '造成损失及危害'
            ]

            # 确保列存在
            available_columns = [
                col for col in columns if col in current_df.columns]

            # 创建数据表格
            table = ui.table(
                columns=[{'name': col, 'label': col, 'field': col}
                         for col in available_columns],
                rows=current_df[available_columns].to_dict('records'),
                pagination=10,
                row_key='案例编号'
            ).classes('w-full')

            table.props('grid')
            table.classes('max-h-96')

            # 添加详情查看功能
            table.add_slot('body', '''
                <q-tr :props="props">
                    <q-td v-for="col in props.cols" :key="col.name" :props="props">
                        <div v-if="col.name === '案例名称'" class="cursor-pointer text-blue-600 hover:text-blue-800"
                             @click="() => $parent.$emit('view-details', props.row)">
                            <q-icon name="visibility" size="sm" class="mr-1"/>
                            {{ col.value }}
                        </div>
                        <div v-else-if="col.name === '泄漏气体'" class="flex items-center">
                            <q-icon name="whatshot" size="sm" class="mr-1 text-red-500"/>
                            {{ col.value }}
                        </div>
                        <div v-else-if="col.name === '案例场景分类'" class="flex items-center">
                            <q-icon name="category" size="sm" class="mr-1 text-green-500"/>
                            {{ col.value }}
                        </div>
                        <div v-else>
                            {{ col.value }}
                        </div>
                    </q-td>
                </q-tr>
            ''')

            def on_row_click(row):
                """查看案例详情"""
                show_accident_details(row)

            table.on('view-details', on_row_click)

    def show_accident_details(row):
        """显示事故详情对话框"""
        with ui.dialog() as dialog, ui.card().classes('w-full max-w-3xl'):
            # 标题
            with ui.row().classes('items-center mb-4'):
                ui.icon('warning').classes('text-red-600 text-xl mr-2')
                ui.label(f'案例详情: {row.get("案例名称", "未知")}').classes(
                    'text-h5 font-bold')

            # 创建详情布局
            with ui.column().classes('w-full gap-3'):
                # 基本信息卡片
                with ui.card().classes('w-full p-4 bg-blue-50'):
                    ui.label('基本信息').classes(
                        'text-lg font-bold text-blue-700 mb-2')
                    with ui.grid(columns=2).classes('gap-2'):
                        with ui.column():
                            ui.label('案例编号:').classes('font-medium')
                            ui.label(row.get('案例编号', 'N/A')
                                     ).classes('text-blue-600')

                            ui.label('案例分类:').classes('font-medium mt-2')
                            ui.label(row.get('案例场景分类', 'N/A')
                                     ).classes('text-green-600')

                        with ui.column():
                            ui.label('泄漏气体:').classes('font-medium')
                            with ui.row().classes('items-center'):
                                ui.icon('whatshot').classes(
                                    'text-red-500 mr-1')
                                ui.label(row.get('泄漏气体', 'N/A')
                                         ).classes('text-red-600')

                # 设备信息卡片
                with ui.card().classes('w-full p-4 bg-green-50'):
                    ui.label('设备与位置').classes(
                        'text-lg font-bold text-green-700 mb-2')
                    with ui.row().classes('items-start'):
                        ui.icon('location_on').classes(
                            'text-green-600 mr-2 mt-1')
                        ui.label(row.get('泄漏设备（位置）', 'N/A')
                                 ).classes('text-gray-700')

                # 事故经过卡片
                with ui.card().classes('w-full p-4 bg-amber-50'):
                    ui.label('事故经过概要').classes(
                        'text-lg font-bold text-amber-700 mb-2')
                    with ui.row().classes('items-start'):
                        ui.icon('description').classes(
                            'text-amber-600 mr-2 mt-1')
                        ui.label(row.get('事故经过概要', 'N/A')
                                 ).classes('text-gray-700')

                # 损失危害卡片
                with ui.card().classes('w-full p-4 bg-red-50'):
                    ui.label('造成损失及危害').classes(
                        'text-lg font-bold text-red-700 mb-2')
                    with ui.row().classes('items-start'):
                        ui.icon('error').classes('text-red-600 mr-2 mt-1')
                        ui.label(row.get('造成损失及危害', 'N/A')
                                 ).classes('text-gray-700')

                # 安全警示
                with ui.card().classes('w-full p-4 bg-purple-50'):
                    ui.label('安全警示').classes(
                        'text-lg font-bold text-purple-700 mb-2')
                    with ui.column().classes('gap-2'):
                        ui.label('⚠️ 必须严格遵守安全操作规程').classes(
                            'text-sm text-purple-600')
                        ui.label('⚠️ 进入受限空间前必须进行气体检测').classes(
                            'text-sm text-purple-600')
                        ui.label('⚠️ 检修作业前必须可靠切断气源').classes(
                            'text-sm text-purple-600')

            ui.separator().classes('my-4')

            # 操作按钮
            with ui.row().classes('justify-end gap-2'):
                ui.button('关闭', on_click=dialog.close)
                ui.button('导出信息', icon='download',
                          on_click=lambda: export_accident_info(row))

        dialog.open()

    def export_accident_info(row):
        """导出事故信息"""
        # 这里可以添加导出功能，比如生成PDF或下载文本文件
        info = f"""
案例详情报告
============

案例名称: {row.get('案例名称', 'N/A')}
案例编号: {row.get('案例编号', 'N/A')}
案例分类: {row.get('案例场景分类', 'N/A')}

泄漏气体: {row.get('泄漏气体', 'N/A')}
泄漏位置: {row.get('泄漏设备（位置）', 'N/A')}

事故经过:
{row.get('事故经过概要', 'N/A')}

损失危害:
{row.get('造成损失及危害', 'N/A')}

报告时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """

        # 创建临时文件并下载
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
            f.write(info)
            temp_path = f.name

        ui.download(temp_path, filename=f"事故案例_{row.get('案例编号', '未知')}.txt")
        ui.notify(f'已导出案例信息: {row.get("案例名称", "未知")}')

    # 初始化显示
    filter_accidents('所有案例')

    return


@ui.page('/caseBrowser')
@with_layout
async def case_browser_page():
    ui.label('仿真案例').classes('text-h4 font-bold mb-4')

    cases = sorted([e for e in CASE_FOLDER.iterdir() if e.is_dir()])

    # 文件类型图标映射
    FILE_ICONS = {
        '.gif': 'gif',
        '.pdf': 'picture_as_pdf',
        '.docx': 'description',
        '.doc': 'description',
        '.txt': 'article',
        '.py': 'code',
        '.json': 'data_object',
        '.xlsx': 'table_chart',
        '.csv': 'table_rows',
        '.jpg': 'image',
        '.png': 'image',
        '.zip': 'folder_zip',
        '.rar': 'folder_zip',
    }

    # 默认显示图标
    DEFAULT_FILE_ICON = 'insert_drive_file'
    DEFAULT_FOLDER_ICON = 'folder'

    # 创建选择框
    with ui.row().classes('w-full items-center mb-4'):
        ui.label('案例选择:').classes('mr-2')
        case_select = ui.select(
            options=[c.name for c in cases],
            value=cases[0].name if cases else None,
            on_change=lambda e: load_case_files(e.value)
        ).classes('w-64')

    # 文件树容器
    file_tree_container = ui.column().classes('w-full')

    def load_case_files(case_name: str):
        """加载选中案例的文件树"""
        file_tree_container.clear()

        case_path = CASE_FOLDER / case_name
        if not case_path.exists():
            with file_tree_container:
                ui.label(f"Case '{case_name}' not found").classes(
                    'text-negative')
            return

        with file_tree_container:
            # 显示案例路径
            with ui.row().classes('items-center mb-3 p-2 bg-blue-50 rounded'):
                ui.icon('folder_open').classes('text-blue-600 mr-2')
                ui.label(f"案例目录: {case_path}").classes('text-sm')

            # 构建文件树
            build_file_tree(case_path)

    def build_file_tree(path: Path, level=0):
        """递归构建文件树"""
        # 获取所有条目并排序：先文件夹后文件
        items = []
        for item in sorted(path.iterdir()):
            if item.is_dir():
                items.append((item, True))  # True 表示是文件夹
            else:
                items.append((item, False))  # False 表示是文件

        if path.parent != CASE_FOLDER:
            with ui.row().classes(f'items-center ml-{level*4} w-full hover:bg-gray-100 p-1 rounded'):
                # 展开/收起按钮
                expand_btn = ui.button(icon='arrow_back',
                                       on_click=lambda: load_case_files(
                                           path.parent.relative_to(CASE_FOLDER))).props('flat dense size=sm')
                ui.icon(DEFAULT_FOLDER_ICON).classes('text-amber-600 mr-2')
                ui.label('..').classes('flex-grow cursor-pointer').on(
                    'click', lambda: load_case_files(
                        path.parent.relative_to(CASE_FOLDER))
                )

        # 先处理文件夹
        for item, is_dir in items:
            if is_dir:
                with ui.row().classes(f'items-center ml-{level*4} w-full hover:bg-gray-100 p-1 rounded'):
                    # 展开/收起按钮
                    expand_btn = ui.button(icon='chevron_right',
                                           on_click=lambda p=item: toggle_folder(p)).props('flat dense size=sm')

                    # 文件夹图标和名称
                    ui.icon(DEFAULT_FOLDER_ICON).classes('text-amber-600 mr-2')
                    ui.label(item.name).classes('flex-grow cursor-pointer').on(
                        'click', lambda p=item: load_case_files(
                            p.name) if p.parent == CASE_FOLDER else None
                    )

                    # 子文件计数
                    file_count = len(
                        [f for f in item.rglob('*') if f.is_file()])
                    if file_count > 0:
                        ui.badge(str(file_count)).props('color=blue')

                    # 子容器（初始隐藏）
                    sub_container = ui.column().classes(
                        f'w-full ml-{(level+1)*4} hidden')

                    # 存储引用
                    expand_btn.sub_container = sub_container
                    expand_btn.folder_path = item

        # 再处理文件
        for item, is_dir in items:
            if not is_dir:
                suffix = item.suffix.lower()
                icon = FILE_ICONS.get(suffix, DEFAULT_FILE_ICON)

                with ui.row().classes(f'items-center ml-{level*4} w-full hover:bg-gray-50 p-1 rounded'):
                    ui.icon(icon).classes('text-gray-600 mr-2')
                    ui.label(item.name).classes('flex-grow cursor-pointer').on(
                        'click', lambda f=item: preview_file(f)
                    )

                    # 文件大小
                    size = item.stat().st_size
                    size_str = f"{size:,} B"
                    if size > 1024*1024:
                        size_str = f"{size/(1024*1024):.1f} MB"
                    elif size > 1024:
                        size_str = f"{size/1024:.1f} KB"

                    ui.label(size_str).classes('text-xs text-gray-500 mr-2')

                    # 操作按钮
                    with ui.row().classes('gap-1'):
                        ui.button(icon='visibility',
                                  on_click=lambda f=item: preview_file(f)).props('flat dense size=sm')
                        ui.button(icon='download',
                                  on_click=lambda f=item: download_file(f)).props('flat dense size=sm')

    def toggle_folder(folder_path: Path):
        """切换文件夹展开/收起状态"""
        # 注意：这里需要实现展开/收起逻辑
        # 由于NiceGUI的限制，我们可以使用不同的方式
        load_case_files(folder_path.relative_to(CASE_FOLDER))
        # print(f'Toggle folder: {folder_path}')
        pass

    def preview_file(file_path: Path):
        """预览文件"""
        suffix = file_path.suffix.lower()

        # 创建预览对话框
        with ui.dialog() as dialog, ui.card().classes('w-full max-w-4xl').classes('items-center'):
            ui.label(f'Preview: {file_path.name}').classes(
                'text-h6 font-bold mb-3')

            # 根据文件类型显示预览
            if suffix in ['.gif', '.jpg', '.jpeg', '.png']:
                with ui.row().classes('w-full h-96 overflow-auto border rounded'):
                    ui.image(str(file_path)).classes('max-w-full')

            elif suffix == '.pdf':
                ui.html(f'''
                    <iframe
                        src="{file_path}"
                        height="500px"
                        style="border: 1px solid #ddd; width: 800px;"
                        scrolling="yes"
                    ></iframe>
                ''', sanitize=False)

            elif suffix in ['.txt', '.py', '.json']:
                try:
                    content = file_path.read_text(
                        encoding='utf-8')[:2000]  # 限制预览长度
                    ui.code(content).classes('w-full h-96')
                except:
                    ui.label('Cannot preview this file').classes(
                        'text-negative')

            else:
                with ui.column().classes('items-center justify-center h-48'):
                    ui.icon('description').classes(
                        'text-6xl text-gray-400 mb-4')
                    ui.label('Preview not available').classes('text-gray-500')
                    ui.button('Download File', icon='download',
                              on_click=lambda: download_file(file_path)).classes('mt-4')

            ui.separator().classes('my-4')

            with ui.row().classes('justify-end gap-2'):
                ui.button('Close', on_click=dialog.close)
                ui.button('Download', icon='download',
                          on_click=lambda: [download_file(file_path), dialog.close()])

        dialog.open()

    def download_file(file_path: Path):
        """下载文件"""
        # 在NiceGUI中，可以通过设置下载链接
        ui.download(str(file_path))
        ui.notify(f'Downloading: {file_path.name}')

    # 初始化：如果存在案例，加载第一个
    if cases:
        load_case_files(cases[0].name)

    return


@ui.page('/profile')
@with_layout
async def profile_page() -> None:
    ui.label('Profile page')

    def logout() -> None:
        session_manager.remove_session(app.storage.user['session_id'])
        app.storage.user.clear()
        ui.navigate.to('/login')

    with make_it_center():
        ui.label(f'Hello {app.storage.user["username"]}!').classes('text-2xl')
        ui.button(on_click=logout, icon='logout').props('outline round')
    return


@ui.page('/sensors')
@with_layout
async def sensors_page():
    this_user = user_service.get_user_by_id(app.storage.user['id'])
    checks = [
        'create_content',
        'edit_content',
        'delete_content'
    ]
    rights = {e: permission_manager.check_permission(
        this_user, e) for e in checks}

    # 创建数据读取器实例
    reader = SensorDataReader()
    writer = SensorDataWriter()
    ui_manager = SensorsUI(reader, writer, rights)

    # 创建页面
    await ui_manager.create_sensors_page()


@ui.page('/')
@with_layout
async def root():

    with make_it_center():
        # ui.link('Welcome page', '/welcome')
        # ui.link('Profile page', '/profile')
        # with ui.card().classes('max-w-3xl w-full shadow-lg'):
        #     ui.markdown(abstract)
        pass

    # 快速导航按钮
    with ui.row().classes('gap-4 mt-8'):
        if app.storage.user.get('authenticated', False):
            ui.button('案例库', icon='dashboard',
                      on_click=lambda: ui.navigate.to('/caseBrowser')).props('color=primary')
            ui.button('传感器监控', icon='sensors',
                      on_click=lambda: ui.navigate.to('/sensors')).props('color=secondary')
            ui.button('气体数据库', icon='science',
                      on_click=lambda: ui.navigate.to('/gasExplorer')).props('color=accent')
        else:
            ui.button('立即登录', icon='login',
                      on_click=lambda: ui.navigate.to('/login')).props('color=primary')
            ui.button('了解更多', icon='info',
                      on_click=lambda: ui.navigate.to('/welcome')).props('flat')

    # 使用markdown并添加卡片样式
    with ui.card().classes('max-w-3xl w-full shadow-lg bg-white/40'):
        with ui.card_section().classes('p-8'):
            ui.markdown(abstract).classes(
                'text-gray-700 leading-relaxed'
            )

    return


@ui.page('/welcome')
@with_layout
async def welcome_page():
    with make_it_center():
        ui.label('Welcome to my project.')
        user = app.storage.user
        if not user.get('authenticated', False):
            ui.label('You have not logged in.').classes('text-negative')
            ui.link('Login', '/login')
        else:
            ui.label(f'Dear {user.get("username", "N.A.")}').classes(
                'text-positive')
    return


@ui.page('/login')
@with_layout
async def login(redirect_to: str = '/') -> Optional[RedirectResponse]:
    def try_login() -> None:  # local function to avoid passing username and password as arguments
        user = user_service.authenticate_user(username.value, password.value)
        if user is not None:
            app.storage.user.update(
                {'username': username.value,
                 'authenticated': True,
                 'id': user.id,
                 'logInTime': datetime.now()
                 })
            session_id = session_manager.add_session(app.storage.user)
            app.storage.user.update(
                {'session_id': session_id}
            )
            # go back to where the user wanted to go
            ui.navigate.to(redirect_to)
        else:
            ui.notify('Wrong username or password', color='negative')

    if app.storage.user.get('authenticated', False):
        # return RedirectResponse('/')
        # ui.navigate.to('/')
        return

    with ui.card().classes('absolute-center'):
        ui.label('Login')
        username = ui.input('Username').on('keydown.enter', try_login)
        password = ui.input('Password', password=True, password_toggle_button=True).on(
            'keydown.enter', try_login)
        ui.button('Log in', on_click=try_login)
        ui.link('Continue without login', '/welcome')
    return


@app.exception_handler(404)
async def exception_handler_404(request: Request, exception: Exception):
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>404 - Page Not Found</title>
        <style>
            body {{ font-family: Arial, sans-serif; text-align: center; padding: 50px; }}
            h1 {{ color: #dc2626; }}
            .message {{ margin: 20px 0; }}
            button {{ background: #3b82f6; color: white; border: none; padding: 10px 20px; cursor: pointer; }}
        </style>
    </head>
    <body>
        <h1>404 - Page Not Found</h1>
        <div class="message">Sorry, the page "{request.url.path}" does not exist.</div>
        <button onclick="window.location.href='/'">Go Home</button>
    </body>
    </html>
    """

    from starlette.responses import HTMLResponse
    return HTMLResponse(html_content, status_code=404)

# 添加路由来提供静态文件访问


@app.get('/data/case/{case_name:path}')
def serve_pdf(case_name: str):
    """提供PDF文件下载/预览"""
    # 构建完整路径
    file_path = CASE_FOLDER / case_name

    # 检查文件是否存在且是PDF
    if not file_path.exists():
        return app.redirect('/404')
    return FileResponse(file_path, media_type='application/pdf')


@app.get('/map')
def show_map(lat: str = '39.906217', lon: str = '116.3912757', zoom: str = '10', session: str = '???'):
    # params = dict(request.query_params)
    print(f'Loading map, {lat=}, {lon=}, {zoom=}, {session=}')
    html_content = Path('static/html/map.html').read_text(encoding='utf-8')
    changes = {
        '"{{zoom}}"': zoom,
        '"{{lat}}"': lat,
        '"{{lon}}"': lon,
        '{{session}}': session,
    }
    for k, v in changes.items():
        html_content = html_content.replace(k, v)
    return HTMLResponse(content=html_content)


@app.get('/latest_sensor_data')
def require_json_latest_sensor_data():
    reader = SensorDataReader()
    sensors = reader.get_sensor_info()
    for s in sensors:
        try:
            s['value'] = reader.get_latest_data(s['sensor_id'])[0]['value']
        except:
            pass
    obj = json.dumps(sensors)
    return HTMLResponse(obj, media_type='application/json')


@ui.page('/get_fds_simulation_result/{session}')
async def get_fds_simulation_result(session: str):
    dir = 'fds'
    session_dir = Path(dir) / 'simulation' / session
    files = list(session_dir.iterdir()) if session_dir.is_dir() else []
    files.extend(list((session_dir / 'img').iterdir()))
    obj = {'files': [str(f.name) for f in files]}
    return HTMLResponse(json.dumps(obj), media_type='application/json')


@ui.page('/get_fds_simulation_frame')
async def get_fds_simulation_frame(session: str, frame: str):
    dir = 'fds'
    session_dir = Path(dir) / 'simulation' / session / 'img' / frame
    if not session_dir.is_file():
        return HTMLResponse('File not found', status_code=404)
    print(session_dir)
    return FileResponse(session_dir, media_type='image/png')


@ui.page('/simulation')
@with_layout_full_width
async def simulation_page():
    with ui.row().classes('w-[1200px] justify-center gap-4'):
        simulate_button = ui.button(
            'Start Simulation', icon='play_arrow').props('color=primary')

        simulation_history_select = ui.select(
            options=[], label='Simulation History').classes('w-64')

    # Layout
    with ui.row().classes('w-full justify-center gap-4'):
        weather_card = ui.card().classes('w-[200px] p-4 shadow-lg z-10')
        map_card = ui.card().classes('w-[800px] h-[800px] p-0 m-0')
        gas_card = ui.card().classes('w-[200px] p-4 shadow-lg z-10')

    # Simulation history
    def on_select_session(e):
        session = e.value
        update_map(session=session)

    simulation_history = get_fds_simulation_result_history()
    print(simulation_history)
    simulation_history_select.options = [e for e in simulation_history]
    simulation_history_select.update()
    simulation_history_select.on_value_change(on_select_session)

    # Simulate button action
    def on_click():
        reader = SensorDataReader()
        sensors = reader.get_sensor_info()
        for s in sensors:
            try:
                s['value'] = reader.get_latest_data(s['sensor_id'])[0]['value']
            except:
                pass
        session = simulate_with_fds(sensors)
        update_map(session=session)
        ui.notify(
            f'Simulation started. Session ID: {session}', color='positive')

    simulate_button.on('click', on_click)

    gases = gas_db.search_gases()
    geo_candidates = {
        '北京': {'lat': 39.9042, 'lon': 116.4074, 'zoom': 10},
        '上海': {'lat': 31.2304, 'lon': 121.4737, 'zoom': 10},
        '武威': {'lat': 37.9282, 'lon': 102.6346, 'zoom': 10},
        '张掖': {'lat': 38.9259, 'lon': 100.4498, 'zoom': 10},
    }
    default_zoom = 10

    # 左侧天气信息输入
    with weather_card:
        ui.label('地理位置').classes('text-h6 mb-4')

        # 创建下拉选择框
        location_select = ui.select(
            options=list(geo_candidates.keys()),
            value='北京',
            label='选择地点'
        ).classes('w-40')

        # 创建数字输入框
        zoom_input = ui.number(
            value=default_zoom,
            min=1,
            max=20,
            step=1,
            precision=0,
            label='地图缩放级别'
        ).classes('w-24')

        ui.label('气象条件').classes('text-h6 mb-4')

        weather_conditions = ui.select(
            options=['晴', '多云', '阴', '雨', '雪', '雾'],
            value='晴',
            label='天气状况'
        ).classes('w-full mb-4')

        temperature = ui.number(
            label='温度(℃)',
            value=20,
            min=-50,
            max=50
        ).classes('w-full mb-4')

        humidity = ui.number(
            label='湿度(%)',
            value=50,
            min=0,
            max=100
        ).classes('w-full mb-4')

        wind_speed = ui.number(
            label='风力(级)',
            value=3,
            min=0,
            max=12
        ).classes('w-full mb-4')

        wind_direction = ui.select(
            options=['北', '东北', '东', '东南', '南', '西南', '西', '西北'],
            value='东',
            label='风向'
        ).classes('w-full')

    # 右侧气体信息显示
    with gas_card:
        ui.label('气体属性').classes('text-h6 mb-4')

        gas_select = ui.select(
            options=[g['气体名称'] for g in gases],
            value=gases[0]['气体名称'] if gases else None,
            label='选择气体'
        ).classes('w-full mb-6')

        # 气体属性输入字段（字符串类型）
        gas_name_input = ui.input(label='气体名称').classes(
            'w-full mb-2').props('readonly')
        toxicity_input = ui.input(label='毒性等级').classes('w-full mb-2')
        idlh_input = ui.input(label='IDLH浓度').classes('w-full mb-2')
        mac_input = ui.input(label='MAC浓度').classes('w-full mb-2')
        safe_threshold_input = ui.input(label='安全阈值').classes('w-full mb-2')
        warning_concentration_input = ui.input(
            label='警戒浓度').classes('w-full mb-2')
        danger_concentration_input = ui.input(
            label='危险浓度').classes('w-full mb-2')

        # 将输入字段存储到字典中以便访问
        gas_inputs = {
            '气体名称': gas_name_input,
            '毒性等级': toxicity_input,
            'IDLH浓度': idlh_input,
            'MAC浓度': mac_input,
            '安全阈值': safe_threshold_input,
            '警戒浓度': warning_concentration_input,
            '危险浓度': danger_concentration_input
        }

        # 添加保存按钮（如果需要保存修改）
        # ui.button('保存修改', on_click=lambda: save_gas_changes(gas_inputs)).classes('w-full mt-4')

    def update_gas_inputs():
        """当气体选择改变时，填充所有输入字段"""
        selected_gas_name = gas_select.value
        if not selected_gas_name:
            # 清空所有输入字段
            for input_field in gas_inputs.values():
                input_field.value = ''
            return

        # 查找选中的气体信息
        gas_info = next(
            (e for e in gases if e['气体名称'] == selected_gas_name), None)

        if gas_info:
            # 将所有值转换为字符串并填充到输入字段中
            gas_inputs['气体名称'].value = str(gas_info.get('气体名称', ''))
            gas_inputs['毒性等级'].value = str(gas_info.get('毒性等级', ''))
            gas_inputs['IDLH浓度'].value = str(gas_info.get('IDLH浓度', ''))
            gas_inputs['MAC浓度'].value = str(gas_info.get('MAC浓度', ''))
            gas_inputs['安全阈值'].value = str(gas_info.get('安全阈值', ''))
            gas_inputs['警戒浓度'].value = str(gas_info.get('警戒浓度', ''))
            gas_inputs['危险浓度'].value = str(gas_info.get('危险浓度', ''))

            # 可选：根据字段类型设置输入类型
            set_input_attributes(gas_info)
        else:
            # 如果找不到气体，清空所有字段
            for input_field in gas_inputs.values():
                input_field.value = ''

    def set_input_attributes(gas_info):
        """根据数据类型设置输入属性"""
        # 对于数值字段，可以设置输入类型
        concentration_fields = ['IDLH浓度', 'MAC浓度', '安全阈值', '警戒浓度', '危险浓度']

        for field in concentration_fields:
            value = gas_info.get(field)
            input_field = gas_inputs[field]

            if isinstance(value, (int, float)):
                # 设置为数字输入
                input_field.props('type=number step=any')
                # 可选：添加单位后缀
                if field in ['IDLH浓度', 'MAC浓度', '警戒浓度', '危险浓度']:
                    input_field.props(f'suffix=ppm')
            else:
                input_field.props('')

    # 连接选择器变化事件
    gas_select.on('update:model-value', update_gas_inputs)

    # 初始填充（只在页面加载时执行一次）
    if gases:
        update_gas_inputs()

    def update_map(session='???'):
        # 获取选择的地点
        selected_location = location_select.value
        if selected_location in geo_candidates:
            geo = geo_candidates[selected_location]
            zoom = zoom_input.value if zoom_input.value else geo['zoom']

            # 构建包含参数的 URL
            params = f"lat={geo['lat']}&lon={geo['lon']}&zoom={zoom}&session={session}"

            # 更新 iframe 的 src 属性
            js_code = f"""
            var iframe = document.getElementById('map-iframe');
            if (iframe) {{
                iframe.src = '/map?{params}';
            }}
            """
            ui.run_javascript(js_code)

    # 绑定选择框变化事件
    # location_select.on_change(update_map)
    location_select.on('update:model-value', update_map)
    zoom_input.on_value_change(update_map)

    with map_card:
        # 嵌入iframe来显示地图页面
        iframe = ui.html(f'''
<div id='mapdiv'>
    <iframe
        id="map-iframe"
        src="/map"
        style="width: 800px; height: 800px; border: none;"
        title="地图"
    ></iframe>
</div>
''', sanitize=False)

    return


if __name__ in {'__main__', '__mp_main__'}:
    import sys

    kwargs = {
        'reload': True,
    }
    if len(sys.argv) > 1 and sys.argv[1] == '-w':
        kwargs = {
            'reload': False,
            'frameless': True,
            'window_size': (1440, 900),
        }

    ui.run(root,
           title=PROJECT.get('name', 'Project'),
           favicon='./static/favicon/favicon.ico',
           uvicorn_reload_excludes='.*, .py[cod], .sw.*, ~*, *.db, *.log',
           storage_secret='abcdefg',
           **kwargs)

# %%
