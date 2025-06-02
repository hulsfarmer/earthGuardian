from flask import Flask, render_template, request, redirect, url_for
import datetime
import os
import redis
import pickle

app = Flask(__name__)

def get_redis_client():
    redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
    return redis.StrictRedis.from_url(redis_url, decode_responses=True)

def load_report_from_redis(period_key):
    """
    Redis에서 저장된 리포트를 읽어 옵니다.
    - pickle 직렬화된 경우: pickle.loads
    - JSON 형태일 경우: json.loads
    - 그 외 단순 텍스트라면 줄바꿈을 <br>로 변환하여 반환
    """
    client = get_redis_client()
    raw = client.get(f'flask_cache_periodic_report_{period_key}')
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

@app.route('/')
def index():
    # 기존 index() 뷰 로직을 여기에 둡니다.
    # (カテゴリ별 뉴스 로딩, 필터링 처리 등이 포함된 코드)
    # 예시로 아래와 같이 가정합니다:
    """
    news_items = fetch_news_from_redis()
    categorized_news = {cat_id: [] for cat_id in CATEGORIES.keys()}
    # ... (이하 뉴스 분류 코드) ...
    """
    return render_template(
        'index.html',
        categorized_news=categorized_news,
        categories=CATEGORIES,
        sources=sorted_sources,
        current_category=current_category,
        current_source=current_source,
        current_sort=current_sort
    )

@app.route('/reports')
def reports_index():
    """
    /reports 접근 시:
    - ?date=YYYY-MM-DD 쿼리스트링을 읽어 사용
    - 없으면 오늘(UTC) 날짜를 기본값으로 사용
    - 일간/주간/월간 리포트 URL을 생성하여 템플릿에 전달
    """
    date_str = request.args.get('date')
    if not date_str:
        date_str = datetime.datetime.utcnow().strftime('%Y-%m-%d')

    # 각 리포트 타입별 URL 생성
    daily_url   = url_for('daily_report',   date=date_str)
    weekly_url  = url_for('weekly_report',  date=date_str)
    monthly_url = url_for('monthly_report', date=date_str)

    return render_template(
        'reports_index.html',
        date_str=date_str,
        daily_url=daily_url,
        weekly_url=weekly_url,
        monthly_url=monthly_url
    )

@app.route('/reports/daily')
def daily_report():
    date_str = request.args.get('date')
    if not date_str:
        date_str = datetime.datetime.utcnow().strftime('%Y-%m-%d')
    period_key = f"daily-{date_str}"
    raw_report = load_report_from_redis(period_key)
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

@app.route('/reports/weekly')
def weekly_report():
    date_str = request.args.get('date')
    if not date_str:
        date_str = datetime.datetime.utcnow().strftime('%Y-%m-%d')
    period_key = f"weekly-{date_str}"
    raw_report = load_report_from_redis(period_key)
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

@app.route('/reports/monthly')
def monthly_report():
    date_str = request.args.get('date')
    if not date_str:
        date_str = datetime.datetime.utcnow().strftime('%Y-%m-%d')
    period_key = f"monthly-{date_str}"
    raw_report = load_report_from_redis(period_key)
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

if __name__ == '__main__':
    app.run(debug=True, port=5000)
