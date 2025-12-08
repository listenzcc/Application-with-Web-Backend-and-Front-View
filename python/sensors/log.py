from loguru import logger

logger.add('log/sensors.log', rotation='1MB')
