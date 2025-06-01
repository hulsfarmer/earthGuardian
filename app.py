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

# 로깅 설정: DEBUG 레벨로 설정하여 모든 상세 로그를 확인할 수 있도록 합니다.
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# NLTK 다운로드 (모든 환경에서 NLTK를 사용하기 전에 한 번 실행)
try:
    nltk.data.find('corpora/stopwords')
    nltk.data.find('tokenizers/punkt')
except Exception as e:
    logger.warning(f"NLTK resources not found, attempting download: {e}")
    try:
        nltk.download('stopwords')
        nltk.download('punkt')
        logger.info("NLTK stopwords and punkt downloaded successfully.")
    except Exception as download_e:
        logger.error(f"Failed to download NLTK resources: {download_e}. Please ensure NLTK is installed and has access to download directories.")


# 카테고리 키워드 정의
CATEGORIES = {
    'climate_change': {
        'name': 'Climate Change',
        'keywords': ['climate change', 'global warming', 'greenhouse gas', 'carbon emission', 'temperature rise', 'paris agreement', 'ipcc', 'cop', 'net zero', 'climate crisis', 'warming planet', 'carbon footprint', 'emission reduction']
    },
    'biodiversity': {
        'name': 'Biodiversity',
        'keywords': ['biodiversity', 'endangered species', 'wildlife', 'ecosystem', 'habitat loss', 'deforestation', 'conservation', 'extinction', 'protected areas', 'reforestation', 'species loss', 'natural habitats', 'forest destruction']
    },
    'renewable_energy': {
        'name': 'Renewable Energy',
        'keywords': ['renewable energy', 'solar power', 'wind power', 'clean energy', 'green energy', 'hydropower', 'geothermal', 'biofuel', 'energy transition', 'sustainable energy', 'solar farms', 'wind turbines']
    },
    'sustainability': {
        'name': 'Sustainability',
        'keywords': ['sustainability', 'sustainable', 'circular economy', 'green economy', 'esg', 'corporate social responsibility', 'sustainable development goals', 'eco-friendly', 'resource efficiency', 'recycling', 'waste management', 'green business']
    },
    'pollution': {
        'name': 'Pollution',
        'keywords': ['pollution', 'air quality', 'water pollution', 'plastic waste', 'chemical pollution', 'microplastic', 'ocean pollution', 'smog', 'contaminants', 'toxic waste', 'environmental contamination']
    },
    'environmental_policy': {
        'name': 'Environmental Policy',
        'keywords': ['environmental policy', 'climate policy', 'environmental regulation', 'environmental law', 'environmental tax', 'subsidy', 'international agreement', 'climate agreement', 'environmental standard', 'carbon pricing', 'green deal', 'government policy', 'legislation']
    },
    'environmental_tech': {
        'name': 'Environmental Technology',
        'keywords': ['environmental technology', 'green tech', 'carbon capture', 'environmental monitoring', 'waste treatment', 'smart environment', 'clean tech', 'environmental innovation', 'sustainable technology', 'eco-innovation', 'recycling technology', 'sensors', 'AI for environment']
    },
    'others': {
        'name': 'Others',
        'keywords': [] # 'Others' 카테고리는 특정 키워드 없음
    }
}

# Redis 연결 설정 (환경변수 또는 기본값 사용)
REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
redis_client = None # 초기화는 None으로 설정
try:
    redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    # 연결 테스트
    redis_client.ping()
    logger.info(f"Successfully connected to Redis at {REDIS_URL}")
except redis.exceptions.ConnectionError as e:
    logger.error(f"Could not connect to Redis at {REDIS_URL}: {e}. Please ensure Redis server is running.")
    redis_client = None # 연결 실패 시 None 유지
except Exception as e:
    logger.error(f"An unexpected error occurred while connecting to Redis: {e}")
    redis_client = None

# 불용어 설정
try:
    stop_words = set(stopwords.words('english'))
except Exception as e:
    logger.error(f"Failed to load NLTK stopwords: {e}. Using empty set.")
    stop_words = set()


def categorize_news(news_item):
    """뉴스 항목을 카테고리로 분류 (Redis에 category 정보가 없는 경우에만 사용)"""
    title_lower = news_item.get('title', '').lower()
    summary_lower = news_item.get('summary', '').lower()
    
    combined_text = title_lower + " " + summary_lower
    
    assigned_category = CATEGORIES['others']['name'] 
    
    for category_id, category_info in CATEGORIES.items():
        if category_id == 'others':
            continue
            
        for keyword in category_info['keywords']:
            if keyword in combined_text:
                assigned_category = category_info['name']
                logger.debug(f"categorize_news: '{news_item.get('title', '')[:40]}...' classified as '{assigned_category}' (keyword: '{keyword}')")
                return assigned_category
    
    logger.debug(f"categorize_news: '{news_item.get('title', '')[:40]}...' classified as 'Others' (no specific keywords found).")
    return assigned_category

def fetch_news_from_redis():
    """Redis에서 모든 뉴스 항목을 가져와 정렬하고, Redis의 category 정보가 있으면 우선 사용"""
    if redis_client is None:
        logger.error("fetch_news_from_redis: Redis client is not connected. Returning empty list.")
        return []

    news_pattern = re.compile(r'^news-(\d{8})-(\d{3})$') # 'news-YYYYMMDD-NNN' 형식
    
    try:
        keys = [key for key in redis_client.scan_iter('news-*') if news_pattern.match(key)]
        logger.info(f"fetch_news_from_redis: Found {len(keys)} keys matching 'news-*' pattern in Redis.")
    except Exception as e:
        logger.error(f"fetch_news_from_redis: Error scanning keys from Redis: {e}. Returning empty list.")
        return []
    
    if not keys:
        logger.info("fetch_news_from_redis: No 'news-*' keys found in Redis.")
        return []

    pipe = redis_client.pipeline()
    for key in keys:
        pipe.get(key)
    
    try:
        values = pipe.execute()
        logger.debug(f"fetch_news_from_redis: Successfully executed Redis pipeline for {len(keys)} keys.")
    except Exception as e:
        logger.error(f"fetch_news_from_redis: Error executing Redis pipeline: {e}. Returning empty list.")
        return []
    
    news_list = []
    for i, (key, value) in enumerate(zip(keys, values)):
        if value:
            try:
                news_item = json.loads(value)
                news_data = news_item.get('value', {}) # 'value' 키 아래에 실제 데이터가 있다고 가정
                news_data['redis_key'] = key
                
                # Redis에 'category' 필드가 이미 있거나, 빈 값이 아니라면 그대로 사용
                # 그렇지 않다면 categorize_news 함수를 통해 분류
                if 'category' not in news_data or not news_data['category']:
                    news_data['category'] = categorize_news(news_data) 
                
                news_list.append(news_data)
                logger.debug(f"fetch_news_from_redis: Parsed news item {i+1}/{len(keys)}: Title='{news_data.get('title', 'N/A')[:40]}...', Source='{news_data.get('source', 'N/A')}', Category='{news_data.get('category', 'N/A')}'")
            except json.JSONDecodeError as e:
                logger.error(f"fetch_news_from_redis: JSON Decode Error for key {key}: {e} - Value (first 100 chars): {value[:100]}...")
            except Exception as e:
                logger.error(f"fetch_news_from_redis: Other Error processing key {key}: {e} - Value (first 100 chars): {value[:100]}...")
        else:
            logger.warning(f"fetch_news_from_redis: Value for key {key} was empty or None.")
    
    if not news_list:
        logger.info("fetch_news_from_redis: No news items successfully parsed from Redis due to issues or empty values.")
    else:
        logger.info(f"fetch_news_from_redis: Successfully parsed {len(news_list)} valid news items from Redis.")
        
    def parse_date(item):
        date_str = item.get('published', '')
        if not date_str:
            logger.warning(f"parse_date: 'published' field is empty for news item: {item.get('title', 'N/A')[:50]}")
            return datetime.min.replace(tzinfo=timezone.utc)
        try:
            dt = parser.parse(date_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            return dt
        except Exception as e:
            logger.error(f"parse_date: Error parsing date '{date_str}' for news item '{item.get('title', 'N/A')[:50]}...': {e}")
            return datetime.min.replace(tzinfo=timezone.utc)

    # 뉴스 목록 정렬 전에 파싱된 날짜를 확인
    for item in news_list:
        parsed_dt = parse_date(item)
        if parsed_dt == datetime.min.replace(tzinfo=timezone.utc):
            logger.warning(f"News item '{item.get('title', 'N/A')[:50]}...' has unparseable date.")
        item['_parsed_published_date'] = parsed_dt # 정렬을 위해 파싱된 날짜 저장

    news_list.sort(key=lambda x: x['_parsed_published_date'], reverse=True)
    logger.info(f"fetch_news_from_redis: Sorted {len(news_list)} news items by date.")
    return news_list

@app.route('/')
def index():
    """메인 페이지 라우트"""
    logger.info("index route: Fetching news items for main page display.")
    news_items = fetch_news_from_redis()

    if not news_items:
        logger.warning("index route: No news items returned by fetch_news_from_redis. Main page will be empty.")
        categorized_news = {category_id: [] for category_id in CATEGORIES.keys()} # 빈 카테고리 딕셔너리
    else:
        logger.info(f"index route: Preparing to display {len(news_items)} news items on the main page.")
        categorized_news = {category_id: [] for category_id in CATEGORIES.keys()}
        
        for news in news_items:
            found_category = False
            # 이전에 categorize_news에서 category_name을 설정했음
            news_category_name = news.get('category', CATEGORIES['others']['name']) 
            
            # CATEGORIES 딕셔너리의 name 값과 일치하는 category_id를 찾아서 분류
            # category_name을 사용하여 category_id를 역으로 찾는 과정이 필요할 수 있습니다.
            # 현재 로직은 news_category_name (카테고리 이름)과 category_info['name'] (정의된 카테고리 이름)을 비교
            matched_category_id = None
            for category_id, category_info in CATEGORIES.items():
                if news_category_name == category_info['name']:
                    matched_category_id = category_id
                    break
            
            if matched_category_id:
                categorized_news[matched_category_id].append(news)
                found_category = True
            else:
                # 정의되지 않은 카테고리 이름이 들어왔다면 'others'로 분류
                logger.warning(f"index route: News item '{news.get('title', 'N/A')[:50]}' has unknown category name '{news_category_name}', assigning to 'Others'.")
                categorized_news['others'].append(news) 
    
    # ------------------ 최종 categorized_news 딕셔너리 내용 로깅 ------------------
    for cat_id, news_list_in_cat in categorized_news.items():
        logger.info(f"index route: Final categorized_news - Category '{CATEGORIES[cat_id]['name']}' (ID: {cat_id}) has {len(news_list_in_cat)} news items.")
        if news_list_in_cat and cat_id != 'others': # others가 아닌 카테고리에 뉴스가 있다면 샘플 로깅
            logger.info(f"index route: Sample from '{CATEGORIES[cat_id]['name']}': Title='{news_list_in_cat[0].get('title', 'N/A')[:50]}...'")
    # -----------------------------------------------------------------------------

    sources_set = set(item.get('source', 'Unknown') for item in news_items if item.get('source'))
    sorted_sources = sorted(list(sources_set))
    logger.info(f"index route: Found {len(sorted_sources)} unique sources.")

    return render_template('index.html',
                         categorized_news=categorized_news,
                         categories=CATEGORIES,
                         sources=sorted_sources,
                         current_category='',
                         current_source='',
                         current_sort='newest')

@app.route('/api/trends')
def get_trends():
    """트렌드 리포트 API 엔드포인트"""
    logger.info("get_trends: API endpoint called.")
    period = request.args.get('period', 'weekly')
    if period not in ['weekly', 'monthly']:
        logger.warning(f"get_trends: Invalid period requested: {period}")
        return jsonify({'error': 'Invalid period'}), 400
    try:
        news_items = fetch_news_from_redis() # Redis에서 뉴스 가져오기
        
        if not news_items:
            logger.info("get_trends: No news items available from Redis for trend calculation. Returning empty trends.")
            return jsonify({
                'top_keywords': [],
                'source_distribution': [],
                'category_distribution': [],
                'country_distribution': [],
                'sample_news': []
            })

        now = datetime.now(timezone.utc)
        if period == 'weekly':
            cutoff = now - timedelta(days=7)
        else:  # monthly
            cutoff = now - timedelta(days=30)
        
        recent_news = []
        for item in news_items:
            # _parsed_published_date를 사용하여 시간 비교 (fetch_news_from_redis에서 이미 파싱됨)
            if '_parsed_published_date' in item and item['_parsed_published_date'] >= cutoff:
                recent_news.append(item)
            else:
                # published 필드가 없거나 파싱 오류가 있는 경우도 고려하여 경고 로깅
                if '_parsed_published_date' not in item:
                    logger.warning(f"get_trends: News item '{item.get('title', 'N/A')[:50]}' missing '_parsed_published_date' for filtering.")
                elif item['_parsed_published_date'] == datetime.min.replace(tzinfo=timezone.utc):
                     logger.warning(f"get_trends: News item '{item.get('title', 'N/A')[:50]}' has unparseable date, excluded from trends.")

        logger.info(f"get_trends: Filtered down to {len(recent_news)} recent news items for period '{period}'.")
        
        if not recent_news:
            logger.info(f"get_trends: No recent news items found for '{period}' period. Returning empty trends.")
            return jsonify({
                'top_keywords': [],
                'source_distribution': [],
                'category_distribution': [],
                'country_distribution': [],
                'sample_news': []
            })
                
        # --- 실제 트렌드 데이터 계산 로직 ---
        
        # 1. 키워드 빈도 계산
        all_words = []
        for news in recent_news:
            title_text = news.get('title', '')
            summary_text = news.get('summary', '')
            combined_text = title_text + ' ' + summary_text
            
            cleaned_text = re.sub(r'[^a-zA-Z\s]', '', combined_text).lower()
            
            try:
                words = word_tokenize(cleaned_text)
                filtered_words = [word for word in words if word.isalnum() and word not in stop_words and len(word) > 2]
                all_words.extend(filtered_words)
            except Exception as e:
                logger.error(f"get_trends: Error tokenizing/filtering words for news item '{news.get('title', 'N/A')[:50]}...': {e}")
                continue
        
        common_exclude_keywords = set(['news', 'report', 'world', 'global', 'issue', 'new', 'says', 'company', 'government', 'country', 'state', 'million', 'billion', 'week', 'year', 'time', 'people', 'climate', 'energy', 'environmental']) 
        filtered_keywords = [word for word in all_words if word not in common_exclude_keywords]

        keyword_counts = Counter(filtered_keywords)
        top_keywords = [{'keyword': keyword, 'count': count} for keyword, count in keyword_counts.most_common(20)]
        logger.debug(f"get_trends: Top keywords calculated: {top_keywords}")

        # 2. 출처 분포 계산
        source_counts = Counter(news.get('source', 'Unknown') for news in recent_news)
        source_distribution = [{'source': source, 'count': count} for source, count in source_counts.most_common()]
        logger.debug(f"get_trends: Source distribution calculated: {source_distribution}")

        # 3. 카테고리 분포 계산 (Redis의 category 값을 그대로 사용)
        category_counts_dict = {CATEGORIES[c_id]['name']: 0 for c_id in CATEGORIES} 
        
        for news in recent_news:
            cat_name = news.get('category', CATEGORIES['others']['name']) 
            if cat_name in category_counts_dict: 
                category_counts_dict[cat_name] += 1
            else: 
                # CATEGORIES에 정의되지 않은 카테고리 이름이라면 'Others'로 분류
                logger.warning(f"get_trends: News item '{news.get('title', 'N/A')[:50]}' has unknown category '{cat_name}', assigning to 'Others'.")
                category_counts_dict[CATEGORIES['others']['name']] += 1

        category_distribution = [{'category': cat, 'count': count} for cat, count in category_counts_dict.items()]
        category_distribution.sort(key=lambda x: x['count'], reverse=True) 
        
        logger.info(f"get_trends: Final category distribution calculated: {category_distribution}")

        # 4. 국가 분포 계산
        country_mentions = Counter()
        country_keywords_map = {
            'united states': ['united states', 'us', 'usa', 'america', 'american'],
            'china': ['china', 'chinese'],
            'india': ['india', 'indian'],
            'european union': ['eu', 'european union', 'europe'],
            'united kingdom': ['uk', 'united kingdom', 'britain', 'british'],
            'japan': ['japan', 'japanese'],
            'south korea': ['south korea', 'korea', 'korean'],
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
        logger.debug(f"get_trends: Country distribution calculated: {country_distribution}")

        return jsonify({
            'top_keywords': top_keywords,
            'source_distribution': source_distribution,
            'category_distribution': category_distribution, 
            'country_distribution': country_distribution,
            'sample_news': recent_news # 필터링된 실제 뉴스 데이터 반환
        })

    except Exception as e:
        logger.error(f"get_trends: Unhandled error generating trends: {str(e)}", exc_info=True) # exc_info=True로 전체 traceback 로깅
        return jsonify({'error': 'Failed to generate trends', 'details': str(e)}), 500

@app.route('/trends')
def trends_page():
    logger.info("trends_page: Rendering trends.html.")
    return render_template('trends.html')

if __name__ == '__main__':
    app.run(debug=True, port=5000)
