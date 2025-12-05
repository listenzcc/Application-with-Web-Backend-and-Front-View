# decorators.py
from functools import wraps
from typing import Callable, Optional
from .models import User
from .auth_manager import PermissionManager
from . import logger


class AuthContext:
    """认证上下文管理器"""

    def __init__(self, user_service, permission_manager):
        self.user_service = user_service
        self.permission_manager = permission_manager
        self.current_user = None

    def set_current_user(self, user: User):
        """设置当前用户"""
        self.current_user = user

    def check_permission(self, permission_name: str) -> bool:
        """检查当前用户权限"""
        if not self.current_user:
            return False
        return self.permission_manager.check_permission(self.current_user, permission_name)


def require_permission(permission_name: str):
    """权限检查装饰器"""
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            # 检查是否有auth_context属性
            if not hasattr(self, 'auth_context'):
                logger.error("对象没有auth_context属性")
                raise PermissionError("Authentication context not found")

            # 检查权限
            if not self.auth_context.check_permission(permission_name):
                logger.warning(f"权限拒绝: {permission_name}")
                raise PermissionError(
                    f"Insufficient permissions: {permission_name}")

            return func(self, *args, **kwargs)
        return wrapper
    return decorator


def require_role(role_name: str):
    """角色检查装饰器"""
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            if not hasattr(self, 'auth_context'):
                logger.error("对象没有auth_context属性")
                raise PermissionError("Authentication context not found")

            if not self.auth_context.current_user:
                logger.warning("未认证用户尝试访问")
                raise PermissionError("User not authenticated")

            if not self.auth_context.current_user.has_role(role_name):
                logger.warning(f"角色拒绝: {role_name}")
                raise PermissionError(f"Insufficient role: {role_name}")

            return func(self, *args, **kwargs)
        return wrapper
    return decorator


class PermissionChecker:
    """权限检查器（用于函数式编程）"""

    def __init__(self, auth_context: AuthContext):
        self.auth_context = auth_context

    def check(self, permission_name: str) -> bool:
        """检查权限"""
        return self.auth_context.check_permission(permission_name)

    def require(self, permission_name: str):
        """要求权限（装饰器版本）"""
        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                if not self.check(permission_name):
                    raise PermissionError(
                        f"Insufficient permissions: {permission_name}")
                return func(*args, **kwargs)
            return wrapper
        return decorator
