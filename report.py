# report.py

import os
import redis
import pickle
import datetime
from flask import Blueprint, render_template, request, jsonify

reports_bp = Blueprint('reports', __name__, url_prefix='/reports')


def get_redis_client():
    redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
    return redis.StrictRedis.from_url(redis_url, decode_responses=True)


def load_report_from_redis(key_name):
    """
    Redis에서 저장된 리포트를 읽어 옵니다.
    - pickle 직렬화된 경우: pickle.loads
    - JSON 형태일 경우: json.loads
    - 그 외 단순 텍스트라면 줄바꿈을 <br>로 변환하여 반환
    """
    client = get_redis_client()
    raw = client.get(key_name)
    if not raw:
        return None

    try:
        text = raw.decode() if isinstance(raw, bytes) else raw
    except Exception:
        return None

    # 1) pickle 시도
    try:
        return pickle.loads(raw)
    except Exception:
        pass

    # 2) JSON 시도
    try:
        import json
        return json.loads(text)
    except Exception:
        pass

    # 3) 단순 텍스트: 줄바꿈을 <br>로 변환하여 반환
    return text.replace('\n', '<br>')


def list_report_dates(prefix):
    """
    Redis에 저장된 키 중 prefix로 시작하는 것들을 스캔하여, 날짜 문자열 목록을 반환.
    ex) prefix="dailyreport-", 실제 키="dailyreport-20250601" → ["2025-06-01", ...]
    """
    client = get_redis_client()
    pattern = f"{prefix}*"
    cursor = 0
    dates = []
    while True:
        cursor, keys = client.scan(cursor=cursor, match=pattern, count=100)
        for k in keys:
            # k는 "dailyreport-YYYYMMDD"
            date_part = k[len(prefix):]
            if len(date_part) == 8 and date_part.isdigit():
                formatted = f"{date_part[0:4]}-{date_part[4:6]}-{date_part[6:8]}"
                dates.append(formatted)
        if cursor == 0:
            break
    # 내림차순 정렬(가장 최근 날짜부터)
    dates.sort(reverse=True)
    return dates


@reports_bp.route('/')
def reports_index():
    """
    /reports 경로
    - Redis에서 dailyreport-*, weeklyreport-*, monthlyreport-* 키를 스캔하여 날짜 목록을 추출
    - 각 섹션별로 가장 최근 날짜를 골라 그 리포트도 미리 로드
    """
    # 1) Redis에서 날짜 목록 가져오기
    daily_dates   = list_report_dates("dailyreport-")
    weekly_dates  = list_report_dates("weeklyreport-")
    monthly_dates = list_report_dates("monthlyreport-")

    # 2) 각 섹션별 가장 최근 리포트 콘텐츠 미리 로드
    daily_latest_report = None
    weekly_latest_report = None
    monthly_latest_report = None

    if daily_dates:
        latest = daily_dates[0]                    # "YYYY-MM-DD"
        key_date = latest.replace('-', '')         # "YYYYMMDD"
        redis_key = f"dailyreport-{key_date}"
        daily_latest_report = load_report_from_redis(redis_key)

    if weekly_dates:
        latest = weekly_dates[0]
        key_date = latest.replace('-', '')
        redis_key = f"weeklyreport-{key_date}"
        weekly_latest_report = load_report_from_redis(redis_key)

    if monthly_dates:
        latest = monthly_dates[0]
        key_date = latest.replace('-', '')
        redis_key = f"monthlyreport-{key_date}"
        monthly_latest_report = load_report_from_redis(redis_key)

    return render_template(
        'reports.html',
        daily_dates=daily_dates,
        weekly_dates=weekly_dates,
        monthly_dates=monthly_dates,
        daily_latest_report=daily_latest_report,
        weekly_latest_report=weekly_latest_report,
        monthly_latest_report=monthly_latest_report
    )


@reports_bp.route('/api/<report_type>')
def get_report_api(report_type):
    """
    AJAX 호출용: /reports/api/<report_type>?date=YYYY-MM-DD
    - report_type: 'daily', 'weekly', 'monthly'
    - Redis 키: '{report_type}report-YYYYMMDD'
    - JSON 형태로 {'content': 리포트 HTML 문자열} 반환
    """
    date_str = request.args.get('date')
    if not date_str or len(date_str) != 10:
        return jsonify({'content': "<p class='text-gray-500'>Invalid date format.</p>"})

    key_date = date_str.replace('-', '')  # "YYYYMMDD"
    redis_key = f"{report_type}report-{key_date}"

    content = load_report_from_redis(redis_key)
    if not content:
        msg = f"<p class='text-gray-500'>No {report_type} report available for {date_str}.</p>"
        return jsonify({'content': msg})

    return jsonify({'content': content})
