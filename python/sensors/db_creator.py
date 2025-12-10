# db_creator.py
import sqlite3
from datetime import datetime
from .log import logger


def init_database():
    """初始化数据库和表结构"""
    conn = sqlite3.connect('db/sensor_data.db')
    cursor = conn.cursor()

    # 创建传感器信息表
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS sensors (
        sensor_id TEXT PRIMARY KEY,
        x_position REAL NOT NULL,
        y_position REAL NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # 创建传感器数据表
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS sensor_readings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sensor_id TEXT NOT NULL,
        value REAL NOT NULL,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (sensor_id) REFERENCES sensors (sensor_id)
    )
    ''')

    # 创建索引以提高查询性能（需要单独执行）
    cursor.execute(
        'CREATE INDEX IF NOT EXISTS idx_sensor_time ON sensor_readings(sensor_id, timestamp)')
    cursor.execute(
        'CREATE INDEX IF NOT EXISTS idx_timestamp ON sensor_readings(timestamp)')
    cursor.execute(
        'CREATE INDEX IF NOT EXISTS idx_sensor_id ON sensor_readings(sensor_id)')
    cursor.execute(
        'CREATE INDEX IF NOT EXISTS idx_sensors_id ON sensors(sensor_id)')

    conn.commit()

    # 验证表是否创建成功
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    logger.info("创建的表:")
    for table in tables:
        logger.debug(f"  - {table[0]}")

    # 查看索引
    cursor.execute("SELECT name FROM sqlite_master WHERE type='index'")
    indexes = cursor.fetchall()
    logger.info("创建的索引:")
    for index in indexes:
        logger.debug(f"  - {index[0]}")

    conn.close()
    logger.info("数据库初始化完成！")


if __name__ == "__main__":
    init_database()
