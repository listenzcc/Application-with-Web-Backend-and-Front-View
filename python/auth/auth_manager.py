# auth_manager.py
import re
from sqlalchemy.orm import Session
from typing import List, Optional
from .models import User, Permission, RoleEnum, Base


class PermissionManager:
    """权限管理器"""

    # 预定义权限
    PERMISSIONS = {
        # 基本权限
        'view_profile': '查看个人资料',
        'edit_profile': '编辑个人资料',

        # 用户权限
        'view_users': '查看用户列表',
        'create_user': '创建用户',
        'edit_user': '编辑用户',
        'delete_user': '删除用户',

        # 内容权限
        'view_content': '查看内容',
        'create_content': '创建内容',
        'edit_content': '编辑内容',
        'delete_content': '删除内容',

        # 管理权限
        'manage_permissions': '管理权限',
        'view_logs': '查看日志',
        'manage_system': '管理系统设置',
        'manage_sessions': '管理登陆会话'
    }

    # 角色默认权限
    ROLE_PERMISSIONS = {
        RoleEnum.GUEST.value: ['view_profile', 'view_content'],
        RoleEnum.USER.value: ['view_profile', 'edit_profile', 'view_content', 'create_content', 'edit_content'],
        RoleEnum.ADMIN.value: list(PERMISSIONS.keys())  # 管理员拥有所有权限
    }

    def __init__(self, session: Session):
        self.session = session

    def initialize_permissions(self):
        """初始化权限到数据库"""
        for perm_name, description in self.PERMISSIONS.items():
            if not self.session.query(Permission).filter_by(name=perm_name).first():
                permission = Permission(
                    name=perm_name, description=description)
                self.session.add(permission)
        self.session.commit()

    def assign_role_permissions(self, user: User):
        """为用户分配角色对应的默认权限"""
        # 清除现有权限
        user.permissions.clear()

        # 分配新权限
        if user.role in self.ROLE_PERMISSIONS:
            for perm_name in self.ROLE_PERMISSIONS[user.role]:
                permission = self.session.query(
                    Permission).filter_by(name=perm_name).first()
                if permission and permission not in user.permissions:
                    user.permissions.append(permission)

        self.session.commit()

    def add_permission_to_user(self, user_id: int, permission_name: str) -> bool:
        """为用户添加单个权限"""
        user = self.session.query(User).get(user_id)
        permission = self.session.query(Permission).filter_by(
            name=permission_name).first()

        if user and permission and permission not in user.permissions:
            user.permissions.append(permission)
            self.session.commit()
            return True
        return False

    def remove_permission_from_user(self, user_id: int, permission_name: str) -> bool:
        """移除用户的单个权限"""
        user = self.session.query(User).get(user_id)
        permission = self.session.query(Permission).filter_by(
            name=permission_name).first()

        if user and permission and permission in user.permissions:
            user.permissions.remove(permission)
            self.session.commit()
            return True
        return False

    def check_permission(self, user: User, permission_name: str) -> bool:
        """检查用户是否有特定权限"""
        # 管理员自动拥有所有权限
        if user.is_admin():
            return True

        return user.has_permission(permission_name)

    def check_permission_pattern(self, user: User, pattern: str) -> bool:
        """使用正则表达式检查权限模式"""
        # 管理员自动通过
        if user.is_admin():
            return True

        # 检查是否有匹配的权限
        for permission in user.permissions:
            if re.match(pattern, permission.name):
                return True
        return False
