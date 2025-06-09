from flask import Blueprint, render_template, current_app
import logging

from services import get_cached_homepage_data, CATEGORIES

main_bp = Blueprint('main', __name__)
logger = logging.getLogger(__name__)

@main_bp.route('/')
def index():
    """
    메인 페이지를 렌더링합니다. 캐시된 데이터를 우선적으로 사용합니다.
    """
    try:
        # 캐시에서 홈페이지 데이터 가져오기
        cached_data = get_cached_homepage_data()
        
        if cached_data:
            logger.info("Serving homepage from cache.")
            categorized_news = cached_data['categorized_news']
            sorted_sources = cached_data['sorted_sources']
        else:
            logger.warning("Homepage cache is empty. Falling back to empty data.")
            # 캐시가 없는 경우 비상 로직 (또는 실시간 데이터 로드)
            # 여기서는 빈 데이터로 표시하여 서비스 중단을 방지합니다.
            categorized_news = {cat_id: [] for cat_id in CATEGORIES.keys()}
            sorted_sources = []

        # 카테고리 이름 매핑
        category_names = {cat_id: info['name'] for cat_id, info in CATEGORIES.items()}
        
        return render_template('index.html',
                               categorized_news=categorized_news,
                               categories=category_names,
                               sorted_sources=sorted_sources)
    except Exception as e:
        logger.error(f"Error rendering main page: {e}", exc_info=True)
        # 프로덕션에서는 더 사용자 친화적인 에러 페이지를 보여줘야 합니다.
        return "An error occurred while loading the page.", 500 