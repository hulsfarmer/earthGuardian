from flask import Blueprint, render_template, request
import logging
import json

from services import get_cached_homepage_data, CATEGORIES

main_bp = Blueprint('main', __name__)
logger = logging.getLogger(__name__)

@main_bp.route('/')
def index():
    """
    메인 페이지를 렌더링합니다. 캐시된 데이터를 사용하고, 요청된 필터링/정렬을 적용합니다.
    """
    try:
        current_category = request.args.get('category', '')
        current_source = request.args.get('source', '')
        current_sort = request.args.get('sort', 'newest')

        cached_data = get_cached_homepage_data()
        
        if cached_data:
            logger.info("Serving homepage from cache.")
            categorized_news = cached_data['categorized_news']
            sorted_sources = cached_data['sorted_sources']
            
            # 필터링 로직 (카테고리)
            if current_category and current_category in categorized_news:
                 categorized_news = {current_category: categorized_news[current_category]}

            # 필터링 로직 (소스)
            if current_source:
                filtered_by_source = {}
                for cat_id, news_list in categorized_news.items():
                    filtered_list = [news for news in news_list if news.get('source') == current_source]
                    if filtered_list:
                        filtered_by_source[cat_id] = filtered_list
                categorized_news = filtered_by_source
            
            # 정렬 로직
            if current_sort == 'oldest':
                for cat_id in categorized_news:
                    categorized_news[cat_id].reverse() # 이미 최신순이므로 reverse()만 하면 됨

        else:
            logger.warning("Homepage cache is empty. Falling back to empty data.")
            categorized_news = {cat_id: [] for cat_id in CATEGORIES.keys()}
            sorted_sources = []

        category_names = {cat_id: info['name'] for cat_id, info in CATEGORIES.items()}
        
        return render_template('index.html',
                               categorized_news=categorized_news,
                               categories=category_names,
                               sorted_sources=sorted_sources,
                               current_category=current_category,
                               current_source=current_source,
                               current_sort=current_sort)
    except Exception as e:
        logger.error(f"Error rendering main page: {e}", exc_info=True)
        # 프로덕션에서는 더 사용자 친화적인 에러 페이지를 보여줘야 합니다.
        return "An error occurred while loading the page.", 500 