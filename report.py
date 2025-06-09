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


def list_report_dates(prefix, page=1, per_page=20):
    """
    Redis에 저장된 키 중 prefix로 시작하는 것들을 스캔하여, 날짜 문자열 목록을 반환합니다.
    페이지네이션을 지원합니다.
    """
    client = get_redis_client()
    pattern = f"{prefix}*"
    # 주의: SCAN은 전체 키를 순회하므로, 키가 매우 많을 경우 성능이 저하될 수 있습니다.
    # 이상적으로는 이 목록을 별도의 리스트나 정렬된 세트로 관리해야 합니다.
    # 여기서는 기존 구조를 유지한 채 페이지네이션을 구현합니다.
    all_keys = sorted(client.keys(pattern), reverse=True)
    
    start = (page - 1) * per_page
    end = start + per_page
    paginated_keys = all_keys[start:end]

    dates = []
    for k in paginated_keys:
        date_part = k[len(prefix):]
        if len(date_part) == 8 and date_part.isdigit():
            formatted = f"{date_part[0:4]}-{date_part[4:6]}-{date_part[6:8]}"
            dates.append(formatted)

    total_items = len(all_keys)
    total_pages = (total_items + per_page - 1) // per_page
    
    return dates, total_pages


@reports_bp.route('/')
def reports_index():
    """
    /reports 경로
    페이지네이션을 사용하여 리포트 목록을 표시합니다.
    """
    daily_page = request.args.get('daily_page', 1, type=int)
    weekly_page = request.args.get('weekly_page', 1, type=int)
    monthly_page = request.args.get('monthly_page', 1, type=int)
    
    daily_dates, daily_total_pages = list_report_dates("dailyreport-", page=daily_page, per_page=20)
    weekly_dates, weekly_total_pages = list_report_dates("weeklyreport-", page=weekly_page, per_page=20)
    monthly_dates, monthly_total_pages = list_report_dates("monthlyreport-", page=monthly_page, per_page=20)

    # 각 섹션별 가장 최근 리포트 콘텐츠 미리 로드
    daily_latest_dates, _ = list_report_dates("dailyreport-", page=1, per_page=1)
    weekly_latest_dates, _ = list_report_dates("weeklyreport-", page=1, per_page=1)
    monthly_latest_dates, _ = list_report_dates("monthlyreport-", page=1, per_page=1)
    
    daily_latest_report = None
    if daily_latest_dates:
        key_date = daily_latest_dates[0].replace('-', '')
        daily_latest_report = load_report_from_redis(f"dailyreport-{key_date}")

    weekly_latest_report = None
    if weekly_latest_dates:
        key_date = weekly_latest_dates[0].replace('-', '')
        weekly_latest_report = load_report_from_redis(f"weeklyreport-{key_date}")

    monthly_latest_report = None
    if monthly_latest_dates:
        key_date = monthly_latest_dates[0].replace('-', '')
        monthly_latest_report = load_report_from_redis(f"monthlyreport-{key_date}")
    
    return render_template(
        'reports.html',
        daily_dates=daily_dates,
        daily_page=daily_page,
        daily_total_pages=daily_total_pages,
        weekly_dates=weekly_dates,
        weekly_page=weekly_page,
        weekly_total_pages=weekly_total_pages,
        monthly_dates=monthly_dates,
        monthly_page=monthly_page,
        monthly_total_pages=monthly_total_pages,
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
