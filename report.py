# report.py

import os
import redis
import pickle
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


@reports_bp.route('/news', methods=['POST'])
def report_news():
    """
    특정 뉴스 아이템을 신고하고, 'reported' 목록으로 옮깁니다.
    성공적으로 신고되면 캐시를 즉시 업데이트하도록 스케줄링합니다.
    """
    if not redis_client:
        logger.error("REPORT_NEWS: Redis client not available.")
        return jsonify({"status": "error", "message": "Database connection failed"}), 500

    data = request.get_json()
    if not data or 'redis_key' not in data or 'reason' not in data:
        return jsonify({"status": "error", "message": "Invalid report data"}), 400

    redis_key = data['redis_key']
    reason = data['reason']

    try:
        news_item_json = redis_client.get(redis_key)
        if not news_item_json:
            return jsonify({"status": "error", "message": "News item not found"}), 404
            
        # 원본 키 삭제 및 신고 목록에 추가
        pipe = redis_client.pipeline()
        pipe.delete(redis_key)
        reported_key = f"reported:{redis_key}"
        pipe.hset(reported_key, mapping={
            "reported_at": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
            "news_item": news_item_json
        })
        pipe.execute()
        
        # 캐시 즉시 업데이트 스케줄링
        if scheduler.state == 1: # STATE_RUNNING
            from services import update_news_cache
            scheduler.add_job(
                update_news_cache, 
                id='immediate_cache_update_after_report',
                replace_existing=True,
                name="Immediate Cache Update after Report"
            )
            logger.info(f"REPORT_NEWS: Scheduled immediate cache update after reporting key: {redis_key}")

        return jsonify({"status": "success", "message": "News reported and removed"}), 200
            
    except Exception as e:
        logger.error(f"REPORT_NEWS: Error processing report for key {redis_key}: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "An internal server error occurred"}), 500


@reports_bp.route('/', methods=['GET'])
def list_reports():
    """
    신고된 뉴스 목록을 보여주는 관리자용 페이지를 렌더링합니다.
    """
    if not redis_client:
        return "Error: Redis connection not available.", 500
        
    reported_keys = redis_client.keys('reported:news-*')
    reports = []
    if reported_keys:
        for key in reported_keys:
            report_data = redis_client.hgetall(key)
            reports.append({
                'key': key,
                'reported_at': report_data.get('reported_at', 'N/A'),
                'reason': report_data.get('reason', 'N/A')
            })
    return render_template('reports/list.html', reports=reports)
