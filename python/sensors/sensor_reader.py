# sensor_reader.py
import sqlite3
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import pandas as pd


class SensorDataReader:
    def __init__(self, db_path='db/sensor_data.db'):
        self.db_path = db_path

    def get_recent_data(self, sensor_id: Optional[str] = None,
                        minutes: int = 60) -> List[Dict]:
        """
        获取最近指定时长的数据

        Args:
            sensor_id: 传感器ID，None表示所有传感器
            minutes: 最近多少分钟的数据

        Returns:
            传感器数据列表
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        time_threshold = datetime.now() - timedelta(minutes=minutes)

        try:
            if sensor_id:
                cursor.execute('''
                SELECT sr.*, s.x_position, s.y_position
                FROM sensor_readings sr
                JOIN sensors s ON sr.sensor_id = s.sensor_id
                WHERE sr.sensor_id = ? AND sr.timestamp >= ?
                ORDER BY sr.timestamp DESC
                ''', (sensor_id, time_threshold))
            else:
                cursor.execute('''
                SELECT sr.*, s.x_position, s.y_position
                FROM sensor_readings sr
                JOIN sensors s ON sr.sensor_id = s.sensor_id
                WHERE sr.timestamp >= ?
                ORDER BY sr.timestamp DESC
                ''', (time_threshold,))

            rows = cursor.fetchall()
            return [dict(row) for row in rows]

        finally:
            conn.close()

    def get_latest_data(self, sensor_id: Optional[str] = None) -> List[Dict]:
        """
        获取每个传感器最近一个时间点的数据

        Args:
            sensor_id: 传感器ID，None表示所有传感器

        Returns:
            最新传感器数据列表
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            if sensor_id:
                # 获取指定传感器的最新数据
                cursor.execute('''
                SELECT sr.*, s.x_position, s.y_position
                FROM sensor_readings sr
                JOIN sensors s ON sr.sensor_id = s.sensor_id
                WHERE sr.sensor_id = ?
                ORDER BY sr.timestamp DESC
                LIMIT 1
                ''', (sensor_id,))
            else:
                # 使用子查询获取每个传感器的最新数据（兼容旧版本SQLite）
                cursor.execute('''
                SELECT sr.*, s.x_position, s.y_position
                FROM sensor_readings sr
                JOIN sensors s ON sr.sensor_id = s.sensor_id
                WHERE sr.timestamp = (
                    SELECT MAX(timestamp)
                    FROM sensor_readings sr2
                    WHERE sr2.sensor_id = sr.sensor_id
                )
                ORDER BY sr.sensor_id
                ''')

            rows = cursor.fetchall()
            return [dict(row) for row in rows]

        finally:
            conn.close()

    def get_sensor_info(self) -> List[Dict]:
        """获取所有传感器信息"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            cursor.execute('SELECT * FROM sensors ORDER BY sensor_id')
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_data_as_dataframe(self, sensor_id: Optional[str] = None,
                              start_time: Optional[datetime] = None,
                              end_time: Optional[datetime] = None) -> pd.DataFrame:
        """
        获取数据为Pandas DataFrame格式

        Args:
            sensor_id: 传感器ID
            start_time: 开始时间
            end_time: 结束时间

        Returns:
            DataFrame格式的数据
        """
        conn = sqlite3.connect(self.db_path)

        try:
            query = '''
            SELECT sr.*, s.x_position, s.y_position
            FROM sensor_readings sr
            JOIN sensors s ON sr.sensor_id = s.sensor_id
            WHERE 1=1
            '''
            params = []

            if sensor_id:
                query += ' AND sr.sensor_id = ?'
                params.append(sensor_id)

            if start_time:
                query += ' AND sr.timestamp >= ?'
                params.append(start_time)

            if end_time:
                query += ' AND sr.timestamp <= ?'
                params.append(end_time)

            query += ' ORDER BY sr.timestamp'

            df = pd.read_sql_query(query, conn, params=params)

            # 转换时间列
            if 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'])

            return df

        finally:
            conn.close()


def demo_reader():
    """演示读取功能"""
    reader = SensorDataReader()

    print("=== 所有传感器信息 ===")
    sensors = reader.get_sensor_info()
    for sensor in sensors:
        print(
            f"ID: {sensor['sensor_id']}, 位置: ({sensor['x_position']}, {sensor['y_position']})")

    print("\n=== 最近5分钟所有传感器数据 ===")
    recent_data = reader.get_recent_data(minutes=5)
    for data in recent_data[:5]:  # 只显示前5条
        print(f"{data['sensor_id']} - {data['timestamp']}: {data['value']:.2f}")

    print("\n=== 每个传感器的最新数据 ===")
    latest_data = reader.get_latest_data()
    for data in latest_data:
        print(f"{data['sensor_id']} - 最新值: {data['value']:.2f}, "
              f"时间: {data['timestamp']}")

    print("\n=== 指定传感器(sensor_001)的最新数据 ===")
    sensor_data = reader.get_latest_data('sensor_001')
    if sensor_data:
        data = sensor_data[0]
        print(f"值: {data['value']:.2f}, 时间: {data['timestamp']}")


if __name__ == "__main__":
    demo_reader()
