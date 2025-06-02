from flask import Flask, render_template, request, jsonify, send_from_directory
import json
from datetime import datetime, timedelta, timezone
import logging
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

# NLTK 다운로드 (한 번만 실행해도 됨)
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
        logger.error(f"Failed to download NLTK resources: {download_e}. Please ensure NLTK is installed.")


# 카테고리 키워드 정의
CATEGORIES = {
    'climate_change': {
        'name': 'Climate Change',
        'keywords': [
            'climate change', 'global warming', 'greenhouse gas',
            'carbon emission', 'temperature rise', 'paris agreement',
            'ipcc', 'cop', 'net zero', 'climate crisis',
            'warming planet', 'carbon footprint', 'emission reduction'
        ]
    },
    'biodiversity': {
        'name': 'Biodiversity',
        'keywords': [
            'biodiversity', 'endangered species', 'wildlife',
            'ecosystem', 'habitat loss', 'deforestation',
            'conservation', 'extinction', 'protected areas',
            'reforestation', 'species loss', 'natural habitats',
            'forest destruction'
        ]
    },
    'renewable_energy': {
        'name': 'Renewable Energy',
        'keywords': [
            'renewable energy', 'solar power', 'wind power',
            'clean energy', 'green energy', 'hydropower',
            'geothermal', 'biofuel', 'energy transition',
            'sustainable energy', 'solar farms', 'wind turbines'
        ]
    },
    'sustainability': {
        'name': 'Sustainability',
        'keywords': [
            'sustainability', 'sustainable', 'circular economy',
            'green economy', 'esg', 'corporate social responsibility',
            'sustainable development goals', 'eco-friendly',
            'resource efficiency', 'recycling', 'waste management',
            'green business'
        ]
    },
    'pollution': {
        'name': 'Pollution',
        'keywords': [
            'pollution', 'air quality', 'water pollution',
            'plastic waste', 'chemical pollution', 'microplastic',
            'ocean pollution', 'smog', 'contaminants', 'toxic waste',
            'environmental contamination'
        ]
    },
    'environmental_policy': {
        'name': 'Environmental Policy',
        'keywords': [
            'environmental policy', 'climate policy',
            'environmental regulation', 'environmental law',
            'environmental tax', 'subsidy', 'international agreement',
            'climate agreement', 'environmental standard',
            'carbon pricing', 'green deal', 'government policy',
            'legislation'
        ]
    },
    'environmental_tech': {
        'name': 'Environmental Technology',
        'keywords': [
            'environmental technology', 'green tech',
            'carbon capture', 'environmental monitoring',
            'waste treatment', 'smart environment', 'clean tech',
            'environmental innovation', 'sustainable technology',
            'eco-innovation', 'recycling technology', 'sensors',
            'AI for environment'
        ]
    },
    'others': {
        'name': 'Others',
        'keywords': []  # 'Others' 카테고리는 특정 키워드 없음
    }
}

# Redis 연결 설정 (환경변수 또는 기본값 사용)
REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
redis_client = None
try:
    redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    redis_client.ping()
    logger.info(f"Successfully connected to Redis at {REDIS_URL}")
except redis.exceptions.ConnectionError as e:
    logger.error(f"Could not connect to Redis at {REDIS_URL}: {e}")
    redis_client = None
except Exception as e:
    logger.error(f"Unexpected error while connecting to Redis: {e}")
    redis_client = None

# 불용어 설정
try:
    stop_words = set(stopwords.words('english'))
except Exception as e:
    logger.error(f"Failed to load NLTK stopwords: {e}. Using empty set.")
    stop_words = set()


def categorize_news(news_item):
    """
    뉴스 항목을 키워드 기반으로 카테고리 분류.
    news_item에 'category'가 없거나 유효하지 않을 때만 호출됩니다.
    """
    title_lower = news_item.get('title', '').lower()
    summary_lower = news_item.get('summary', '').lower()
    combined_text = title_lower + " " + summary_lower

    assigned_category_name = CATEGORIES['others']['name']
    for category_id, category_info in CATEGORIES.items():
        if category_id == 'others':
            continue
        for keyword in category_info['keywords']:
            if keyword in combined_text:
                assigned_category_name = category_info['name']
                logger.debug(
                    f"categorize_news: '{news_item.get('title', '')[:40]}...' "
                    f"classified as '{assigned_category_name}' (keyword: '{keyword}')"
                )
                return assigned_category_name

    logger.debug(
        f"categorize_news: '{news_item.get('title', '')[:40]}...' classified as 'Others'."
    )
    return assigned_category_name


def fetch_news_from_redis():
    """
    Redis에서 모든 뉴스 항목을 가져와 정렬하고,
    Key('news-YYYYMMDD-NNN')에서 날짜를 직접 추출하여 '_parsed_published_date'로 저장합니다.
    Redis 데이터에 'category' 필드가 있으면 그것을 우선 사용하고,
    없거나 유효하지 않으면 categorize_news 함수를 통해 분류합니다.
    """
    if redis_client is None:
        logger.error("fetch_news_from_redis: Redis client is not connected. Returning empty list.")
        return []

    news_pattern = re.compile(r'^news-(\d{8})-(\d{3})$')  # 'news-YYYYMMDD-NNN' 형식
    try:
        keys = [key for key in redis_client.scan_iter('news-*') if news_pattern.match(key)]
        logger.info(f"fetch_news_from_redis: Found {len(keys)} keys matching 'news-*' in Redis.")
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
        logger.debug(f"fetch_news_from_redis: Executed Redis pipeline for {len(keys)} keys.")
    except Exception as e:
        logger.error(f"fetch_news_from_redis: Error executing Redis pipeline: {e}. Returning empty list.")
        return []

    news_list = []
    for key, value in zip(keys, values):
        if not value:
            logger.warning(f"fetch_news_from_redis: Value for key {key} was empty or None.")
            continue

        try:
            news_item = json.loads(value)
            news_data = news_item.get('value', {})
            news_data['redis_key'] = key

            # Redis에 저장된 category 우선 사용, 없으면 키워드 분류
            redis_category_name = news_data.get('category')
            is_valid = False
            if redis_category_name:
                for cat_info in CATEGORIES.values():
                    if redis_category_name == cat_info['name']:
                        is_valid = True
                        break

            if is_valid:
                news_data['category'] = redis_category_name
                logger.debug(f"Using Redis category '{redis_category_name}' for key {key}.")
            else:
                news_data['category'] = categorize_news(news_data)
                logger.debug(f"Redis category invalid/missing for {key}, classified as '{news_data['category']}'.")

            # Key에서 날짜 추출
            m = news_pattern.match(key)
            if m:
                date_str = m.group(1)  # 'YYYYMMDD'
                try:
                    dt = datetime.strptime(date_str, "%Y%m%d").replace(tzinfo=timezone.utc)
                    news_data['_parsed_published_date'] = dt
                except Exception as e:
                    logger.error(f"Error parsing date from key '{key}': {e}")
                    news_data['_parsed_published_date'] = datetime.min.replace(tzinfo=timezone.utc)
            else:
                logger.warning(f"Key '{key}' did not match pattern.")
                news_data['_parsed_published_date'] = datetime.min.replace(tzinfo=timezone.utc)

            news_list.append(news_data)

        except json.JSONDecodeError as e:
            logger.error(f"JSON Decode Error for key {key}: {e}")
        except Exception as e:
            logger.error(f"Error processing key {key}: {e}")

    if news_list:
        news_list.sort(
            key=lambda x: x.get('_parsed_published_date', datetime.min.replace(tzinfo=timezone.utc)),
            reverse=True
        )
        logger.info(f"fetch_news_from_redis: Sorted {len(news_list)} news items by parsed date.")
    else:
        logger.info("fetch_news_from_redis: No valid news items parsed from Redis.")

    return news_list


@app.route('/')
def index():
    """메인 페이지 라우트"""
    logger.info("index route: Fetching news items for main page display.")

    # 1) GET 파라미터 읽기
    current_category = request.args.get('category', '')
    current_source   = request.args.get('source', '')
    current_sort     = request.args.get('sort', 'newest')

    # 2) Redis에서 모든 뉴스 가져오기
    news_items = fetch_news_from_redis()

    # 3) 정렬 처리: 'oldest'인 경우만 뒤집기
    if current_sort == 'oldest':
        news_items = list(reversed(news_items))

    # 4) 카테고리별로 그룹핑
    categorized_news = {cat_id: [] for cat_id in CATEGORIES.keys()}
    for news in news_items:
        news_category_name = news.get('category', CATEGORIES['others']['name'])
        matched_cat_id = None
        for cid, info in CATEGORIES.items():
            if news_category_name == info['name']:
                matched_cat_id = cid
                break
        if matched_cat_id:
            categorized_news[matched_cat_id].append(news)
        else:
            categorized_news['others'].append(news)

    # 5) 소스 목록 생성 (중복 제거 + 정렬)
    sources_set = {n['source'] for n in news_items if n.get('source')}
    sorted_sources = sorted(sources_set)

    # 6) 템플릿 렌더링 (필터 파라미터도 함께 넘김)
    return render_template(
        'index.html',
        categorized_news=categorized_news,
        categories=CATEGORIES,
        sources=sorted_sources,
        current_category=current_category,
        current_source=current_source,
        current_sort=current_sort
    )


@app.route('/api/trends')
def get_trends():
    """트렌드 리포트 API 엔드포인트"""
    logger.info("get_trends: API endpoint called.")
    period = request.args.get('period', 'weekly')
    if period not in ['weekly', 'monthly']:
        logger.warning(f"get_trends: Invalid period requested: {period}")
        return jsonify({'error': 'Invalid period'}), 400

    try:
        news_items = fetch_news_from_redis()
        if not news_items:
            logger.info("No news items in Redis; returning empty trends.")
            return jsonify({
                'top_keywords': [],
                'source_distribution': [],
                'category_distribution': [],
                'country_distribution': [],
                'sample_news': []
            })

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=7) if period == 'weekly' else now - timedelta(days=30)

        recent_news = [
            item for item in news_items
            if item.get('_parsed_published_date') and item['_parsed_published_date'] >= cutoff
        ]
        logger.info(f"Filtered {len(recent_news)} recent news items for '{period}'.")

        if not recent_news:
            logger.info(f"No recent news items for '{period}'; returning empty trends.")
            return jsonify({
                'top_keywords': [],
                'source_distribution': [],
                'category_distribution': [],
                'country_distribution': [],
                'sample_news': []
            })

        # 1) 키워드 빈도 계산
        all_words = []
        for news in recent_news:
            combined = f"{news.get('title','')} {news.get('summary','')}"
            cleaned = re.sub(r'[^a-zA-Z\s]', '', combined).lower()
            try:
                tokens = word_tokenize(cleaned)
                filtered = [w for w in tokens if w.isalnum() and w not in stop_words and len(w) > 2]
                all_words.extend(filtered)
            except Exception as e:
                logger.error(f"Error tokenizing words for '{news.get('title','')}': {e}")
        common_exclude = {
            'news','report','world','global','issue','new','says','company','government','country',
            'state','million','billion','week','year','time','people','climate','energy','environmental'
        }
        filtered_keywords = [w for w in all_words if w not in common_exclude]
        keyword_counts = Counter(filtered_keywords)
        top_keywords = [{'keyword': k, 'count': c} for k, c in keyword_counts.most_common(20)]
        logger.debug(f"Top keywords: {top_keywords}")

        # 2) 출처 분포 계산
        all_sources = {item.get('source','Unknown').strip() for item in news_items if item.get('source')}
        source_counts = Counter(item.get('source','Unknown').strip() for item in recent_news if item.get('source'))
        source_distribution = [
            {'source': s, 'count': source_counts.get(s,0)} for s in sorted(all_sources, key=lambda x: x.lower())
        ]
        logger.debug(f"Source distribution: {source_distribution}")

        # 3) 카테고리 분포 계산
        category_counts_dict = {info['name']: 0 for info in CATEGORIES.values()}
        for news in recent_news:
            cn = news.get('category', CATEGORIES['others']['name'])
            if cn in category_counts_dict:
                category_counts_dict[cn] += 1
            else:
                category_counts_dict[CATEGORIES['others']['name']] += 1
        category_distribution = [
            {'category': cat, 'count': cnt} for cat, cnt in category_counts_dict.items()
        ]
        category_distribution.sort(key=lambda x: x['count'], reverse=True)
        logger.info(f"Category distribution: {category_distribution}")

        # 4) 국가 분포 계산
        country_mentions = Counter()
        country_keywords_map = {
            'United States': ['united states','us','usa','america','american'],
            'China': ['china','chinese'],
            'India': ['india','indian'],
            'European Union': ['eu','european union','europe','brussels'],
            'United Kingdom': ['uk','united kingdom','britain','british','london'],
            'Japan': ['japan','japanese','tokyo'],
            'South Korea': ['south korea','korea','korean','seoul'],
            'Australia': ['australia','australian','canberra','sydney'],
            'Brazil': ['brazil','brazilian','brasilia'],
            'Russia': ['russia','russian','moscow'],
            'Canada': ['canada','canadian','ottawa'],
            'Germany': ['germany','german','berlin'],
            'France': ['france','french','paris'],
            'Italy': ['italy','italian','rome'],
            'Spain': ['spain','spanish','madrid']
        }
        for news in recent_news:
            text = (news.get('title','') + " " + news.get('summary','')).lower()
            for country, keywords in country_keywords_map.items():
                if any(k in text for k in keywords):
                    country_mentions[country] += 1
        country_distribution = [{'country': c, 'count': cnt} for c, cnt in country_mentions.most_common()]
        logger.debug(f"Country distribution: {country_distribution}")

        return jsonify({
            'top_keywords': top_keywords,
            'source_distribution': source_distribution,
            'category_distribution': category_distribution,
            'country_distribution': country_distribution,
            'sample_news': recent_news
        })

    except Exception as e:
        logger.error(f"get_trends: Unhandled error generating trends: {e}", exc_info=True)
        return jsonify({'error': 'Failed to generate trends', 'details': str(e)}), 500


@app.route('/trends')
def trends_page():
    logger.info("trends_page: Rendering trends.html.")
    return render_template('trends.html')

@app.route('/ads.txt')
def ads_txt():
    return send_from_directory('.', 'ads.txt')  # 루트 디렉토리에서 ads.txt 반환

@app.route('/privacy_policy.html')
def privacy():
    return render_template('privacy_policy.html')

@app.route('/terms_of_service.html')
def terms():
    return render_template('terms_of_service.html')

@app.route('/contact_us.html')
def contact():
    return render_template('contact_us.html')

@app.route('/about_us.html')
def about():
    return render_template('about_us.html')

# report.py에서 정의한 Blueprint를 가져와서 등록
from report import reports_bp
app.register_blueprint(reports_bp)

if __name__ == '__main__':
    app.run(debug=True, port=5000)
