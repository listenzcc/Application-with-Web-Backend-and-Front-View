from functools import wraps
from typing import Callable, Optional
from nicegui import app, ui
from omegaconf import OmegaConf

conf = OmegaConf.load('./conf/project.yml')
project_name = conf['name']
email = conf['email']

# 全局深蓝底、白字主题。页面里硬编码的浅色 Tailwind 类在这里统一翻转，
# 免得逐页去改（后续新页面只要继续用那些类名就自动是深色）。
THEME_CSS = '''
<style>
    body {
        background-color: #0a1a33;
        background-image: url('/static/img/background.avif');
        background-size: cover;
        background-position: center;
        background-repeat: no-repeat;
        background-attachment: fixed;
        background-blend-mode: multiply;
    }
    /* 浅色面板 -> 深蓝面板 */
    .bg-white, .bg-gray-50, .bg-gray-100, .bg-blue-50, .bg-blue-100,
    .bg-green-50, .bg-amber-50, .bg-red-50, .bg-purple-50 {
        background-color: #10233f !important;
    }
    /* 灰字 -> 亮字 */
    .text-gray-800, .text-gray-700, .text-gray-600 {
        color: #dbe4f4 !important;
    }
    .text-gray-500, .text-gray-400 {
        color: #8fa3c8 !important;
    }
    /* 深色语义文字在深蓝底上偏暗，整体提亮 */
    .text-blue-700, .text-blue-800 { color: #7ab3ff !important; }
    .text-amber-700 { color: #ffd166 !important; }
    .text-purple-700 { color: #c4a5ff !important; }
    .text-green-700 { color: #7ee2a0 !important; }
    /* Quasar 组件 */
    .q-card { background-color: #10233f !important; color: #dbe4f4 !important; }
    .q-header, .q-footer { background-color: #0d2140 !important; }
    .q-table { color: #dbe4f4 !important; }
    .q-table thead th, .q-table tbody td { color: #dbe4f4 !important; }
    .q-separator { background-color: #24406b !important; }
</style>
'''


def _apply_theme():
    """每页开场切到暗色模式并注入全局主题样式。"""
    ui.dark_mode(True)
    ui.add_head_html(THEME_CSS)


def with_layout_full_width(func: Callable) -> Callable:
    """为页面添加公共header和footer的装饰器"""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        # 深蓝主题 + 公共header
        _apply_theme()
        create_header()

        # 页面主要内容区域
        with ui.column().classes('w-full mx-auto p-4 min-h-[calc(100vh-130px)]'):
            await func(*args, **kwargs)

        # 添加公共footer
        create_footer()

    return wrapper


def with_layout(func: Callable) -> Callable:
    """为页面添加公共header和footer的装饰器"""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        # 深蓝主题 + 公共header
        _apply_theme()
        create_header()

        # 页面主要内容区域
        with ui.column().classes('w-full max-w-7xl mx-auto p-4 min-h-[calc(100vh-130px)]'):
            await func(*args, **kwargs)

        # 添加公共footer
        create_footer()

    return wrapper


def create_header():
    """创建公共header，显示用户状态"""
    with ui.header().classes('bg-[#0d2140] shadow-sm border-b border-[#24406b]') as header:
        with ui.row().classes('w-full justify-between items-center p-4'):
            # 左侧：Logo和导航
            with ui.row().classes('items-center gap-8'):
                # Logo
                ui.link(
                    project_name, '/').classes('text-2xl font-bold text-white no-underline hover:text-blue-200')

                # 主导航
                with ui.row().classes('gap-6'):
                    ui.link('介绍页', '/',
                            ).classes('text-gray-200 hover:text-white no-underline font-medium')

                    # 拉格朗日模型与追溯模型同属 HYSPLIT，收进一个下拉菜单；
                    # 高斯模型保留单独入口。
                    with ui.button('扩散仿真(拉格朗日/追溯)') \
                            .props('flat dense no-caps color=white') \
                            .style('min-height:0; padding:0;') \
                            .classes('font-medium items-center'):
                        with ui.menu().props('auto-close'):
                            ui.menu_item('拉格朗日模型',
                                         lambda: ui.navigate.to('/simulationHysplit'))
                            ui.menu_item('追溯模型',
                                         lambda: ui.navigate.to('/simulationBackward'))
                    ui.link('扩散仿真(高斯模型)', '/simulationGaussian',
                            ).classes('text-gray-200 hover:text-white no-underline font-medium')
                    # FDS 二维模拟入口已下线（/simulationFDS 页面代码保留）
                    ui.link('扩散仿真(CFD三维模型)', '/simulationFDS3D',
                            ).classes('text-gray-200 hover:text-white no-underline font-medium')
                    ui.link('仿真案例', '/caseBrowser',
                            ).classes('text-gray-200 hover:text-white no-underline font-medium')
                    ui.link('气体管理', '/gasExplorer',
                            ).classes('text-gray-200 hover:text-white no-underline font-medium')
                    ui.link('化学品管理', '/chemicalExplorer',
                            ).classes('text-gray-200 hover:text-white no-underline font-medium')
                    ui.link('权限管理', '/privilege',
                            ).classes('text-gray-200 hover:text-white no-underline font-medium')
                    ui.link('传感器管理', '/sensors',
                            ).classes('text-gray-200 hover:text-white no-underline font-medium')
                    ui.link('事故教育', '/accidents',
                            ).classes('text-gray-200 hover:text-white no-underline font-medium')

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
    with ui.footer(fixed=False).classes('bg-[#0d2140] border-t border-[#24406b] mt-8'):
        with ui.column().classes('w-full max-w-6xl mx-auto p-6 gap-4'):
            # Footer上半部分：链接和联系方式
            with ui.grid(columns=3).classes('w-full gap-8'):
                # 公司信息
                with ui.column():
                    ui.label(project_name).classes(
                        'text-xl font-bold text-gray-800 mb-2')
                    ui.label('Relax and take a very deep breathe.').classes(
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
                        ui.label(conf['email'])
                    with ui.row().classes('items-center gap-2 text-gray-600'):
                        ui.icon('phone', size='sm')
                        ui.label(conf['phone'])
                    with ui.row().classes('items-center gap-2 text-gray-600'):
                        ui.icon('location_on', size='sm')
                        ui.label(conf['location'])

            # 分隔线
            ui.separator()

            # Footer下半部分：版权信息
            with ui.row().classes('w-full justify-between items-center'):
                ui.label(f'© 2024 {project_name}. All rights reserved.').classes(
                    'text-sm text-gray-500')
                with ui.row().classes('gap-6 text-sm'):
                    ui.link('Privacy Policy', '/privacy').classes(
                        'text-gray-500 hover:text-gray-700 no-underline')
                    ui.link('Terms of Service', '/terms').classes(
                        'text-gray-500 hover:text-gray-700 no-underline')
                    ui.link('Cookie Policy', '/cookies').classes(
                        'text-gray-500 hover:text-gray-700 no-underline')
