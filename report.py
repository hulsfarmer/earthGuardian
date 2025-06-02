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

    # raw가 bytes 혹은 str 형태
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

    # 3) 단순 텍스트: 줄바꿈을 <br>로 바꾸어 반환
    return text.replace('\n', '<br>')


@reports_bp.route('/')
def reports_index():
    """
    /reports 경로
    - ?date=YYYY-MM-DD 파라미터를 읽어 사용
    - 없으면 오늘(UTC) 날짜 기본 사용
    - 일간/주간/월간 리포트 URL을 생성하여 템플릿에 전달
    """
    date_str = request.args.get('date')
    if not date_str:
        date_str = datetime.datetime.utcnow().strftime('%Y-%m-%d')

    daily_url   = url_for('reports.daily_report',   date=date_str)
    weekly_url  = url_for('reports.weekly_report',  date=date_str)
    monthly_url = url_for('reports.monthly_report', date=date_str)

    return render_template(
        'reports.html',
        date_str=date_str,
        daily_url=daily_url,
        weekly_url=weekly_url,
        monthly_url=monthly_url
    )


@reports_bp.route('/daily')
def daily_report():
    """
    /reports/daily 경로
    - ?date=YYYY-MM-DD 파라미터를 읽어 사용
    - 없으면 오늘(UTC) 날짜 기본 사용
    - Redis에서 `dailyreport-YYYYMMDD` 키로 리포트 조회
    """
    date_str = request.args.get('date')
    if not date_str:
        date_str = datetime.datetime.utcnow().strftime('%Y-%m-%d')

    # Redis에 저장된 형식: 'dailyreport-YYYYMMDD'
    # date_str은 'YYYY-MM-DD' 형식이므로, '-'를 제거해야 키와 일치함
    key_date = date_str.replace('-', '')        # e.g. '20250601'
    redis_key = f"dailyreport-{key_date}"       # e.g. 'dailyreport-20250601'

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
    - 없으면 오늘(UTC) 날짜 기본 사용
    - Redis에서 `weeklyreport-YYYYMMDD` 키로 리포트 조회
    """
    date_str = request.args.get('date')
    if not date_str:
        date_str = datetime.datetime.utcnow().strftime('%Y-%m-%d')

    key_date = date_str.replace('-', '')        # e.g. '20250601'
    redis_key = f"weeklyreport-{key_date}"      # e.g. 'weeklyreport-20250601'

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
    - 없으면 오늘(UTC) 날짜 기본 사용
    - Redis에서 `monthlyreport-YYYYMMDD` 키로 리포트 조회
    """
    date_str = request.args.get('date')
    if not date_str:
        date_str = datetime.datetime.utcnow().strftime('%Y-%m-%d')

    key_date = date_str.replace('-', '')        # e.g. '20250601'
    redis_key = f"monthlyreport-{key_date}"     # e.g. 'monthlyreport-20250601'

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
