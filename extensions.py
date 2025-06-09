# extensions.py
import os
import redis
import logging
from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)

# Redis 연결 설정
REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
redis_client = None
try:
    redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    redis_client.ping()
    logger.info(f"Successfully connected to Redis at {REDIS_URL}")
except redis.exceptions.ConnectionError as e:
    logger.error(f"Could not connect to Redis at {REDIS_URL}: {e}")
    redis_client = None
except Exception as e:
    logger.error(f"Unexpected error while connecting to Redis: {e}")
    redis_client = None

# 스케줄러 설정
scheduler = BackgroundScheduler(daemon=True) 