from flask import Flask, render_template, request, jsonify
import json
from datetime import datetime, timedelta, timezone
import logging
from dateutil import parser
import os
from collections import Counter
# NLTK 관련 import (top_keywords 생성에 사용)
import nltk
from nltk.tokenize import word_tokenize
from nltk.corpus import stopwords
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

# NLTK 리소스 다운로드 (최초 실행 시 또는 필요 시)
# 실제 배포 환경에서는 Dockerfile이나 시작 스크립트에서 처리하는 것이 좋습니다.
try:
    nltk.data.find('corpora/stopwords')
    nltk.data.find('tokenizers/punkt')
except Exception as e:
    logger.info("NLTK stopwords or punkt not found. Downloading...")
    nltk.download('stopwords', quiet=True)
    nltk.download('punkt', quiet=True)


def parse_published_date(date_string):
    """
    주어진 날짜 문자열을 offset-aware UTC datetime 객체로 파싱합니다.
    예상 형식: "fri, 30 may 2025 05:00:45 gmt"
    """
    if not date_string:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        # 시도 1: dateutil.parser.parse 사용 (일반적으로 유연함)
        dt = parser.parse(date_string)
    except (ValueError, TypeError) as e:
        logger.warning(f"dateutil.parser.parse failed for '{date_string}': {e}. Trying strptime.")
        try:
            # 시도 2: strptime으로 명시적 파싱
            # "fri, 30 may 2025 05:00:45 gmt" 형식에 맞춤
            # 'gmt' 부분은 대소문자 구분 없이 제거하고 UTC로 가정
            dt_naive_str = date_string.lower().rsplit(' gmt', 1)[0] if ' gmt' in date_string.lower() else date_string.lower().rsplit(' utc', 1)[0] if ' utc' in date_string.lower() else date_string.lower()
            dt_naive = datetime.strptime(dt_naive_str, "%a, %d %b %Y %H:%M:%S")
            dt = dt_naive.replace(tzinfo=timezone.utc) # GMT/UTC로 간주
        except ValueError as ve:
            logger.error(f"strptime failed for '{date_string}' after parser.parse also failed: {ve}")
            return datetime.min.replace(tzinfo=timezone.utc)

    # 시간대 정보 통일 (UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt

def load_news_data():
    """JSON 파일에서 뉴스 데이터 로드 (현재 사용되지 않음, Redis 우선)"""
    try:
        with open('data/news.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning("News data file not found (data/news.json)")
        return {'news': []}
    except json.JSONDecodeError:
        logger.error("Error decoding news data file (data/news.json)")
        return {'news': []}

def categorize_news(news_item):
    """뉴스 항목을 카테고리로 분류"""
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
    """Redis에서 뉴스 데이터를 로드하고 날짜로 정렬합니다."""
    news_pattern = re.compile(r'^news-(\d{8})-(\d{3})$')
    keys = [key for key in redis_client.scan_iter('news-*') if news_pattern.match(key)]
    
    if not keys:
        logger.info("No news keys found in Redis.")
        return []

    pipe = redis_client.pipeline()
    for key in keys:
        pipe.get(key)
    values = pipe.execute()
    
    news_list = []
    for key, value in zip(keys, values):
        if value:
            try:
                news_item_wrapper = json.loads(value)
                # 실제 뉴스 데이터는 'value' 키 내부에 있음
                news_data = news_item_wrapper.get('value', {})
                if not news_data: # 'value' 필드가 없거나 비어있는 경우
                    logger.warning(f"News data in 'value' field is empty for key {key}.")
                    continue
                news_data['redis_key'] = key # 원본 Redis 키 추가
                news_list.append(news_data)
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON in Redis for key {key}: {value[:100]}...") # 값의 일부를 로깅
            except Exception as e:
                logger.error(f"Unexpected error processing data from Redis key {key}: {e}", exc_info=True)
    
    # 날짜로 정렬 (파싱된 datetime 객체 사용)
    news_list.sort(key=lambda item: parse_published_date(item.get('published', '')), reverse=True)
    return news_list

@app.route('/')
def index():
    news_items = fetch_news_from_redis()
    categorized_news_dict = {category_id: [] for category_id in CATEGORIES.keys()}
    
    all_sources = set()
    for news in news_items:
        category = categorize_news(news) # title, summary 기반 분류
        # 만약 news 객체에 이미 'category' 필드가 있다면 그것을 우선 사용할 수도 있음.
        # 예: category_id_from_data = news.get('category')
        # if category_id_from_data and category_id_from_data in CATEGORIES:
        #    category = category_id_from_data
        # else:
        #    category = categorize_news(news)
        categorized_news_dict[category].append(news)
        all_sources.add(news.get('source', 'Unknown'))

    return render_template('index.html',
                         categorized_news=categorized_news_dict,
                         categories=CATEGORIES,
                         sources=sorted(list(all_sources)), # 정렬된 소스 목록
                         current_category='',
                         current_source='',
                         current_sort='newest')

@app.route('/api/trends')
def get_trends():
    period = request.args.get('period', 'weekly')
    if period not in ['weekly', 'monthly']:
        return jsonify({'error': 'Invalid period'}), 400
    
    try:
        news_items = fetch_news_from_redis()
        if not news_items:
            logger.info("No news items fetched from Redis for trends.")
            # 빈 데이터라도 정상적인 구조로 반환
            return jsonify({
                'top_keywords': [], 'source_distribution': [], 'category_distribution': [],
                'country_distribution': [], 'sample_news': []
            })

        now = datetime.now(timezone.utc)
        if period == 'weekly':
            cutoff_date = now - timedelta(days=7)
        else:  # monthly
            cutoff_date = now - timedelta(days=30)

        recent_news = []
        for item in news_items:
            published_date = parse_published_date(item.get('published', ''))
            if published_date >= cutoff_date:
                recent_news.append(item)
        
        if not recent_news:
            logger.info(f"No recent news found for the {period} period.")
             # 빈 데이터라도 정상적인 구조로 반환
            return jsonify({
                'top_keywords': [], 'source_distribution': [], 'category_distribution': [],
                'country_distribution': [], 'sample_news': []
            })


        # 카테고리 분포 계산
        category_counts = Counter()
        for news_item in recent_news:
            category_id_from_data = news_item.get('category') # Redis에 저장된 카테고리 ID
            final_category_id = ''
            if category_id_from_data and category_id_from_data in CATEGORIES:
                final_category_id = category_id_from_data
            else:
                final_category_id = categorize_news(news_item) # title/summary 기반 재분류
            category_counts[CATEGORIES[final_category_id]['name']] += 1
        category_distribution = [{'category': name, 'count': count} for name, count in category_counts.most_common()]

        # 출처 분포 계산
        source_counts = Counter(item.get('source', 'Unknown') for item in recent_news)
        source_distribution = [{'source': name, 'count': count} for name, count in source_counts.most_common() if name != 'Unknown']
        
        # 키워드 빈도 계산 (간단 버전)
        stop_words_set = set(stopwords.words('english'))
        all_words_list = []
        for news_item in recent_news:
            text_content = (news_item.get('title', '') + " " + news_item.get('summary', '')).lower()
            words = word_tokenize(text_content)
            for word in words:
                if word.isalpha() and word not in stop_words_set and len(word) > 2:
                    all_words_list.append(word)
        keyword_counts = Counter(all_words_list)
        top_keywords = [{'keyword': kw, 'count': cnt} for kw, cnt in keyword_counts.most_common(10)] # 상위 10개

        # 국가 분포 (더미 데이터 - 실제 구현 필요)
        # 이 부분은 뉴스 내용에서 국가명을 추출하는 로직(예: NER 또는 키워드 매칭)이 필요합니다.
        country_distribution = [{'country': 'ExampleCountry', 'count': len(recent_news)}] 
        logger.warning("Country distribution is using dummy data. Actual implementation needed.")

        sample_news = recent_news # 이미 필터링된 최신 뉴스

        return jsonify({
            'top_keywords': top_keywords,
            'source_distribution': source_distribution,
            'category_distribution': category_distribution,
            'country_distribution': country_distribution,
            'sample_news': sample_news
        })
    except Exception as e:
        logger.error(f"Error generating trends data: {str(e)}", exc_info=True)
        return jsonify({'error': 'Failed to generate trends data'}), 500

@app.route('/trends')
def trends_page():
    return render_template('trends.html')

if __name__ == '__main__':
    # 개발 환경에서는 debug=True 사용, 프로덕션에서는 False 또는 Gunicorn 등 사용
    app.run(debug=True)
