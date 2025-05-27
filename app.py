from flask import Flask, render_template, request, jsonify
import json
from datetime import datetime, timedelta
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
    title_lower = news_item['title'].lower()
    summary_lower = news_item['summary'].lower()
    
    for category_id, category in CATEGORIES.items():
        if category_id == 'others':
            continue
            
        for keyword in category['keywords']:
            if keyword in title_lower or keyword in summary_lower:
                return category_id
    
    return 'others'

def fetch_news_from_redis():
    """Redis에서 news-YYYYMMDD-XXX 패턴의 키로 저장된 뉴스들을 모두 가져와 리스트로 반환"""
    news_pattern = re.compile(r'news-(\d{8})-(\d{3})')
    news_list = []
    for key in redis_client.scan_iter('news-*'):
        if news_pattern.match(key):
            value = redis_client.get(key)
            if value:
                try:
                    news_item = json.loads(value)
                    news_item['redis_key'] = key
                    news_list.append(news_item)
                except Exception as e:
                    logger.warning(f"Invalid JSON in Redis for key {key}: {e}")
    # published 기준 내림차순 정렬 (날짜 파싱 실패시 최근순)
    def parse_date(item):
        try:
            return parser.parse(item.get('published', ''))
        except:
            return datetime.min
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
                         sources=set(item['source'] for item in news_items),
                         current_category='',
                         current_source='',
                         current_sort='newest')

@app.route('/api/trends')
def get_trends():
    """트렌드 리포트 API 엔드포인트"""
    period = request.args.get('period', 'weekly')
    if period not in ['weekly', 'monthly']:
        return jsonify({'error': 'Invalid period'}), 400
    
    try:
        # Redis에서 뉴스 데이터 로드
        news_items = fetch_news_from_redis()
        
        # 기간 설정
        now = datetime.now()
        if period == 'weekly':
            start_date = now - timedelta(days=7)
        else:  # monthly
            start_date = now - timedelta(days=30)
        
        # 기간 내 뉴스 필터링
        recent_news = [
            item for item in news_items
            if parser.parse(item['published']) >= start_date
        ]
        
        if not recent_news:
            return jsonify({
                'period': period,
                'generated_at': now.strftime('%Y-%m-%d %H:%M:%S'),
                'total_news': 0,
                'top_keywords': [],
                'source_distribution': [],
                'category_distribution': [],
                'country_distribution': [],
                'sample_news': []
            })
        
        # 키워드 추출 및 분석
        all_text = ' '.join([item['title'] + ' ' + item['summary'] for item in recent_news])
        words = word_tokenize(all_text.lower())
        stop_words = set(stopwords.words('english'))
        words = [word for word in words if word.isalnum() and word not in stop_words and len(word) > 2]
        
        # 키워드 빈도 분석
        keyword_freq = Counter(words).most_common(20)
        
        # 출처별 뉴스 수
        source_stats = Counter(item['source'] for item in recent_news)
        
        # 카테고리별 뉴스 수
        category_stats = Counter(categorize_news(item) for item in recent_news)
        
        # 국가 분석
        country_keywords = {
            'united states': ['united states', 'us', 'usa', 'america', 'american'],
            'china': ['china', 'chinese'],
            'india': ['india', 'indian'],
            'european union': ['eu', 'european union', 'europe'],
            'united kingdom': ['uk', 'united kingdom', 'britain', 'british'],
            'japan': ['japan', 'japanese'],
            'south korea': ['south korea', 'korean', 'korea'],
            'australia': ['australia', 'australian'],
            'brazil': ['brazil', 'brazilian'],
            'russia': ['russia', 'russian'],
            'canada': ['canada', 'canadian'],
            'germany': ['germany', 'german'],
            'france': ['france', 'french'],
            'italy': ['italy', 'italian'],
            'spain': ['spain', 'spanish']
        }
        
        # 국가별 뉴스 개수 집계
        country_mentions = Counter()
        for item in recent_news:
            text = (item['title'] + ' ' + item['summary']).lower()
            for country, keywords in country_keywords.items():
                if any(keyword in text for keyword in keywords):
                    country_mentions[country] += 1
        
        # 상위 10개 국가만 선택
        country_stats = country_mentions.most_common(10)
        
        # 트렌드 리포트 생성
        report = {
            'period': period,
            'generated_at': now.strftime('%Y-%m-%d %H:%M:%S'),
            'total_news': len(recent_news),
            'top_keywords': [{'keyword': k, 'count': v} for k, v in keyword_freq],
            'source_distribution': [{'source': k, 'count': v} for k, v in source_stats.items()],
            'category_distribution': [{'category': k, 'count': v} for k, v in category_stats.items()],
            'country_distribution': [{'country': k, 'count': v} for k, v in country_stats],
            'sample_news': [
                {
                    'title': item['title'],
                    'summary': item['summary'],
                    'link': item['link'],
                    'source': item['source'],
                    'published': item['published'],
                    'category': categorize_news(item)
                }
                for item in recent_news[:100]  # 최근 100개 뉴스 샘플
            ]
        }
        
        return jsonify(report)
        
    except Exception as e:
        logger.error(f"Error generating trends report: {str(e)}")
        return jsonify({'error': 'Failed to generate report'}), 500

@app.route('/trends')
def trends_page():
    return render_template('trends.html')

if __name__ == '__main__':
    app.run(debug=True) 
