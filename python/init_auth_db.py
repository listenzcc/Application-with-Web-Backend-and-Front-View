# init_auth_db.py
from auth.database import DatabaseManager
from auth.user_service import UserService
from auth.auth_manager import PermissionManager
from auth.decorators import AuthContext
from auth.models import RoleEnum
from auth.decorators import require_permission, require_role


def main():
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

        # 4. 用户认证
        authenticated_user = user_service.authenticate_user(
            "testuser", "password123")
        if authenticated_user:
            print(f"用户认证成功: {authenticated_user.username}")
            auth_context.set_current_user(authenticated_user)

        # 5. 权限检查示例
        # 检查特定权限
        can_view_content = permission_manager.check_permission(
            authenticated_user,
            "view_content"
        )
        print(f"是否可以查看内容: {can_view_content}")

        # 检查用户角色
        print(f"用户角色: {authenticated_user.role}")
        print(f"是否是管理员: {authenticated_user.is_admin()}")

        # 6. 权限管理示例
        # 为用户添加额外权限
        permission_manager.add_permission_to_user(
            authenticated_user.id,
            "manage_permissions"
        )

        # 检查新权限
        can_manage = permission_manager.check_permission(
            authenticated_user,
            "manage_permissions"
        )
        print(f"是否可以管理权限: {can_manage}")

        # 7. 列出所有用户
        print("\n所有用户:")
        users = user_service.list_users()
        for user in users:
            print(f"  - {user.username} ({user.role}) - 活跃: {user.is_active}")

        # 8. 更新用户角色
        user_service.update_user_role(
            user_id=user1.id,
            new_role=RoleEnum.ADMIN.value,
            updater=authenticated_user  # 需要管理员权限
        )

    finally:
        db_manager.close_session()


class ContentManager:
    """示例：使用权限装饰器的内容管理器"""

    def __init__(self, auth_context):
        self.auth_context = auth_context

    @require_permission("view_content")
    def view_content(self, content_id: int):
        """查看内容（需要view_content权限）"""
        print(f"查看内容 {content_id}")
        return {"id": content_id, "content": "示例内容"}

    @require_permission("create_content")
    def create_content(self, content_data: dict):
        """创建内容（需要create_content权限）"""
        print(f"创建内容: {content_data}")
        return {"status": "success", "id": 1}

    @require_permission("edit_content")
    @require_role(RoleEnum.USER.value)
    def edit_content(self, content_id: int, updates: dict):
        """编辑内容（需要edit_content权限和USER角色）"""
        print(f"编辑内容 {content_id}: {updates}")
        return {"status": "success"}


if __name__ == "__main__":
    main()
