# database.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from .models import Base
from .auth_manager import PermissionManager
from . import logger


class DatabaseManager:
    """数据库管理器"""

    def __init__(self, database_url: str, echo: bool = False):
        """
        初始化数据库管理器

        Args:
            database_url: 数据库连接URL (e.g., 'sqlite:///auth.db')
            echo: 是否输出SQL语句
        """
        self.engine = create_engine(database_url, echo=echo)
        self.SessionLocal = scoped_session(
            sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        )

    def create_tables(self):
        """创建所有表"""
        Base.metadata.create_all(bind=self.engine)
        logger.info("数据库表创建完成")

    def drop_tables(self):
        """删除所有表"""
        Base.metadata.drop_all(bind=self.engine)
        logger.info("数据库表已删除")

    def get_session(self):
        """获取数据库会话"""
        return self.SessionLocal()

    def close_session(self):
        """关闭当前会话"""
        self.SessionLocal.remove()

    def initialize_data(self):
        """初始化基础数据"""
        session = self.get_session()
        try:
            # 初始化权限
            permission_manager = PermissionManager(session)
            permission_manager.initialize_permissions()

            # 创建默认管理员用户（如果不存在）
            from .user_service import UserService
            user_service = UserService(session)

            admin = user_service.get_user_by_username("admin")
            if not admin:
                user_service.create_user(
                    username="admin",
                    email="admin@example.com",
                    password="admin123",
                    role="admin"
                )
                logger.info("默认管理员用户已创建")

            session.commit()
            logger.info("数据初始化完成")

        except Exception as e:
            session.rollback()
            logger.error(f"数据初始化失败: {e}")
            raise
        finally:
            self.close_session()
