# keep_writing.py

import time
from random import random, choice
from datetime import datetime
from sensor_writer import SensorDataWriter
from sensor_reader import SensorDataReader
from log import logger

if __name__ == '__main__':
    reader = SensorDataReader()
    sensors = reader.get_sensor_info()
    print(sensors)

    # 创建写入器实例
    writer = SensorDataWriter()

    while True:
        # 写入一些测试数据
        test_data = [{
            'sensor_id': e['sensor_id'],
            'value': random()
        } for e in sensors]
        writer.batch_write_data(test_data)

        # 写入带时间戳的数据
        sensor = choice(sensors)
        custom_time = datetime.now()
        writer.write_sensor_data(sensor['sensor_id'], random(), custom_time)

        time.sleep(10 + random() * 5)
