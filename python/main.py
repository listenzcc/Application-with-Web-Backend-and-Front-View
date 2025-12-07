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

from components.layout import with_layout

# %%
# Gas explorer data
df_gas_explorer = pd.read_excel('./data/gas/a.xlsx')

# %%
# Cases
case_folder = Path('./data/case')

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
        ui.label('Gas explorer').classes('text-h4 font-bold text-primary')

        # 表格部分
        with ui.card_section():
            ui.table.from_pandas(
                df_gas_explorer, pagination={'rowsPerPage': 5})

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


@ui.page('/cases')
@with_layout
async def cases_page():
    ui.label('Cases page')

    ui.label('Cases Browser').classes('text-h4 font-bold mb-4')

    cases = sorted([e for e in case_folder.iterdir() if e.is_dir()])

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

        case_path = case_folder / case_name
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

        if path.parent != case_folder:
            with ui.row().classes(f'items-center ml-{level*4} w-full hover:bg-gray-100 p-1 rounded'):
                # 展开/收起按钮
                expand_btn = ui.button(icon='arrow_back',
                                       on_click=lambda: load_case_files(
                                           path.parent.relative_to(case_folder))).props('flat dense size=sm')
                ui.icon(DEFAULT_FOLDER_ICON).classes('text-amber-600 mr-2')
                ui.label('..').classes('flex-grow cursor-pointer').on(
                    'click', lambda: load_case_files(
                        path.parent.relative_to(case_folder))
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
                            p.name) if p.parent == case_folder else None
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
        load_case_files(folder_path.relative_to(case_folder))
        # print(f'Toggle folder: {folder_path}')
        pass

    def preview_file(file_path: Path):
        """预览文件"""
        suffix = file_path.suffix.lower()

        # 创建预览对话框
        with ui.dialog() as dialog, ui.card().classes('w-full max-w-4xl'):
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
    file_path = case_folder / case_name

    # 检查文件是否存在且是PDF
    if not file_path.exists():
        return app.redirect('/404')
    from fastapi.responses import FileResponse
    return FileResponse(file_path, media_type='application/pdf')


if __name__ in {'__main__', '__mp_main__'}:
    ui.run(root,
           reload=True,
           #    frameless=True,
           storage_secret='listenzcc')

# %%
