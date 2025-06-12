from flask import Blueprint, render_template
from services import get_cached_reports_data, get_cached_homepage_data

home_bp = Blueprint('home', __name__)

@home_bp.route('/')
def home():
    # Get latest reports
    (
        all_daily_dates, all_weekly_dates, all_monthly_dates,
        latest_daily_report, latest_weekly_report, latest_monthly_report
    ) = get_cached_reports_data()

    latest_daily_date = all_daily_dates[0] if all_daily_dates else None
    latest_daily_report_content = latest_daily_report if latest_daily_report else None
    latest_weekly_date = all_weekly_dates[0] if all_weekly_dates else None
    latest_weekly_report_content = latest_weekly_report if latest_weekly_report else None

    # Get latest news (for featured reports)
    homepage_data = get_cached_homepage_data()
    latest_news = []
    if homepage_data:
        all_news = []
        for news_list in homepage_data['categorized_news'].values():
            all_news.extend(news_list)
        all_news.sort(key=lambda n: n.get('published', ''), reverse=True)
        latest_news = all_news[:5]

    return render_template(
        'home.html',
        latest_daily_date=latest_daily_date,
        latest_daily_report=latest_daily_report_content,
        latest_weekly_date=latest_weekly_date,
        latest_weekly_report=latest_weekly_report_content,
        latest_news=latest_news
    ) 