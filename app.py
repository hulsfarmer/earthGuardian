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

# NLTK 다운로드 (모든 환경에서 NLTK를 사용하기 전에 한 번 실행)
# 배포 환경 (예: Dockerfile)에서는 미리 다운로드하거나,
# 애플리케이션 시작 시점에 한 번만 실행되도록 하는 것이 좋습니다.
# 여기서는 앱 시작 시도를 포함하지만, 이미 다운로드되어 있다면 건너뜁니다.
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


# 카테고리 키워드 정의
CATEGORIES = {
    'climate_change': {
        'name': 'Climate Change',
        'keywords': ['climate change', 'global warming', 'greenhouse gas', 'carbon emission', 'temperature rise', 'paris agreement', 'ipcc', 'cop28', 'net zero']
    },
    'biodiversity': {
        'name': 'Biodiversity',
        'keywords': ['biodiversity', 'endangered species', 'wildlife', 'ecosystem', 'habitat loss', 'deforestation', 'conservation', 'extinction', 'protected areas', 'reforestation']
    },
    'renewable_energy': {
        'name': 'Renewable Energy',
        'keywords': ['renewable energy', 'solar power', 'wind power', 'clean energy', 'green energy', 'hydropower', 'geothermal', 'biofuel', 'energy transition']
    },
    'sustainability': {
        'name': 'Sustainability',
        'keywords': ['sustainability', 'sustainable', 'circular economy', 'green economy', 'esg', 'corporate social responsibility', 'sustainable development goals', 'eco-friendly', 'resource efficiency']
    },
    'pollution': {
        'name': 'Pollution',
        'keywords': ['pollution', 'air quality', 'water pollution', 'plastic waste', 'chemical pollution', 'microplastic', 'ocean pollution', 'smog', 'contaminants']
    },
    'environmental_policy': {
        'name': 'Environmental Policy',
        'keywords': ['environmental policy', 'climate policy', 'environmental regulation', 'environmental law', 'environmental tax', 'subsidy', 'international agreement', 'climate agreement', 'environmental standard', 'carbon pricing', 'green deal']
    },
    'environmental_tech': {
        'name': 'Environmental Technology',
        'keywords': ['environmental technology', 'green tech', 'carbon capture', 'environmental monitoring', 'waste treatment', 'smart environment', 'clean tech', 'environmental innovation', 'sustainable technology', 'eco-innovation', 'recycling technology']
    },
    'others': {
        'name': 'Others',
        'keywords': [] # 'Others' 카테고리는 특정 키워드 없음
    }
}

# Redis 연결 설정 (환경변수 또는 기본값 사용)
REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)

# 불용어 설정
try:
    stop_words = set(stopwords.words('english'))
except Exception as e:
    logger.error(f"Failed to load NLTK stopwords: {e}. Using empty set.")
    stop_words = set()


def load_news_data():
    """JSON 파일에서 뉴스 데이터 로드 (현재 Redis 사용 중이므로 이 함수는 직접 사용되지 않음)"""
    # 이 함수는 파일 로딩 예시이며, 실제로는 fetch_news_from_redis()를 사용합니다.
    pass

def categorize_news(news_item):
    """뉴스 항목을 카테고리로 분류"""
    title_lower = news_item.get('title', '').lower()
    summary_lower = news_item.get('summary', '').lower()
    
    # 뉴스 제목과 요약 내용을 조합
    combined_text = title_lower + " " + summary_lower
    
    assigned_category = CATEGORIES['others']['name'] # 기본값은 'Others'
    
    for category_id, category_info in CATEGORIES.items():
        if category_id == 'others':
            continue # 'others' 카테고리는 키워드 매칭 대상에서 제외
            
        for keyword in category_info['keywords']:
            # 키워드가 뉴스 내용에 포함되는지 확인
            if keyword in combined_text:
                assigned_category = category_info['name']
                # logger.info(f"News '{news_item.get('title', '')[:50]}' categorized as: {assigned_category} (matched keyword: '{keyword}')") # 디버깅용
                return assigned_category # 첫 번째 매칭되는 카테고리 반환
    
    # logger.info(f"News '{news_item.get('title', '')[:50]}' categorized as: {assigned_category} (no specific keyword match)") # 디버깅용
    return assigned_category

def fetch_news_from_redis():
    """Redis에서 모든 뉴스 항목을 가져와 정렬하고 카테고리 정보 추가"""
    news_pattern = re.compile(r'^news-(\d{8})-(\d{3})$') # news-YYYYMMDD-XXX 패턴
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
                
                # 뉴스 로드 시 카테고리 정보 추가 (중요!)
                news_data['category'] = categorize_news(news_data) 
                news_list.append(news_data)
            except Exception as e:
                logger.warning(f"Invalid JSON in Redis for key {key}: {e}")
    
    # 발행일 기준으로 뉴스 정렬
    def parse_date(item):
        try:
            dt = parser.parse(item.get('published', ''))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            return dt
        except:
            # 날짜 파싱 실패 시 최소 날짜 반환하여 정렬에 영향을 미치지 않도록 함
            return datetime.min.replace(tzinfo=timezone.utc)

    news_list.sort(key=parse_date, reverse=True)
    return news_list

@app.route('/')
def index():
    """메인 페이지 라우트"""
    news_items = fetch_news_from_redis()

    # news_items에 이미 카테고리 정보가 있으므로, 분류만 하면 됨
    categorized_news = {category_id: [] for category_id in CATEGORIES.keys()}
    
    for news in news_items:
        # CATEGORIES 딕셔너리의 실제 카테고리 이름과 일치하는지 확인
        # find the category_id from news['category']
        for category_id, category_info in CATEGORIES.items():
            if news.get('category') == category_info['name']:
                categorized_news[category_id].append(news)
                break # 해당 뉴스는 하나의 카테고리에만 속하도록
    
    # 각 카테고리별 뉴스 수를 로그로 출력 (디버깅용)
    for cat_id, news_list in categorized_news.items():
        logger.info(f"Category '{CATEGORIES[cat_id]['name']}': {len(news_list)} news items")

    return render_template('index.html',
                         categorized_news=categorized_news,
                         categories=CATEGORIES,
                         sources=sorted(list(set(item.get('source', 'Unknown') for item in news_items if item.get('source')))), # 중복 제거 및 정렬
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
                if 'published' in item and item['published']:
                    published_dt = parser.parse(item['published'])
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
            
            cleaned_text = re.sub(r'[^a-zA-Z\s]', '', combined_text).lower()
            
            # 토큰화 및 불용어 제거 (NLTK stopwords가 로드되지 않았다면 이 부분에서 문제가 발생할 수 있음)
            try:
                words = word_tokenize(cleaned_text)
                filtered_words = [word for word in words if word.isalnum() and word not in stop_words and len(word) > 2]
                all_words.extend(filtered_words)
            except Exception as e:
                logger.error(f"Error tokenizing/filtering words for news item: {e}")
                continue
        
        common_exclude_keywords = set(['news', 'report', 'world', 'global', 'issue', 'new', 'says', 'company', 'government', 'country', 'state', 'million', 'billion', 'week', 'year', 'time', 'people'])
        filtered_keywords = [word for word in all_words if word not in common_exclude_keywords]

        keyword_counts = Counter(filtered_keywords)
        top_keywords = [{'keyword': keyword, 'count': count} for keyword, count in keyword_counts.most_common(20)]

        # 2. 출처 분포 계산
        source_counts = Counter(news.get('source', 'Unknown') for news in recent_news)
        source_distribution = [{'source': source, 'count': count} for source, count in source_counts.most_common()]

        # 3. 카테고리 분포 계산 (★ 모든 카테고리를 포함하도록 수정됨 ★)
        # 모든 정의된 카테고리를 0으로 초기화
        category_counts_dict = {CATEGORIES[c_id]['name']: 0 for c_id in CATEGORIES} 
        
        # 실제 뉴스 데이터로 카운트 업데이트
        for news in recent_news:
            cat_name = news.get('category', CATEGORIES['others']['name'])
            # 정의된 카테고리라면 카운트 증가, 아니면 'Others'에 추가
            if cat_name in category_counts_dict: 
                category_counts_dict[cat_name] += 1
            else: 
                category_counts_dict[CATEGORIES['others']['name']] += 1

        # 딕셔너리를 리스트 형태로 변환 (모든 카테고리 포함)
        # 차트 순서를 위해 카운트가 높은 순으로 정렬하는 것이 일반적
        category_distribution = [{'category': cat, 'count': count} for cat, count in category_counts_dict.items()]
        category_distribution.sort(key=lambda x: x['count'], reverse=True) # 빈도순으로 정렬
        
        logger.info(f"Calculated category distribution (including zeros): {category_distribution}")

        # 4. 국가 분포 계산
        country_mentions = Counter()
        country_keywords_map = {
            'united states': ['united states', 'us', 'usa', 'america', 'american'],
            'china': ['china', 'chinese'],
            'india': ['india', 'indian'],
            'european union': ['eu', 'european union', 'europe'],
            'united kingdom': ['uk', 'united kingdom', 'britain', 'british'],
            'japan': ['japan', 'japanese'],
            'south korea': ['south korea', 'korea', 'korean'], # 'korea' 추가
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
                    country_mentions[country_name.title()] += 1
        
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
    app.run(debug=True, port=5000)
