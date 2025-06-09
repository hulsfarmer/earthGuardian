# views/trends.py
from flask import Blueprint, render_template, jsonify, request
import logging

from services import get_cached_trends_data

trends_bp = Blueprint('trends', __name__)
logger = logging.getLogger(__name__)

@trends_bp.route('/trends')
def trends_page():
    """
    트렌드 분석 페이지를 렌더링합니다.
    """
    return render_template('trends.html')

@trends_bp.route('/api/trends')
def get_trends():
    """
    캐시된 트렌드 데이터를 API 형태로 제공합니다.
    주간(weekly) 또는 월간(monthly) 데이터를 선택할 수 있습니다.
    """
    period = request.args.get('period', 'weekly')
    if period not in ['weekly', 'monthly']:
        return jsonify({"error": "Invalid period specified. Use 'weekly' or 'monthly'."}), 400
        
    try:
        trends_data = get_cached_trends_data(period)
        if trends_data:
            logger.info(f"Serving {period} trends from cache.")
            return jsonify(trends_data)
        else:
            logger.warning(f"No cached data available for {period} trends.")
            # 캐시가 없는 경우, 클라이언트가 재시도할 수 있도록 빈 데이터를 반환합니다.
            return jsonify({
                "top_keywords": [],
                "source_distribution": [],
                "category_distribution": [],
                "country_distribution": [],
                "sample_news": []
            })
    except Exception as e:
        logger.error(f"Error fetching {period} trends data: {e}", exc_info=True)
        return jsonify({"error": "An internal error occurred while fetching trends data."}), 500 