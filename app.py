from flask import Flask, render_template, request, jsonify
import json
from datetime import datetime, timedelta, timezone
import logging
from dateutil import parser
import os
from collections import Counter
from nltk.tokenize import word_tokenize
from nltk.corpus import stopwords
import nltk
import redis
import re

app = Flask(__name__)

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 카테고리 키워드 정의
CATEGORIES = {
    'climate_change': {
        'name': 'Climate Change',
        'keywords': ['climate change', 'global warming', 'greenhouse gas', 'carbon emission', 'temperature rise']
    },
    'biodiversity': {
        'name': 'Biodiversity',
        'keywords': ['biodiversity', 'endangered species', 'wildlife', 'ecosystem', 'habitat']
    },
    'renewable_energy': {
        'name': 'Renewable Energy',
        'keywords': ['renewable energy', 'solar power', 'wind power', 'clean energy', 'green energy']
    },
    'sustainability': {
        'name': 'Sustainability',
        'keywords': ['sustainability', 'sustainable', 'circular economy', 'green economy', 'esg']
    },
    'pollution': {
        'name': 'Pollution',
        'keywords': ['pollution', 'air quality', 'water pollution', 'plastic waste', 'chemical']
    },
    'environmental_policy': {
        'name': 'Environmental Policy',
        'keywords': ['environmental policy', 'climate policy', 'environmental regulation', 'environmental law', 'environmental tax', 'subsidy', 'international agreement', 'climate agreement', 'environmental standard']
    },
    'environmental_tech': {
        'name': 'Environmental Technology',
        'keywords': ['environmental technology', 'green tech', 'carbon capture', 'environmental monitoring', 'waste treatment', 'smart environment', 'clean tech', 'environmental innovation', 'sustainable technology']
    },
    'others': {
        'name': 'Others',
        'keywords': []
    }
}

# Redis 연결 설정 (환경변수 또는 기본값 사용)
REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)

def load_news_data():
    """JSON 파일에서 뉴스 데이터 로드"""
    try:
        with open('data/news.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning("News data file not found")
        return {'news': []}
    except json.JSONDecodeError:
        logger.error("Error decoding news data file")
        return {'news': []}

def categorize_news(news_item):
    """뉴스 항목을 카테고리로 분류"""
    # Use get method to provide default empty string if key is missing
    title_lower = news_item.get('title', '').lower()
    summary_lower = news_item.get('summary', '').lower()
    
    for category_id, category in CATEGORIES.items():
        if category_id == 'others':
            continue
            
        for keyword in category['keywords']:
            if keyword in title_lower or keyword in summary_lower:
                return category_id
    
    return 'others'

def fetch_news_from_redis():
    news_pattern = re.compile(r'^news-(\d{8})-(\d{3})$')
    keys = [key for key in redis_client.scan_iter('news-*') if news_pattern.match(key)]
    
    # Pipeline으로 여러 GET 요청을 한 번에 처리
    pipe = redis_client.pipeline()
    for key in keys:
        pipe.get(key)
    values = pipe.execute()
    
    news_list = []
    for key, value in zip(keys, values):
        if value:
            try:
                news_item = json.loads(value)
                # Access the nested 'value' object
                news_data = news_item.get('value', {})
                news_data['redis_key'] = key
                news_list.append(news_data)
            except Exception as e:
                logger.warning(f"Invalid JSON in Redis for key {key}: {e}")
    
    # 날짜 파싱에서 offset-aware 통일
    def parse_date(item):
        try:
            dt = parser.parse(item.get('published', ''))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            return dt
        except:
            return datetime.min.replace(tzinfo=timezone.utc)

    news_list.sort(key=parse_date, reverse=True)
    return news_list

@app.route('/')
def index():
    # Redis에서 뉴스 데이터 로드
    news_items = fetch_news_from_redis()

    # 카테고리 분류 (기존 로직 재사용)
    categorized_news = {category_id: [] for category_id in CATEGORIES.keys()}
    for news in news_items:
        category = categorize_news(news)
        categorized_news[category].append(news)

    return render_template('index.html',
                         categorized_news=categorized_news,
                         categories=CATEGORIES,
                         sources=set(item.get('source', 'Unknown') for item in news_items),
                         current_category='',
                         current_source='',
                         current_sort='newest')

@app.route('/api/trends')
def get_trends():
    """트렌드 리포트 API 엔드포인트 (이제는 해당 기간의 뉴스만 반환)"""
    period = request.args.get('period', 'weekly')
    if period not in ['weekly', 'monthly']:
        return jsonify({'error': 'Invalid period'}), 400
    try:
        # Redis에서 뉴스 데이터 로드
        news_items = fetch_news_from_redis()
        # 기간 설정
        now = datetime.now(timezone.utc)
        if period == 'weekly':
            cutoff = now - timedelta(days=7)
        else:  # monthly
            cutoff = now - timedelta(days=30)
        # 기간 내 뉴스 필터링
        recent_news = [
            item for item in news_items
            if parser.parse(item['published']) >= cutoff
        ]
        
        # 트렌드 데이터 생성
        top_keywords = [{'keyword': 'climate change', 'count': 5}, {'keyword': 'renewable energy', 'count': 3}]
        source_distribution = [{'source': 'The Guardian', 'count': 2}, {'source': 'BBC', 'count': 1}]
        category_distribution = [{'category': 'Climate Change', 'count': 2}, {'category': 'Renewable Energy', 'count': 1}]
        country_distribution = [{'country': 'Australia', 'count': 2}, {'country': 'United States', 'count': 1}]
        sample_news = recent_news
        
        return jsonify({
            'top_keywords': top_keywords,
            'source_distribution': source_distribution,
            'category_distribution': category_distribution,
            'country_distribution': country_distribution,
            'sample_news': sample_news
        })
    except Exception as e:
        logger.error(f"Error generating news list: {str(e)}")
        return jsonify({'error': 'Failed to generate news list'}), 500

@app.route('/trends')
def trends_page():
    return render_template('trends.html')

if __name__ == '__main__':
    app.run(debug=True) 
