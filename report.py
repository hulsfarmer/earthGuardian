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
            # Redis는 bytes로 반환하므로, 디코딩
            text = raw.decode() if isinstance(raw, bytes) else raw

            # 1) pickle 시도
            try:
                return pickle.loads(raw)
            except Exception:
                # 2) JSON 시도
                try:
                    import json
                    return json.loads(text)
                except Exception:
                    # 3) 그냥 텍스트(plain string) → 줄바꿈을 <br>로 변환하여 리턴
                    return text.replace('\n', '<br>')
        except Exception:
            # 완전히 실패하면 None
            return None
    return None
