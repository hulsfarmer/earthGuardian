from flask import Flask, render_template, request, jsonify
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

# NLTK 다운로드 (모든 환경에서 NLTK를 사용하기 전에 한 번 실행)
# 'stopwords'와 'punkt'는 트렌드 분석에 필요합니다.
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
redis_client = None  # 초기화는 None으로 설정
try:
    redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    # 연결 테스트
    redis_client.ping()
    logger.info(f"Successfully connected to Redis at {REDIS_URL}")
except redis.exceptions.ConnectionError as e:
    logger.error(f"Could not connect to Redis at {REDIS_URL}: {e}. Please ensure Redis server is running.")
    redis_client = None  # 연결 실패 시 None 유지
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
    """
    뉴스 항목을 키워드 기반으로 카테고리 분류.
    news_item에 'category'가 없거나 유효하지 않을 때만 호출됩니다.
    """
    title_lower = news_item.get('title', '').lower()
    summary_lower = news_item.get('summary', '').lower()

    combined_text = title_lower + " " + summary_lower

    assigned_category_name = CATEGORIES['others']['name']  # 기본값은 'Others'

    for category_id, category_info in CATEGORIES.items():
        if category_id == 'others':
            continue  # 'others' 카테고리 자체는 키워드 기반 분류에서 제외

        for keyword in category_info['keywords']:
            if keyword in combined_text:
                assigned_category_name = category_info['name']
                logger.debug(
                    f"categorize_news: '{news_item.get('title', '')[:40]}...' "
                    f"classified as '{assigned_category_name}' (keyword: '{keyword}')"
                )
                return assigned_category_name  # 일치하는 키워드 찾으면 즉시 반환

    logger.debug(
        f"categorize_news: '{news_item.get('title', '')[:40]}...' classified as 'Others' "
        "(no specific keywords found)."
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
    for key, value in zip(keys, values):
        if not value:
            logger.warning(f"fetch_news_from_redis: Value for key {key} was empty or None.")
            continue

        try:
            news_item = json.loads(value)
            news_data = news_item.get('value', {})  # 'value' 키 아래에 실제 데이터가 있다고 가정
            news_data['redis_key'] = key

            # --- 기존 뉴스 페이지 작동 방식 유지: Redis category 우선 사용 및 Fallback ---
            redis_category_name = news_data.get('category')

            # Redis에서 가져온 category 값이 유효한지 확인 (CATEGORIES의 name 값과 비교)
            is_valid_redis_category = False
            if redis_category_name:
                for cat_info in CATEGORIES.values():
                    if redis_category_name == cat_info['name']:
                        is_valid_redis_category = True
                        break

            if is_valid_redis_category:
                news_data['category'] = redis_category_name
                logger.debug(
                    f"fetch_news_from_redis: Using Redis category '{redis_category_name}' for key {key}."
                )
            else:
                # Redis에 category가 없거나 유효하지 않으면 categorize_news 호출
                news_data['category'] = categorize_news(news_data)
                logger.debug(
                    f"fetch_news_from_redis: Redis category for key '{key}' was invalid/missing "
                    f"('{redis_category_name}'). Classified as '{news_data['category']}'."
                )
            # -------------------------------------------------------------------

            # 2) Key에서 날짜(YYYYMMDD) 추출 → datetime 객체로 변환하여 '_parsed_published_date'로 저장
            m = news_pattern.match(key)
            if m:
                date_str = m.group(1)  # 'YYYYMMDD'
                try:
                    # UTC 기준으로 자정 00:00:00
                    dt = datetime.strptime(date_str, "%Y%m%d").replace(tzinfo=timezone.utc)
                    news_data['_parsed_published_date'] = dt
                except Exception as e:
                    logger.error(f"fetch_news_from_redis: Error parsing date from key '{key}': {e}")
                    news_data['_parsed_published_date'] = datetime.min.replace(tzinfo=timezone.utc)
            else:
                logger.warning(f"fetch_news_from_redis: Key '{key}' did not match pattern.")
                news_data['_parsed_published_date'] = datetime.min.replace(tzinfo=timezone.utc)

            news_list.append(news_data)

        except json.JSONDecodeError as e:
            logger.error(f"fetch_news_from_redis: JSON Decode Error for key {key}: {e}")
        except Exception as e:
            logger.error(f"fetch_news_from_redis: Other Error processing key {key}: {e}")

    if not news_list:
        logger.info("fetch_news_from_redis: No news items successfully parsed from Redis due to issues or empty values.")
    else:
        logger.info(f"fetch_news_from_redis: Successfully parsed {len(news_list)} valid news items from Redis.")

    # '_parsed_published_date'를 기준으로 내림차순 정렬
    news_list.sort(
        key=lambda x: x.get('_parsed_published_date', datetime.min.replace(tzinfo=timezone.utc)),
        reverse=True
    )
    logger.info(f"fetch_news_from_redis: Sorted {len(news_list)} news items by parsed date.")
    return news_list


@app.route('/')
def index():
    """메인 페이지 라우트"""
    logger.info("index route: Fetching news items for main page display.")
    news_items = fetch_news_from_redis()

    if not news_items:
        logger.warning("index route: No news items returned by fetch_news_from_redis. Main page will be empty.")
        categorized_news = {category_id: [] for category_id in CATEGORIES.keys()}
    else:
        logger.info(f"index route: Preparing to display {len(news_items)} news items on the main page.")
        categorized_news = {category_id: [] for category_id in CATEGORIES.keys()}

        for news in news_items:
            # Redis에서 설정된 category 또는 categorize_news()로 설정된 값을 사용
            news_category_name = news.get('category', CATEGORIES['others']['name'])

            # CATEGORIES 딕셔너리의 name 값과 일치하는 category_id를 찾아서 분류
            matched_category_id = None
            for category_id, category_info in CATEGORIES.items():
                if news_category_name == category_info['name']:
                    matched_category_id = category_id
                    break

            if matched_category_id:
                categorized_news[matched_category_id].append(news)
            else:
                logger.warning(
                    f"index route: News item '{news.get('title', 'N/A')[:50]}' has an unexpected category name "
                    f"'{news_category_name}'. Assigning to 'Others'."
                )
                categorized_news['others'].append(news)

    for cat_id, news_list_in_cat in categorized_news.items():
        logger.info(
            f"index route: Category '{CATEGORIES[cat_id]['name']}' (ID: {cat_id}) has {len(news_list_in_cat)} news items."
        )
        if news_list_in_cat and cat_id != 'others':
            logger.debug(
                f"index route: Sample from '{CATEGORIES[cat_id]['name']}': "
                f"Title='{news_list_in_cat[0].get('title', 'N/A')[:50]}...'"
            )

    sources_set = set(item.get('source', 'Unknown') for item in news_items if item.get('source'))
    sorted_sources = sorted(list(sources_set))
    logger.info(f"index route: Found {len(sorted_sources)} unique sources.")

    return render_template(
        'index.html',
        categorized_news=categorized_news,
        categories=CATEGORIES,
        sources=sorted_sources,
        current_category='',
        current_source='',
        current_sort='newest'
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
        news_items = fetch_news_from_redis()  # Redis에서 모든 뉴스 항목 가져오기

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
        cutoff = now - timedelta(days=7) if period == 'weekly' else now - timedelta(days=30)

        # Key에서 가져온 '_parsed_published_date'를 사용하여 필터링
        recent_news = [
            item for item in news_items
            if item.get('_parsed_published_date') and item['_parsed_published_date'] >= cutoff
        ]
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

        # 1. 키워드 빈도 계산
        all_words = []
        for news in recent_news:
            title_text = news.get('title', '')
            summary_text = news.get('summary', '')
            combined_text = f"{title_text} {summary_text}"
            cleaned_text = re.sub(r'[^a-zA-Z\s]', '', combined_text).lower()
            try:
                words = word_tokenize(cleaned_text)
                filtered_words = [
                    word for word in words
                    if word.isalnum() and word not in stop_words and len(word) > 2
                ]
                all_words.extend(filtered_words)
            except Exception as e:
                logger.error(
                    f"get_trends: Error tokenizing/filtering words for news item "
                    f"'{news.get('title', 'N/A')[:50]}...': {e}"
                )
                continue

        common_exclude_keywords = {
            'news', 'report', 'world', 'global', 'issue', 'new', 'says',
            'company', 'government', 'country', 'state', 'million', 'billion',
            'week', 'year', 'time', 'people', 'climate', 'energy',
            'environmental', 'find', 'also', 'one', 'would', 'could',
            'get', 'like', 'just', 'still', 'big', 'back', 'take', 'make',
            'first', 'last', 'well', 'much', 'many', 'think', 'even',
            'said', 'going', 'help', 'across', 'around', 'among',
            'might', 'must', 'need', 'next', 'only', 'over', 'part',
            'per', 'cent', 'place', 'set', 'show', 'side', 'since',
            'small', 'some', 'than', 'that', 'them', 'then', 'there',
            'these', 'they', 'this', 'those', 'through', 'too', 'under',
            'up', 'upon', 'very', 'want', 'was', 'way', 'we', 'well',
            'were', 'what', 'when', 'where', 'which', 'while', 'who',
            'whom', 'why', 'will', 'with', 'within', 'without', 'won',
            'would', 'yes', 'yet', 'you', 'your', 'yours', 'etc', 'etcetera'
        }
        filtered_keywords = [word for word in all_words if word not in common_exclude_keywords]
        keyword_counts = Counter(filtered_keywords)
        top_keywords = [
            {'keyword': keyword, 'count': count}
            for keyword, count in keyword_counts.most_common(20)
        ]
        logger.debug(f"get_trends: Top keywords calculated: {top_keywords}")

        # 2. 출처 분포 계산
        all_sources = {
            item.get('source', 'Unknown').strip() for item in news_items if item.get('source')
        }
        source_counts = Counter(
            item.get('source', 'Unknown').strip() for item in recent_news if item.get('source')
        )
        source_distribution = [
            {'source': source, 'count': source_counts.get(source, 0)}
            for source in sorted(all_sources, key=lambda s: s.lower())
        ]
        logger.debug(f"get_trends: Source distribution calculated: {source_distribution}")

        # 3. 카테고리 분포 계산
        category_counts_dict = {
            info['name']: 0 for info in CATEGORIES.values()
        }
        for news in recent_news:
            cat_name = news.get('category', CATEGORIES['others']['name'])
            if cat_name in category_counts_dict:
                category_counts_dict[cat_name] += 1
            else:
                logger.warning(
                    f"get_trends: News item '{news.get('title', 'N/A')[:50]}' has an unexpected category name '{cat_name}'. Assigning to 'Others'."
                )
                category_counts_dict[CATEGORIES['others']['name']] += 1

        category_distribution = [
            {'category': cat, 'count': count}
            for cat, count in category_counts_dict.items()
        ]
        category_distribution.sort(key=lambda x: x['count'], reverse=True)
        logger.info(f"get_trends: Final category distribution calculated: {category_distribution}")

        # 4. 국가 분포 계산
        country_mentions = Counter()
        country_keywords_map = {
            'United States': ['united states', 'us', 'usa', 'america', 'american'],
            'China': ['china', 'chinese'],
            'India': ['india', 'indian'],
            'European Union': ['eu', 'european union', 'europe', 'brussels'],
            'United Kingdom': ['uk', 'united kingdom', 'britain', 'british', 'london'],
            'Japan': ['japan', 'japanese', 'tokyo'],
            'South Korea': ['south korea', 'korea', 'korean', 'seoul'],
            'Australia': ['australia', 'australian', 'canberra', 'sydney'],
            'Brazil': ['brazil', 'brazilian', 'brasilia'],
            'Russia': ['russia', 'russian', 'moscow'],
            'Canada': ['canada', 'canadian', 'ottawa'],
            'Germany': ['germany', 'german', 'berlin'],
            'France': ['france', 'french', 'paris'],
            'Italy': ['italy', 'italian', 'rome'],
            'Spain': ['spain', 'spanish', 'madrid']
        }

        for news in recent_news:
            text = (news.get('title', '') + ' ' + news.get('summary', '')).lower()
            for country_name, keywords in country_keywords_map.items():
                if any(k in text for k in keywords):
                    country_mentions[country_name] += 1

        country_distribution = [
            {'country': country, 'count': count}
            for country, count in country_mentions.most_common()
        ]
        logger.debug(f"get_trends: Country distribution calculated: {country_distribution}")

        return jsonify({
            'top_keywords': top_keywords,
            'source_distribution': source_distribution,
            'category_distribution': category_distribution,
            'country_distribution': country_distribution,
            'sample_news': recent_news  # 필터링된 실제 뉴스 데이터 반환
        })

    except Exception as e:
        logger.error(f"get_trends: Unhandled error generating trends: {str(e)}", exc_info=True)
        return jsonify({'error': 'Failed to generate trends', 'details': str(e)}), 500


@app.route('/trends')
def trends_page():
    logger.info("trends_page: Rendering trends.html.")
    return render_template('trends.html')


if __name__ == '__main__':
    app.run(debug=True, port=5000)
