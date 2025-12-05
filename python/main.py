# %%
import contextlib

from typing import Optional
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
        # email="user@example.com",
        password="password123",
        role=RoleEnum.USER.value
    )

    # 创建访客
    guest = user_service.create_user(
        username="guest",
        # email="guest@example.com",
        password="guest123",
        role=RoleEnum.GUEST.value
    )
except:
    pass

# Auth middle ware
unrestricted_page_routes = {'/login', '/welcomepage'}


@app.add_middleware
class AuthMiddleware(BaseHTTPMiddleware):
    """This middleware restricts access to all NiceGUI pages.

    It redirects the user to the login page if they are not authenticated.
    """

    async def dispatch(self, request: Request, call_next):
        if not app.storage.user.get('authenticated', False):
            if not request.url.path.startswith('/_nicegui') and request.url.path not in unrestricted_page_routes:
                return RedirectResponse(f'/login?redirect_to={request.url.path}')
        return await call_next(request)


@contextlib.contextmanager
def make_it_center():
    with ui.column().classes('absolute-center items-center') as col:
        yield col
    return


@ui.page('/privilege')
@with_layout
async def privilege_page():
    ui.label('Privilege page')

    user = user_service.get_user_by_id(app.storage.user['id'])

    ui.label(f'Username: {user.username}, role: {user.role}')

    # View users
    if permission_manager.check_permission(user, 'view_users'):
        view_users_card = ui.card()

        def update_view_users_card():
            users = user_service.list_users()
            view_users_card.clear()
            with view_users_card:
                for u in users:
                    ui.label(
                        f'- {u.username} ({u.role}) - Alive: {u.is_active}')
        update_view_users_card()

        ui.button('Refresh', on_click=update_view_users_card)

    # Signup
    if permission_manager.check_permission(user, 'create_user'):
        def try_signup():
            if user_service.create_user(
                username=username.value,
                email=email.value,
                password=password.value,
                role=role.value
            ):
                ui.notify('Signup successfully.')
                try:
                    update_view_users_card()
                except:
                    pass
            else:
                ui.notify('Signup failed.', color='negative')

        with ui.card():
            ui.label('SignUp')
            username = ui.input('Username').on('keydown.enter', try_signup)
            password = ui.input('Password', password=True, password_toggle_button=True).on(
                'keydown.enter', try_signup)
            role = ui.select(['user', 'guest'], label='role', value='guest')
            email = ui.input('Email').on('keydown.enter', try_signup)
            ui.button('SignUp', on_click=try_signup)


@ui.page('/profile')
@with_layout
async def profile_page() -> None:
    ui.label('Profile page')

    def logout() -> None:
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
        ui.link('Welcome page', '/welcomepage')
        ui.link('Profile page', '/profilepage')
        ui.link('Sub page', '/subpage')

    return


@ui.page('/subpage')
@with_layout
async def test_page() -> None:
    ui.label('This is a sub page.')
    return


@ui.page('/welcomepage')
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
                 'id': user.id
                 })
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
        ui.link('Continue without login', '/welcomepage')
    return


# @app.exception_handler(404)
# async def exception_handler_404(request: Request, exception: Exception):
#     with Client(page('')) as client:
#         ui.label('Sorry, this page does not exist')
#         ui.label('404 - Page Not Found').classes('text-2xl text-red-600')
#         ui.label('Sorry, the page you are looking for does not exist.')
#         ui.button('Go Home', on_click=lambda: ui.navigate.to(
#             '/')).props('primary')
#         return client.build_response(request, 404)

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
    ui.run(root, storage_secret='THIS_NEEDS_TO_BE_CHANGED')

# %%
