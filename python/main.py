# %%
import contextlib
import pandas as pd

from typing import Optional
from pathlib import Path
from datetime import datetime

from nicegui import Client
from nicegui import app, ui
from nicegui.page import page

from fastapi import Request
from fastapi.responses import RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

from auth.models import RoleEnum
from auth.database import DatabaseManager
from auth.decorators import AuthContext, require_permission, require_role
from auth.user_service import UserService
from auth.auth_manager import PermissionManager

from util.user_session_manager import UserSessionManager

from explorer.toxic_gas import ToxicGasDatabase

from components.layout import with_layout

# %%
# Gas explorer data
gas_db = ToxicGasDatabase()

# %%
# Cases
CASE_FOLDER = Path('./data/case')

# %%
# Auth system

# Auth db
# 1. 初始化数据库
db_manager = DatabaseManager('sqlite:///auth.db', echo=False)
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
unrestricted_page_routes = {'/login', '/welcome'}
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
                        'MAC浓度': mac.value
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
                '沸点_C', '熔点_C', 'IDLH浓度', 'MAC浓度'
            ]

            # 确保列存在
            available_columns = [
                col for col in columns_to_show if col in display_df.columns]
            display_df = display_df[available_columns]

            # 重命名列显示
            display_df = display_df.rename(columns={
                '沸点_C': '沸点(℃)',
                '熔点_C': '熔点(℃)'
            })

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
            毒性分布: {', '.join([f'{k}:{v}' for k, v in stats.get('toxicity_distribution', {}).items()])}
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
        ui.label('Gas Explorer').classes('text-h4 text-primary')

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
                    ).classes('w-full')

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
        ui.label(f'共 {len(self.current_df) if self.current_df is not None else 0} 条记录').classes(
            'text-caption')


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
        ui.label(f'Confirm User Deletion ({u.username})').classes(
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
    ui.label('Privilege page')

    this_user = user_service.get_user_by_id(app.storage.user['id'])
    log_in_time = app.storage.user['logInTime']
    if isinstance(log_in_time, str):
        log_in_time = datetime.fromisoformat(log_in_time)

    user_profile_pil(this_user, log_in_time)

    # View users, view_users
    if permission_manager.check_permission(this_user, 'view_users'):
        with ui.expansion('View users', icon='work').classes('w-full'):
            view_users_card = ui.card()

            columns = [
                {'name': 'name', 'label': 'Name', 'field': 'name',
                    'required': True, 'align': 'left', 'sortable': True},
                {'name': 'role', 'label': 'Role',
                    'field': 'role', 'sortable': True},
                {'name': 'isActive', 'label': 'isActive',
                    'field': 'isActive', 'sortable': True},
                {'name': 'action', 'label': 'Action', 'align': 'center'},
                {'name': 'delete', 'label': 'Delete', 'align': 'center'}
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

            ui.button('Refresh', on_click=update_view_users_card)
        pass

    # Signup, create_user
    if permission_manager.check_permission(this_user, 'create_user'):
        with ui.expansion('Create New User', icon='settings').classes('w-full'):
            def try_signup():
                if user_service.create_user(
                    username=username.value,
                    email=email.value,
                    password=password.value,
                    role=role.value
                ):
                    ui.notify('Signup successfully.')
                else:
                    ui.notify('Signup failed.', color='negative')
                try:
                    update_view_users_card()
                except:
                    pass

            with ui.card():
                ui.label('SignUp')
                username = ui.input('Username').on('keydown.enter', try_signup)
                password = ui.input('Password', password=True, password_toggle_button=True).on(
                    'keydown.enter', try_signup)
                role = ui.select(['user', 'guest'],
                                 label='role', value='guest')
                email = ui.input('Email').on('keydown.enter', try_signup)
                ui.button('SignUp', on_click=try_signup)

    return


@ui.page('/gasExplorer')
@with_layout
async def gas_explorer_page():
    ui.label('Gas explorer page')

    with ui.card().classes('w-full shadow-lg rounded-lg'):
        # ui.label('Gas explorer').classes('text-h4 font-bold text-primary')

        _ui = GasManagementUI()

        # 分割线
        ui.separator().classes('my-4')

        # 网站链接部分
        with ui.card_section():
            ui.label('Friend websites:').classes('text-h6 font-semibold mb-3')

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


@ui.page('/caseBrowser')
@with_layout
async def case_browser_page():
    ui.label('Case browser page')

    ui.label('Case Browser').classes('text-h4 font-bold mb-4')

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
        ui.label('Select Case:').classes('mr-2')
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
                ui.label(f"Path: {case_path}").classes('text-sm')

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


@ui.page('/')
@with_layout
async def root():
    ui.label('Home page')

    with make_it_center():
        ui.link('Welcome page', '/welcome')
        ui.link('Profile page', '/profile')

    return


@ui.page('/welcome')
@with_layout
async def welcome_page():
    ui.label('Welcome page')
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
    from fastapi.responses import FileResponse
    return FileResponse(file_path, media_type='application/pdf')


@app.get('/map')
def show_map():
    html_content = Path('html/map.html').read_text(encoding='utf-8')
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=html_content)


@ui.page('/simulation')
@with_layout
async def simulation_page():
    with ui.card().classes('w-full h-full p-0 m-0').classes('items-center'):
        # 嵌入iframe来显示地图页面
        ui.html(f'''
<div id='mapdiv'>
    <iframe 
        src="/map" 
        style="width: 800px; height: 800px; border: none;"
        title="地图"
    ></iframe>
</div>
''', sanitize=False)
    return


if __name__ in {'__main__', '__mp_main__'}:
    ui.run(root,
           reload=True,
           #    frameless=True,
           storage_secret='listenzcc')

# %%
