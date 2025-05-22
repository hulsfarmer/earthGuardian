import os
import pickle
import redis

def get_report_from_redis(period_key):
    redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
    redis_client = redis.StrictRedis.from_url(redis_url)
    raw = redis_client.get(f'flask_cache_periodic_report_{period_key}')
    if raw:
        return pickle.loads(raw)
    return None

def get_redis_client():
    redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
    return redis.StrictRedis.from_url(redis_url)

def list_report_keys(report_type):
    """
    report_type: 'day', 'week', 'month'
    SCAN 명령을 사용하여 키 목록을 가져온다.
    """
    r = get_redis_client()
    pattern = f"{report_type}report-*"
    keys = []
    cursor = 0
    while True:
        cursor, batch = r.scan(cursor=cursor, match=pattern, count=100)
        keys.extend([k.decode() for k in batch])
        if cursor == 0:
            break
    keys.sort(reverse=True)
    return keys

def get_report(report_type, date_str):
    """
    report_type: 'day', 'week', 'month'
    date_str: '2025-05-22' 등
    """
    r = get_redis_client()
    key = f"{report_type}report-{date_str}"
    raw = r.get(key)
    if raw:
        try:
            return pickle.loads(raw)
        except Exception:
            # 혹시 JSON 등 다른 포맷일 경우
            import json
            return json.loads(raw)
    return None

# Removed functions: get_last_sunday, get_week_of_month, generate_periodic_report, generate_weekly_reports, generate_monthly_reports, generate_2025_reports, generate_daily_report, generate_daily_report_with_fallback, generate_weekly_report, generate_monthly_report 