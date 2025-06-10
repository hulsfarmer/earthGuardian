# report.py

import os
import redis
import pickle
import re # 정규표현식 모듈 추가
import datetime
from flask import Blueprint, render_template, request, jsonify
import logging
from datetime import timezone

# 공용 redis_client와 scheduler를 import합니다.
from extensions import redis_client, scheduler
from services import get_cached_reports_data

reports_bp = Blueprint('reports', __name__, url_prefix='/reports')
logger = logging.getLogger(__name__)


def get_redis_client():
    redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
    return redis.StrictRedis.from_url(redis_url, decode_responses=True)


def linkify(text):
    """
    텍스트 내의 URL을 찾아서 <a> 태그로 변환하고, 줄바꿈을 <br>로 변경합니다.
    """
    # URL을 찾기 위한 정규표현식
    # http/https뿐만 아니라 www. 로 시작하는 주소도 링크로 변환합니다.
    url_pattern = re.compile(r'((?:https?://|www\.)[^\s<]+)')
    
    def add_protocol(match):
        url = match.group(1)
        if url.startswith('www.'):
            return f'http://{url}'
        return url

    # URL에 <a> 태그 추가, target="_blank"로 새 창에서 열기
    # URL이 아닌 텍스트는 그대로 유지됩니다.
    linked_text = url_pattern.sub(lambda m: f'<a href="{add_protocol(m)}" target="_blank" class="text-blue-500 hover:text-blue-700">{m.group(1)}</a>', text)
    
    # 마지막으로 줄바꿈 처리
    return linked_text.replace('\n', '<br>')


def load_report_from_redis(key_name):
    """
    Redis에서 저장된 리포트를 읽어 옵니다.
    - pickle 직렬화된 경우: pickle.loads 후 linkify 처리
    - JSON 형태일 경우: json.loads 후 linkify 처리
    - 그 외 단순 텍스트라면 linkify 처리
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
        data = pickle.loads(raw)
        # pickle로 로드된 데이터가 문자열인 경우에만 linkify 적용
        return linkify(data) if isinstance(data, str) else data
    except Exception:
        pass

    # 2) JSON 시도
    try:
        import json
        data = json.loads(text)
        # JSON으로 로드된 데이터가 문자열인 경우에만 linkify 적용
        return linkify(data) if isinstance(data, str) else data
    except Exception:
        pass

    # 3) 단순 텍스트: linkify를 사용하여 URL 변환 및 줄바꿈 처리
    return linkify(text)


@reports_bp.route('/')
def reports_index():
    """
    /reports 경로
    캐시된 데이터를 사용하여 리포트 목록을 표시하고, 페이지네이션을 적용합니다.
    """
    daily_page = request.args.get('daily_page', 1, type=int)
    weekly_page = request.args.get('weekly_page', 1, type=int)
    monthly_page = request.args.get('monthly_page', 1, type=int)
    per_page = 20

    # 캐시에서 모든 데이터를 한 번에 가져옵니다.
    (
        all_daily_dates, all_weekly_dates, all_monthly_dates,
        latest_daily_report, latest_weekly_report, latest_monthly_report
    ) = get_cached_reports_data()
    
    if all_daily_dates is None: all_daily_dates = []
    if all_weekly_dates is None: all_weekly_dates = []
    if all_monthly_dates is None: all_monthly_dates = []

    # 페이지네이션 처리
    daily_start = (daily_page - 1) * per_page
    daily_end = daily_start + per_page
    daily_dates_paginated = all_daily_dates[daily_start:daily_end]
    daily_total_pages = (len(all_daily_dates) + per_page - 1) // per_page

    weekly_start = (weekly_page - 1) * per_page
    weekly_end = weekly_start + per_page
    weekly_dates_paginated = all_weekly_dates[weekly_start:weekly_end]
    weekly_total_pages = (len(all_weekly_dates) + per_page - 1) // per_page

    monthly_start = (monthly_page - 1) * per_page
    monthly_end = monthly_start + per_page
    monthly_dates_paginated = all_monthly_dates[monthly_start:monthly_end]
    monthly_total_pages = (len(all_monthly_dates) + per_page - 1) // per_page
    
    return render_template(
        'reports.html',
        daily_dates=daily_dates_paginated,
        daily_page=daily_page,
        daily_total_pages=daily_total_pages,
        weekly_dates=weekly_dates_paginated,
        weekly_page=weekly_page,
        weekly_total_pages=weekly_total_pages,
        monthly_dates=monthly_dates_paginated,
        monthly_page=monthly_page,
        monthly_total_pages=monthly_total_pages,
        daily_latest_report=latest_daily_report,
        weekly_latest_report=latest_weekly_report,
        monthly_latest_report=latest_monthly_report
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
