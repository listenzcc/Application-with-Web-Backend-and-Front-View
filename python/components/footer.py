from functools import wraps
from typing import Callable
from nicegui import ui


def with_footer(func: Callable) -> Callable:
    """为页面添加公共footer的装饰器"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        # 先调用原始函数创建页面内容
        func(*args, **kwargs)

        # 添加公共footer
        with ui.footer().classes('bg-blue-100'):
            with ui.row().classes('w-full justify-center items-center gap-4 p-4'):
                ui.link('Home', '/').classes('text-blue-600 hover:text-blue-800')
                ui.link(
                    'About', '/about').classes('text-blue-600 hover:text-blue-800')
                ui.link(
                    'Contact', '/contact').classes('text-blue-600 hover:text-blue-800')
                ui.link('Privacy Policy',
                        '/privacy').classes('text-blue-600 hover:text-blue-800')

            with ui.row().classes('w-full justify-center text-sm text-gray-500'):
                ui.label('© 2024 My Company. All rights reserved.')
    return wrapper
