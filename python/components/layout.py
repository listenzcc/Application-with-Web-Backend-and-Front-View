from functools import wraps
from typing import Callable, Optional
from nicegui import app, ui


def with_layout(func: Callable) -> Callable:
    """为页面添加公共header和footer的装饰器"""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        # 添加公共header
        create_header()

        # 页面主要内容区域
        with ui.column().classes('w-full max-w-6xl mx-auto p-4 min-h-[calc(100vh-130px)]'):
            await func(*args, **kwargs)

        # 添加公共footer
        create_footer()

    return wrapper


def create_header():
    """创建公共header，显示用户状态"""
    with ui.header().classes('bg-blue-50 shadow-sm border-b') as header:
        with ui.row().classes('w-full justify-between items-center p-4'):
            # 左侧：Logo和导航
            with ui.row().classes('items-center gap-8'):
                # Logo
                ui.link(
                    'MyApp', '/').classes('text-2xl font-bold text-blue-600 no-underline hover:text-blue-800')

                # 主导航
                with ui.row().classes('gap-6'):
                    ui.link('Home', '/',
                            ).classes('text-gray-700 hover:text-blue-600 no-underline font-medium')
                    ui.link('Simulation', '/simulation',
                            ).classes('text-gray-700 hover:text-blue-600 no-underline font-medium')
                    ui.link('CaseBrowser', '/caseBrowser',
                            ).classes('text-gray-700 hover:text-blue-600 no-underline font-medium')
                    ui.link('GasExplorer', '/gasExplorer',
                            ).classes('text-gray-700 hover:text-blue-600 no-underline font-medium')
                    ui.link('Privilege', '/privilege',
                            ).classes('text-gray-700 hover:text-blue-600 no-underline font-medium')

            # 右侧：用户信息和操作（右上角）
            create_user_info_section()

    return header


def create_user_info_section():
    """创建右上角的用户信息区域"""
    with ui.row().classes('items-center gap-4'):
        # 检查用户是否已登录
        user_authenticated = app.storage.user.get('authenticated', False)
        username = app.storage.user.get('username', 'Guest')

        if user_authenticated:
            # 已登录用户的显示
            with ui.row().classes('items-center gap-3'):
                # 用户头像和欢迎信息
                with ui.column().classes('items-end'):
                    ui.label(f'Hello, {username}').classes(
                        'text-sm font-medium text-gray-700')

                # 用户头像图标
                ui.icon(
                    'account_circle', size='lg', color='primary')

                # 下拉菜单
                with ui.menu() as menu:
                    ui.menu_item('Profile', lambda: ui.navigate.to('/profile'))
                    ui.menu_item(
                        'Settings', lambda: ui.navigate.to('/settings'))
                    ui.separator()
                    ui.menu_item('Logout', on_logout)

                # 主菜单按钮
                ui.button(icon='more_vert',
                          #   on_click=lambda: menu.open(),
                          ).props('flat round')

                ui.tooltip('Profile')

            with ui.row().classes('items-center gap-3'):
                # 通知图标
                with ui.menu() as notification_menu:
                    ui.menu_item('No new notifications')

                # 通知菜单按钮
                ui.button(icon='notifications',
                          #   on_click=lambda: notification_menu.open(),
                          color='primary').props('flat round')

                ui.tooltip('Notifications')

        else:
            # 未登录用户的显示
            with ui.row().classes('items-center gap-3'):
                ui.label('Welcome, Guest').classes('text-sm text-gray-600')

                # 登录/注册按钮
                ui.button('Login', on_click=lambda: ui.navigate.to('/login'),
                          color='primary', icon='login').props('outline')
                ui.button('Sign Up', on_click=lambda: ui.navigate.to('/register'),
                          color='positive').props('outline')


def on_logout():
    """登出处理函数"""
    app.storage.user.clear()
    ui.navigate.to('/login')
    ui.notify('已成功登出', color='positive')


def create_footer():
    """创建公共footer"""
    with ui.footer(fixed=False).classes('bg-gray-50 border-t mt-8'):
        with ui.column().classes('w-full max-w-6xl mx-auto p-6 gap-4'):
            # Footer上半部分：链接和联系方式
            with ui.grid(columns=3).classes('w-full gap-8'):
                # 公司信息
                with ui.column():
                    ui.label('MyApp').classes(
                        'text-xl font-bold text-gray-800 mb-2')
                    ui.label('Making your life easier with our amazing products.').classes(
                        'text-gray-600')
                    with ui.row().classes('gap-3 mt-3'):
                        ui.button(
                            icon='facebook',
                            color='primary',
                            on_click=lambda: ui.run_javascript(
                                "window.open('https://facebook.com','_blank')")
                        ).props('flat round')

                        ui.button(
                            icon='face',
                            color='primary',
                            on_click=lambda: ui.run_javascript(
                                "window.open('https://github.com','_blank')")
                        ).props('flat round')

                # 快速链接
                with ui.column():
                    ui.label('Quick Links').classes(
                        'font-bold text-gray-700 mb-3')
                    ui.link(
                        'Home', '/').classes('text-gray-600 hover:text-blue-600 no-underline block py-1')
                    ui.link('About Us', '/about').classes(
                        'text-gray-600 hover:text-blue-600 no-underline block py-1')
                    ui.link('Services', '/services').classes(
                        'text-gray-600 hover:text-blue-600 no-underline block py-1')
                    ui.link('Contact', '/contact').classes(
                        'text-gray-600 hover:text-blue-600 no-underline block py-1')

                # 联系方式
                with ui.column():
                    ui.label('Contact Us').classes(
                        'font-bold text-gray-700 mb-3')
                    with ui.row().classes('items-center gap-2 text-gray-600'):
                        ui.icon('email', size='sm')
                        ui.label('contact@myapp.com')
                    with ui.row().classes('items-center gap-2 text-gray-600'):
                        ui.icon('phone', size='sm')
                        ui.label('+1 (555) 123-4567')
                    with ui.row().classes('items-center gap-2 text-gray-600'):
                        ui.icon('location_on', size='sm')
                        ui.label('123 Main St, City, Country')

            # 分隔线
            ui.separator()

            # Footer下半部分：版权信息
            with ui.row().classes('w-full justify-between items-center'):
                ui.label('© 2024 MyApp. All rights reserved.').classes(
                    'text-sm text-gray-500')
                with ui.row().classes('gap-6 text-sm'):
                    ui.link('Privacy Policy', '/privacy').classes(
                        'text-gray-500 hover:text-gray-700 no-underline')
                    ui.link('Terms of Service', '/terms').classes(
                        'text-gray-500 hover:text-gray-700 no-underline')
                    ui.link('Cookie Policy', '/cookies').classes(
                        'text-gray-500 hover:text-gray-700 no-underline')
