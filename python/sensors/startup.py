# startup.py
import time
from datetime import datetime
from db_creator import init_database
from sensor_writer import SensorDataWriter
from sensor_reader import SensorDataReader
from log import logger


def main():
    # 1. 初始化数据库
    logger.debug("正在初始化数据库...")
    init_database()

    from random import random

    # 2. 创建写入器实例
    writer = SensorDataWriter()

    # 3. 注册传感器
    logger.debug("注册传感器...")
    sensors = [
        {"id": "temp_001", "x": random(), "y": random()},
        {"id": "temp_002", "x": random(), "y": random()},
        {"id": "humidity_001", "x": random(), "y": random()},
    ]

    for sensor in sensors:
        writer.register_sensor(sensor["id"], sensor["x"], sensor["y"])

    # 4. 写入一些测试数据
    logger.debug("写入测试数据...")
    test_data = [
        {"sensor_id": "temp_001", "value": random()},
        {"sensor_id": "temp_002", "value": random()},
        {"sensor_id": "humidity_001", "value": random()},
    ]
    writer.batch_write_data(test_data)

    # 写入带时间戳的数据
    custom_time = datetime.now()
    writer.write_sensor_data("temp_001", random(), custom_time)
    writer.write_sensor_data("temp_005", random(), custom_time)

    # 等待一下
    time.sleep(1)

    # 再写入一条最新数据
    writer.write_sensor_data("temp_001", random())
    writer.close()

    # 5. 读取数据
    logger.debug("读取数据...")
    reader = SensorDataReader()

    # 获取所有传感器信息
    all_sensors = reader.get_sensor_info()
    logger.debug(f"共有 {len(all_sensors)} 个传感器:")
    for sensor in all_sensors:
        logger.debug(
            f"  {sensor['sensor_id']}: ({sensor['x_position']}, {sensor['y_position']})")

    # 获取最近10分钟数据
    logger.debug(f"最近10分钟的数据:")
    recent = reader.get_recent_data(minutes=10)
    for data in recent:
        logger.debug(
            f"  {data['sensor_id']} - {data['timestamp']}: {data['value']}")

    # 获取最新数据
    logger.debug(f"所有传感器的最新数据:")
    latest = reader.get_latest_data()
    for data in latest:
        logger.debug(
            f"  {data['sensor_id']}: {data['value']} (更新时间: {data['timestamp']})")

    # 获取DataFrame格式数据
    logger.debug(f"DataFrame格式数据:")
    df = reader.get_data_as_dataframe()
    logger.debug(f"数据形状: {df.shape}")
    if not df.empty:
        logger.debug(df[['sensor_id', 'value', 'timestamp']].head())


if __name__ == "__main__":
    main()
