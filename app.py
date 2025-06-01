# app.py
from flask import Flask, render_template, request, jsonify
import json
from datetime import datetime, timedelta, timezone
import logging
from dateutil import parser
import os
from collections import Counter
from nltk.tokenize import word_tokenize
from nltk.corpus import stopwords # 주석 해제하여 사용
import nltk
import redis
import re

app = Flask(__name__)

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# NLTK 다운로드 (모든 환경에서 NLTK를 사용하기 전에 한 번 실행)
# try:
#     nltk.data.find('corpora/stopwords')
# except nltk.downloader.DownloadError:
#     nltk.download('stopwords')
# try:
#     nltk.data.find('tokenizers/punkt')
# except nltk.downloader.DownloadError:
#     nltk.download('punkt')

# 이 부분은 주석 처리된 상태로 유지하고, 실제로 NLTK를 사용하는 부분에 적용
# NLTK 관련 오류 처리를 더 견고하게 하려면, 앱 시작 시점에 다운로드 로직을 포함하는 것이 좋습니다.
# 또는 Dockerfile 등 배포 환경에서 미리 다운로드합니다.
try:
    nltk.data.find('corpora/stopwords')
    nltk.data.find('tokenizers/punkt')
except Exception as e: # 이전의 AttributeError 해결을 위해 일반 Exception으로 변경
    logger.warning(f"NLTK resources not found, attempting download: {e}")
    try:
        nltk.download('stopwords')
        nltk.download('punkt')
        logger.info("NLTK stopwords and punkt downloaded successfully.")
    except Exception as download_e:
        logger.error(f"Failed to download NLTK resources: {download_e}")
        # 다운로드 실패 시에도 앱이 실행되도록 하되, 관련 기능은 제한될 수 있음을 명시


# 카테고리 키워드 정의 (기존과 동일)
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

# 불용어 설정
stop_words = set(stopwords.words('english'))

def load_news_data():
    """JSON 파일에서 뉴스 데이터 로드 (현재 Redis 사용 중이므로 이 함수는 사용되지 않음)"""
    # ... (기존과 동일)

def categorize_news(news_item):
    """뉴스 항목을 카테고리로 분류"""
    title_lower = news_item.get('title', '').lower()
    summary_lower = news_item.get('summary', '').lower()
    
    for category_id, category in CATEGORIES.items():
        if category_id == 'others':
            continue
            
        for keyword in category['keywords']:
            if keyword in title_lower or keyword in summary_lower:
                # 카테고리 ID 대신 실제 카테고리 이름 반환
                return category['name'] 
    
    return CATEGORIES['others']['name'] # 'Others' 카테고리 이름 반환

def fetch_news_from_redis():
    news_pattern = re.compile(r'^news-(\d{8})-(\d{3})$')
    keys = [key for key in redis_client.scan_iter('news-*') if news_pattern.match(key)]
    
    pipe = redis_client.pipeline()
    for key in keys:
        pipe.get(key)
    values = pipe.execute()
    
    news_list = []
    for key, value in zip(keys, values):
        if value:
            try:
                news_item = json.loads(value)
                news_data = news_item.get('value', {})
                news_data['redis_key'] = key
                
                # 뉴스 로드 시 카테고리 정보 추가
                news_data['category'] = categorize_news(news_data) 
                news_list.append(news_data)
            except Exception as e:
                logger.warning(f"Invalid JSON in Redis for key {key}: {e}")
    
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
    news_items = fetch_news_from_redis()

    categorized_news = {category_id: [] for category_id in CATEGORIES.keys()}
    # 이 부분은 이제 news_items에 이미 카테고리 정보가 포함되어 있으므로 재분류
    for news in news_items:
        # CATEGORIES 딕셔너리의 키를 이용하여 카테고리 뉴스 분류
        for category_id, category_info in CATEGORIES.items():
            if news.get('category') == category_info['name']:
                categorized_news[category_id].append(news)
                break # 해당 뉴스는 하나의 카테고리에만 속하도록

    return render_template('index.html',
                         categorized_news=categorized_news,
                         categories=CATEGORIES,
                         sources=set(item.get('source', 'Unknown') for item in news_items),
                         current_category='',
                         current_source='',
                         current_sort='newest')


@app.route('/api/trends')
def get_trends():
    period = request.args.get('period', 'weekly')
    if period not in ['weekly', 'monthly']:
        return jsonify({'error': 'Invalid period'}), 400
    try:
        news_items = fetch_news_from_redis() # Redis에서 뉴스 가져오기
        
        now = datetime.now(timezone.utc)
        if period == 'weekly':
            cutoff = now - timedelta(days=7)
        else:  # monthly
            cutoff = now - timedelta(days=30)
        
        # 기간 내 뉴스 필터링 (published 시간을 정확히 파싱하여 비교)
        recent_news = []
        for item in news_items:
            try:
                # published 필드가 존재하고 유효한 날짜 형식인지 확인
                if 'published' in item and item['published']:
                    published_dt = parser.parse(item['published'])
                    # 시간대가 없는 경우 UTC로 간주
                    if published_dt.tzinfo is None:
                        published_dt = published_dt.replace(tzinfo=timezone.utc)
                    else:
                        published_dt = published_dt.astimezone(timezone.utc)
                    
                    if published_dt >= cutoff:
                        recent_news.append(item)
            except Exception as e:
                logger.warning(f"Error parsing date for news item {item.get('title', 'N/A')}: {e}")
                continue # 날짜 파싱 오류가 있는 뉴스는 건너뛰기
                
        # --- 실제 트렌드 데이터 계산 ---
        
        # 1. 키워드 빈도 계산
        all_words = []
        for news in recent_news:
            title_text = news.get('title', '')
            summary_text = news.get('summary', '')
            combined_text = title_text + ' ' + summary_text
            
            # 특수 문자 제거 및 소문자 변환
            cleaned_text = re.sub(r'[^a-zA-Z\s]', '', combined_text).lower()
            
            # 토큰화 및 불용어 제거
            words = word_tokenize(cleaned_text)
            filtered_words = [word for word in words if word.isalnum() and word not in stop_words and len(word) > 2]
            all_words.extend(filtered_words)
        
        # 키워드 필터링 (너무 일반적인 키워드 제외)
        common_exclude_keywords = set(['news', 'report', 'world', 'global', 'issue', 'new', 'says', 'company', 'government', 'country'])
        filtered_keywords = [word for word in all_words if word not in common_exclude_keywords]

        keyword_counts = Counter(filtered_keywords)
        top_keywords = [{'keyword': keyword, 'count': count} for keyword, count in keyword_counts.most_common(20)] # 상위 20개

        # 2. 출처 분포 계산
        source_counts = Counter(news.get('source', 'Unknown') for news in recent_news)
        source_distribution = [{'source': source, 'count': count} for source, count in source_counts.most_common()]

        # 3. 카테고리 분포 계산
        category_counts = Counter(news.get('category', CATEGORIES['others']['name']) for news in recent_news)
        category_distribution = [{'category': category, 'count': count} for category, count in category_counts.most_common()]

        # 4. 국가 분포 계산 (기존 로직 사용, 더 정교한 로직 필요 시 개선)
        country_mentions = Counter()
        country_keywords_map = {
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
        
        for news in recent_news:
            text = (news.get('title', '') + ' ' + news.get('summary', '')).lower()
            for country_name, keywords in country_keywords_map.items():
                if any(k in text for k in keywords):
                    country_mentions[country_name.title()] += 1 # 첫 글자를 대문자로
        
        country_distribution = [{'country': country, 'count': count} for country, count in country_mentions.most_common()]

        return jsonify({
            'top_keywords': top_keywords,
            'source_distribution': source_distribution,
            'category_distribution': category_distribution,
            'country_distribution': country_distribution,
            'sample_news': recent_news # 필터링된 최신 뉴스만 포함
        })

    except Exception as e:
        logger.error(f"Error generating trends: {str(e)}")
        return jsonify({'error': 'Failed to generate trends'}), 500

@app.route('/trends')
def trends_page():
    return render_template('trends.html')

if __name__ == '__main__':
    app.run(debug=True)
