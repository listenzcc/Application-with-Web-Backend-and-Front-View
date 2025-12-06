# %%
import contextlib

from typing import Optional
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

    # Manage sessions, manage_sessions
    if permission_manager.check_permission(this_user, 'manage_sessions'):
        with ui.expansion('Manage sessions', icon='settings').classes('w-full'):
            print(session_manager.active_sessions)
            with ui.column():
                for k, v in session_manager.active_sessions.items():
                    ui.label(f'{k}: {v}')

        pass


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

if __name__ in {'__main__', '__mp_main__'}:
    ui.run(root,
           reload=False,
           storage_secret='listenzcc')

# %%
