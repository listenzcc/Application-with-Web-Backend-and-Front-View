from typing import Dict, List
from datetime import datetime, timedelta
import uuid

# 用户会话管理类


class UserSessionManager:
    def __init__(self):
        # 存储活跃用户会话 {session_id: user_data}
        self.active_sessions: Dict[str, Dict] = {}

    def add_session(self, user_data: dict) -> str:
        """添加新会话"""
        session_id = str(uuid.uuid4())
        self.active_sessions[session_id] = {
            **user_data,
            'session_id': session_id,
            'login_time': datetime.now(),
            'last_activity': datetime.now(),
            'ip_address': None  # 可以从 request 中获取
        }
        return session_id

    def remove_session(self, session_id: str):
        """移除会话"""
        if session_id in self.active_sessions:
            del self.active_sessions[session_id]

    def update_activity(self, session_id: str):
        """更新最后活动时间"""
        if session_id in self.active_sessions:
            self.active_sessions[session_id]['last_activity'] = datetime.now()

    def get_active_users(self) -> List[Dict]:
        """获取所有活跃用户"""
        return list(self.active_sessions.values())

    def get_user_by_id(self, user_id: int) -> List[Dict]:
        """根据用户ID查找会话"""
        return [session for session in self.active_sessions.values()
                if session.get('id') == user_id]

    def cleanup_inactive_sessions(self, timeout_minutes: int = 30):
        """清理不活跃的会话"""
        cutoff = datetime.now() - timedelta(minutes=timeout_minutes)
        inactive_keys = [
            key for key, session in self.active_sessions.items()
            if session['last_activity'] < cutoff
        ]
        for key in inactive_keys:
            del self.active_sessions[key]
        return len(inactive_keys)


# 全局实例
session_manager = UserSessionManager()
