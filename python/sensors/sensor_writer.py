# sensor_writer.py
import sqlite3
import time
import random
from datetime import datetime, timedelta
from typing import Optional
from .log import logger


class SensorDataWriter:
    def __init__(self, db_path='db/sensor_data.db'):
        self.db_path = db_path
        self._init_connection()

    def _init_connection(self):
        """初始化数据库连接"""
        self.conn = sqlite3.connect(self.db_path)
        self.cursor = self.conn.cursor()

    def register_sensor(self, sensor_id: str, x: float, y: float):
        """注册新传感器"""
        try:
            self.cursor.execute('''
            INSERT OR REPLACE INTO sensors (sensor_id, x_position, y_position, last_updated)
            VALUES (?, ?, ?, ?)
            ''', (sensor_id, x, y, datetime.now()))
            self.conn.commit()
            logger.debug(f"传感器 {sensor_id} 注册成功 - 位置({x}, {y})")
            return True
        except Exception as e:
            logger.error(f"注册传感器失败: {e}")
            return False

    def delete_sensor(self, sensor_id: str):
        '''
        删除指定ID的传感器

        :param self: 类实例
        :param sensor_id: 要删除的传感器ID
        :type sensor_id: str
        :return: 删除成功返回True，失败返回False
        :rtype: bool
        '''
        try:
            # 执行删除操作
            self.cursor.execute('''
                DELETE FROM sensors
                WHERE sensor_id = ?
            ''', (sensor_id,))  # 注意这里应该是元组，后面要加逗号

            # 检查是否成功删除了记录
            if self.cursor.rowcount == 0:
                logger.warning(f"传感器 {sensor_id} 不存在，无法删除")
                return False

            self.conn.commit()
            logger.debug(f"传感器 {sensor_id} 删除成功")
            return True
        except Exception as e:
            logger.error(f'删除传感器失败: {e}')
            # 发生异常时回滚事务
            self.conn.rollback()
            return False

    def write_sensor_data(self, sensor_id: str, value: float,
                          timestamp: Optional[datetime] = None):
        """写入传感器数据"""
        try:
            if timestamp is None:
                timestamp = datetime.now()

            # 写入传感器读数
            self.cursor.execute('''
            INSERT INTO sensor_readings (sensor_id, value, timestamp)
            VALUES (?, ?, ?)
            ''', (sensor_id, value, timestamp))

            # 更新传感器的最后更新时间
            self.cursor.execute('''
            UPDATE sensors 
            SET last_updated = ?
            WHERE sensor_id = ?
            ''', (timestamp, sensor_id))

            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"写入数据失败: {e}")
            return False

    def batch_write_data(self, sensor_data: list):
        """批量写入传感器数据"""
        try:
            current_time = datetime.now()

            # 批量插入读数
            readings = [(data['sensor_id'], data['value'],
                        data.get('timestamp', current_time))
                        for data in sensor_data]

            self.cursor.executemany('''
            INSERT INTO sensor_readings (sensor_id, value, timestamp)
            VALUES (?, ?, ?)
            ''', readings)

            # 批量更新传感器最后更新时间
            sensor_ids = list(set(data['sensor_id'] for data in sensor_data))
            for sensor_id in sensor_ids:
                self.cursor.execute('''
                UPDATE sensors 
                SET last_updated = ?
                WHERE sensor_id = ?
                ''', (current_time, sensor_id))

            self.conn.commit()
            logger.debug(f"批量写入 {len(sensor_data)} 条数据成功")
            return True
        except Exception as e:
            logger.error(f"批量写入失败: {e}")
            return False

    def close(self):
        """关闭数据库连接"""
        if hasattr(self, 'conn'):
            self.conn.close()


def simulate_sensor_data():
    """模拟传感器数据写入"""
    writer = SensorDataWriter()

    # 注册一些示例传感器
    sensors = [
        {'id': 'sensor_001', 'x': 10.5, 'y': 20.3},
        {'id': 'sensor_002', 'x': 15.2, 'y': 25.8},
        {'id': 'sensor_003', 'x': 8.7, 'y': 18.4},
    ]

    for sensor in sensors:
        writer.register_sensor(sensor['id'], sensor['x'], sensor['y'])

    # 模拟数据写入（运行10次）
    logger.debug("\n开始模拟数据写入...")
    for i in range(10):
        for sensor in sensors:
            # 生成随机数值（模拟传感器读数）
            value = random.uniform(20.0, 30.0)
            writer.write_sensor_data(sensor['id'], value)
            logger.debug(f"写入 {sensor['id']}: {value:.2f}")

        time.sleep(2)  # 模拟2秒更新间隔

    writer.close()
    logger.debug("模拟完成！")


if __name__ == "__main__":
    # 直接运行可以测试数据写入
    simulate_sensor_data()
