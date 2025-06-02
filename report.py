# report.py

import os
import redis
import pickle
import datetime
from flask import Blueprint, render_template, request, url_for

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

    # 3) 단순 텍스트 → 줄바꿈을 <br>로 변환하여 반환
    return text.replace('\n', '<br>')


def list_report_dates(prefix):
    """
    Redis에 저장된 키 중 prefix로 시작하는 것들을 스캔하여, 날짜 문자열 목록을 반환.
    예: prefix="dailyreport-", 실제 키 "dailyreport-20250601" -> "2025-06-01"
    """
    client = get_redis_client()
    pattern = f"{prefix}*"
    cursor = 0
    dates = []
    while True:
        cursor, keys = client.scan(cursor=cursor, match=pattern, count=100)
        for k in keys:
            # k는 string
            # prefix 길이를 제외한 나머지가 YYYYMMDD 형태임
            date_part = k[len(prefix):]  # e.g. "20250601"
            if len(date_part) == 8 and date_part.isdigit():
                # 포맷을 "YYYY-MM-DD"로 변환
                formatted = f"{date_part[0:4]}-{date_part[4:6]}-{date_part[6:8]}"
                dates.append(formatted)
        if cursor == 0:
            break
    # 내림차순 정렬 (가장 최근 날짜부터)
    dates.sort(reverse=True)
    return dates


@reports_bp.route('/')
def reports_index():
    """
    /reports 접근 시:
    - ?date=YYYY-MM-DD 쿼리스트링을 읽어 사용
      (없으면 오늘(UTC) 날짜를 기본으로 하지만, 인덱스 페이지에서는 필터 없이 전체 리스트를 보여줍니다.)
    - Redis에서 dailyreport-*, weeklyreport-*, monthlyreport-* 키를 스캔하여
      날짜 목록을 추출한 후 템플릿에 전달
    """
    # Redis 키에서 날짜들 조회
    daily_dates   = list_report_dates("dailyreport-")
    weekly_dates  = list_report_dates("weeklyreport-")
    monthly_dates = list_report_dates("monthlyreport-")

    return render_template(
        'reports.html',
        daily_dates=daily_dates,
        weekly_dates=weekly_dates,
        monthly_dates=monthly_dates
    )


@reports_bp.route('/daily')
def daily_report():
    """
    /reports/daily 경로
    - ?date=YYYY-MM-DD 파라미터를 읽어 사용
    - 없으면 오늘(UTC) 날짜를 기본으로 사용
    - Redis에서 `dailyreport-YYYYMMDD` 키로 리포트 조회
    """
    date_str = request.args.get('date')
    if not date_str:
        date_str = datetime.datetime.utcnow().strftime('%Y-%m-%d')

    # Redis에 저장된 키: 'dailyreport-YYYYMMDD'
    key_date = date_str.replace('-', '')           # e.g. "20250601"
    redis_key = f"dailyreport-{key_date}"          # e.g. "dailyreport-20250601"

    raw_report = load_report_from_redis(redis_key)
    if raw_report is None:
        return render_template(
            'report_detail.html',
            report_type='daily',
            date_str=date_str,
            report=None
        )

    return render_template(
        'report_detail.html',
        report_type='daily',
        date_str=date_str,
        report=raw_report
    )


@reports_bp.route('/weekly')
def weekly_report():
    """
    /reports/weekly 경로
    - ?date=YYYY-MM-DD 파라미터를 읽어 사용
    - 없으면 오늘(UTC) 날짜를 기본으로 사용
    - Redis에서 `weeklyreport-YYYYMMDD` 키로 리포트 조회
    """
    date_str = request.args.get('date')
    if not date_str:
        date_str = datetime.datetime.utcnow().strftime('%Y-%m-%d')

    key_date = date_str.replace('-', '')
    redis_key = f"weeklyreport-{key_date}"

    raw_report = load_report_from_redis(redis_key)
    if raw_report is None:
        return render_template(
            'report_detail.html',
            report_type='weekly',
            date_str=date_str,
            report=None
        )

    return render_template(
        'report_detail.html',
        report_type='weekly',
        date_str=date_str,
        report=raw_report
    )


@reports_bp.route('/monthly')
def monthly_report():
    """
    /reports/monthly 경로
    - ?date=YYYY-MM-DD 파라미터를 읽어 사용
    - 없으면 오늘(UTC) 날짜를 기본으로 사용
    - Redis에서 `monthlyreport-YYYYMMDD` 키로 리포트 조회
    """
    date_str = request.args.get('date')
    if not date_str:
        date_str = datetime.datetime.utcnow().strftime('%Y-%m-%d')

    key_date = date_str.replace('-', '')
    redis_key = f"monthlyreport-{key_date}"

    raw_report = load_report_from_redis(redis_key)
    if raw_report is None:
        return render_template(
            'report_detail.html',
            report_type='monthly',
            date_str=date_str,
            report=None
        )

    return render_template(
        'report_detail.html',
        report_type='monthly',
        date_str=date_str,
        report=raw_report
    )
