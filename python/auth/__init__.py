from loguru import logger

logger.add('log/auth.log', rotation='1MB')
