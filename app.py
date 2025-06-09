from flask import Flask, render_template, request, jsonify, send_from_directory, abort, redirect, url_for
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
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
import atexit

app = Flask(__name__)

# 로깅 설정: INFO 레벨로 조정하여 운영 환경에 적합하게 변경합니다.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
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

     'sustainability': {
        'name': 'Sustainability',
        'keywords': [
            'sustainability', 'sustainable', 'circular economy', 'green economy',
            'esg', 'csr', 'corporate social responsibility',
            'sustainable development goals', 'sdg', 'eco-friendly',
            'resource efficiency', 'reuse', 'reduce', 'recycle', 'zero waste',
            'waste management', 'green business', 'green building',
            'low carbon', 'carbon neutral', 'green bond', 'sustainable finance',
            'responsible sourcing', 'life cycle assessment', 'agriculture',
            'farming', 'regenerative agriculture', 'organic farming',
            'sustainable food', 'supply chain', 'fair trade',
            'eco-tourism', 'green tourism', 'sustainable packaging',
            'circular fashion'
        ]
    },

    
    'climate_change': {
        'name': 'Climate Change',
        'keywords': [
            'climate change', 'global warming', 'greenhouse gas', 'greenhouse gases',
            'carbon emission', 'carbon emissions', 'co2', 'ch4', 'methane',
            'temperature rise', 'net zero', 'paris agreement', 'ipcc',
            'cop26', 'cop27', 'cop28', 'climate crisis', 'warming planet',
            'carbon footprint', 'emission reduction', 'carbon offset',
            'sea level rise', 'extreme weather', 'climate resilience',
            'fossil fuel', 'fossil fuels', 'oil and gas', 'pipeline', 'pipelines',
            'global heating', 'decarbonization', '1.5c', '2c', 'tipping point',
            'carbon budget', 'permafrost', 'el niño', 'el nino',
            'la niña', 'la nina', 'heatwave'
        ]
    },

    'biodiversity': {
        'name': 'Biodiversity',
        'keywords': [
            'biodiversity', 'endangered', 'endangered species', 'wildlife',
            'ecosystem', 'habitat loss', 'deforestation', 'reforestation',
            'conservation', 'extinction', 'protected areas', 'species loss',
            'nature restoration', 'marine life', 'ocean biodiversity', 'pollinator',
            'coral reef', 'habitat fragmentation', 'ecosystem services',
            'rewilding', 'invasive species', 'poaching', 'wildlife trade',
            'species reintroduction', 'biodiversity hotspot'
        ]
    },

    'renewable_energy': {
        'name': 'Renewable Energy',
        'keywords': [
            'renewable', 'renewables', 'solar', 'solar panel', 'solar farm',
            'wind', 'wind turbine', 'wind farm', 'windfarm',
            'hydro', 'hydropower', 'geothermal', 'biofuel', 'biomass',
            'energy transition', 'sustainable energy', 'green energy',
            'battery storage', 'ev', 'electric vehicle', 'ev charging',
            'charging station', 'hydrogen', 'offshore wind', 'pv', 'microgrid',
            'photovoltaic', 'photovoltaic cell', 'clean power',
            'grid integration', 'transmission line', 'green hydrogen',
            'fuel cell'
        ]
    },

    'pollution': {
        'name': 'Pollution',
        'keywords': [
            'pollution', 'air quality', 'air pollution', 'water pollution',
            'plastic waste', 'chemical pollution', 'microplastic', 'microplastics',
            'ocean pollution', 'smog', 'contaminants', 'toxic waste',
            'wastewater', 'industrial pollution', 'noise pollution',
            'soil contamination', 'particulate matter', 'pm2.5', 'pm10',
            'ozone', 'sulfur dioxide', 'pfas', 'forever chemicals',
            'heavy metal', 'lead', 'mercury', 'arsenic', 'chemical spill',
            'pesticide', 'herbicide', 'black carbon', 'soot',
            'nox', 'nitrogen oxide', 'sewage', 'e-waste'
        ]
    },

    'environmental_policy': {
        'name': 'Environmental Policy',
        'keywords': [
            'environmental policy', 'climate policy',
            'environmental regulation', 'environmental regulations',
            'environmental law', 'carbon pricing', 'carbon tax',
            'emissions trading', 'cap and trade', 'green deal',
            'government policy', 'legislation', 'policy initiative',
            'environmental standard', 'regulation', 'regulations', 'directive',
            'epa', 'eia', 'environmental impact assessment', 'kyoto protocol',
            'farm bill', 'subsidy', 'subsidies', 'tax credit',
            'appropriations', 'supreme court', 'climate finance',
            'trade agreement', 'infrastructure bill'
        ]
    },

    'environmental_tech': {
        'name': 'Environmental Technology',
        'keywords': [
            'environmental technology', 'green tech', 'clean tech', 'cleantech',
            'carbon capture', 'carbon capture technology', 'ccs',
            'direct air capture', 'dacs', 'environmental monitoring',
            'sensor', 'satellite', 'smart grid', 'smart city', 'waste treatment',
            'water treatment', 'eco-innovation', 'recycling technology',
            'waste-to-energy', 'bioremediation', 'ai', 'iot', 'drone',
            'smart irrigation', 'energy storage', 'grid modernization',
            'biotech', 'battery', 'solid-state battery', 'perovskite solar',
            'biochar', 'negative emissions', 'synthetic biology',
            'digital twin', 'blockchain energy', 'quantum sensing',
            'drone mapping'
        ]
    },

    'others': {
        'name': 'Others',
        'keywords': []  # no specific keywords
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


def fetch_all_news_from_redis():
    """
    Redis에서 모든 뉴스 항목을 가져와 파싱하고, 날짜 기준으로 정렬된 리스트를 반환합니다.
    이 함수는 이제 캐싱 작업에 의해서만 내부적으로 호출됩니다.
    """
    if redis_client is None:
        logger.error("fetch_all_news_from_redis: Redis client is not connected.")
        return []

    news_pattern = re.compile(r'^news-(\d{8})-(\d{3})$')
    try:
        keys = [key for key in redis_client.scan_iter('news-*') if news_pattern.match(key)]
    except Exception as e:
        logger.error(f"fetch_all_news_from_redis: Error scanning keys: {e}")
        return []

    if not keys:
        return []

    pipe = redis_client.pipeline()
    for key in keys:
        pipe.get(key)
    
    try:
        values = pipe.execute()
    except Exception as e:
        logger.error(f"fetch_all_news_from_redis: Error executing pipeline: {e}")
        return []

    news_list = []
    for key, value in zip(keys, values):
        if not value:
            continue
        try:
            news_item = json.loads(value)
            news_data = news_item.get('value', {})
            news_data['redis_key'] = key

            redis_category_name = news_data.get('category')
            is_valid = False
            if redis_category_name:
                for cat_info in CATEGORIES.values():
                    if redis_category_name == cat_info['name']:
                        is_valid = True
                        break
            
            if is_valid:
                news_data['category'] = redis_category_name
            else:
                news_data['category'] = categorize_news(news_data)

            m = news_pattern.match(key)
            if m:
                date_str = m.group(1)
                dt = datetime.strptime(date_str, "%Y%m%d").replace(tzinfo=timezone.utc)
                news_data['_parsed_published_date'] = dt
            else:
                news_data['_parsed_published_date'] = datetime.min.replace(tzinfo=timezone.utc)
            
            news_list.append(news_data)
        except Exception as e:
            logger.error(f"Error processing key {key}: {e}")

    news_list.sort(key=lambda x: x.get('_parsed_published_date', datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
    return news_list


def update_news_cache():
    """
    백그라운드 스케줄러에 의해 실행될 캐싱 함수.
    Redis에서 모든 뉴스를 가져와 처리한 후, 그 결과를 다시 Redis에 캐시로 저장합니다.
    """
    with app.app_context():
        logger.info("CACHE_UPDATE_JOB: Starting news cache update.")
        
        # 1. 모든 뉴스 데이터 가져오기
        all_news = fetch_all_news_from_redis()
        if not all_news:
            logger.warning("CACHE_UPDATE_JOB: No news items found to update cache.")
            return

        # 2. 메인 페이지 데이터 계산 및 캐싱
        categorized_news = {cat_id: [] for cat_id in CATEGORIES.keys()}
        for news in all_news:
            news_category_name = news.get('category', CATEGORIES['others']['name'])
            matched_cat_id = 'others'
            for cid, info in CATEGORIES.items():
                if news_category_name == info['name']:
                    matched_cat_id = cid
                    break
            categorized_news[matched_cat_id].append(news)
        
        sources_set = {n['source'] for n in all_news if n.get('source')}
        sorted_sources = sorted(sources_set)

        homepage_data = {
            'categorized_news_json': json.dumps(categorized_news, default=str),
            'sorted_sources_json': json.dumps(sorted_sources)
        }
        try:
            redis_client.hmset('cache:homepage', homepage_data)
            logger.info(f"CACHE_UPDATE_JOB: Successfully cached homepage data for {len(all_news)} items.")
        except Exception as e:
            logger.error(f"CACHE_UPDATE_JOB: Failed to cache homepage data: {e}")

        # 3. 트렌드 데이터 계산 및 캐싱 (주간/월간)
        for period in ['weekly', 'monthly']:
            now = datetime.now(timezone.utc)
            cutoff = now - timedelta(days=7 if period == 'weekly' else 30)
            
            recent_news = [item for item in all_news if item.get('_parsed_published_date') and item['_parsed_published_date'] >= cutoff]
            
            if not recent_news:
                trends_data = { 'top_keywords': [], 'source_distribution': [], 'category_distribution': [], 'country_distribution': [], 'sample_news': [] }
            else:
                # 키워드
                all_words = []
                for news in recent_news:
                    combined = f"{news.get('title','')} {news.get('summary','')}"
                    cleaned = re.sub(r'[^a-zA-Z\s]', '', combined).lower()
                    tokens = word_tokenize(cleaned)
                    filtered = [w for w in tokens if w.isalnum() and w not in stop_words and len(w) > 2]
                    all_words.extend(filtered)
                
                common_exclude = {'news','report','world','global','issue','new','says','company','government','country','state','million','billion','week','year','time','people','climate','energy','environmental'}
                filtered_keywords = [w for w in all_words if w not in common_exclude]
                keyword_counts = Counter(filtered_keywords)
                top_keywords = [{'keyword': k, 'count': c} for k, c in keyword_counts.most_common(20)]

                # 소스 분포
                source_counts = Counter(n['source'] for n in recent_news if 'source' in n)
                source_distribution = [{'source': k, 'count': c} for k, c in source_counts.most_common(10)]
                
                # 카테고리 분포
                category_counts = Counter(n.get('category', 'Others') for n in recent_news)
                category_distribution = [{'category': k, 'count': c} for k, c in category_counts.items()]

                # 국가 분포
                country_counts = Counter(n['country'] for n in recent_news if 'country' in n)
                country_distribution = [{'country': k, 'count': c} for k, c in country_counts.most_common(10)]

                sample_news = recent_news[:5]

                trends_data = {
                    'top_keywords': top_keywords,
                    'source_distribution': source_distribution,
                    'category_distribution': category_distribution,
                    'country_distribution': country_distribution,
                    'sample_news': sample_news
                }
            
            try:
                redis_client.set(f'cache:trends:{period}', json.dumps(trends_data, default=str))
                logger.info(f"CACHE_UPDATE_JOB: Successfully cached {period} trends data.")
            except Exception as e:
                logger.error(f"CACHE_UPDATE_JOB: Failed to cache {period} trends data: {e}")

@app.route('/')
def index():
    """메인 페이지. 캐시된 데이터를 사용합니다."""
    logger.info("index route: Attempting to fetch from cache.")
    
    current_category = request.args.get('category', '')
    current_source = request.args.get('source', '')
    current_sort = request.args.get('sort', 'newest')

    try:
        cached_data = redis_client.hgetall('cache:homepage')
        if cached_data:
            logger.info("index route: Cache hit. Loading data from Redis.")
            categorized_news = json.loads(cached_data['categorized_news_json'])
            sorted_sources = json.loads(cached_data['sorted_sources_json'])
            
            # 오래된 순 정렬 처리
            if current_sort == 'oldest':
                for cat in categorized_news:
                    categorized_news[cat].reverse()
        else:
            logger.warning("index route: Cache miss. No homepage data found. Returning empty.")
            categorized_news, sorted_sources = {}, []
            # 비상시: 캐시가 없을 경우, 동기적으로 캐시를 생성하고 다음 요청부터 사용하게 할 수도 있음
            # update_news_cache() 
            # return redirect(url_for('index'))

    except Exception as e:
        logger.error(f"index route: Error fetching from cache: {e}. Returning empty.")
        categorized_news, sorted_sources = {}, []

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
    """트렌드 리포트 API. 캐시된 데이터를 사용합니다."""
    logger.info("get_trends: API endpoint called. Attempting to fetch from cache.")
    period = request.args.get('period', 'weekly')
    if period not in ['weekly', 'monthly']:
        return jsonify({'error': 'Invalid period'}), 400

    try:
        cached_trends = redis_client.get(f'cache:trends:{period}')
        if cached_trends:
            logger.info(f"get_trends: Cache hit for '{period}' period.")
            return jsonify(json.loads(cached_trends))
        else:
            logger.warning(f"get_trends: Cache miss for '{period}' period. Returning empty.")
            # 비상시: 캐시가 없을 경우
            return jsonify({
                'top_keywords': [], 'source_distribution': [], 'category_distribution': [],
                'country_distribution': [], 'sample_news': []
            })
    except Exception as e:
        logger.error(f"get_trends: Error fetching from cache: {e}")
        return jsonify({'error': 'Failed to retrieve trend data'}), 500


@app.after_request
def set_security_headers(response):
    # 콘텐츠 유형 검사: 잘못된 MIME 타입 실행 방지
    response.headers["X-Content-Type-Options"] = "nosniff"
    
    # 클릭재킹 방지: iframe 삽입 차단
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    
    # 브라우저 XSS 필터 활성화
    response.headers["X-XSS-Protection"] = "1; mode=block"
    
    # Referrer 최소화 (선택)
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    
    # 콘텐츠 보안 정책 (선택 강화)
    # response.headers["Content-Security-Policy"] = "default-src 'self'; img-src * data:; script-src 'self'"

    return response

@app.route('/trends')
def trends_page():
    logger.info("trends_page: Rendering trends.html.")
    return render_template('trends.html')

@app.route('/ads.txt')
def ads_txt():
    return send_from_directory(app.root_path, 'ads.txt')

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

@app.route('/sitemap.xml')
def sitemap():
    return send_from_directory(app.root_path,  'sitemap.xml')

@app.route('/robots.txt')
def robots():
    return send_from_directory(app.root_path, 'robots.txt')


# report.py에서 정의한 Blueprint를 가져와서 등록
from report import reports_bp
app.register_blueprint(reports_bp)

# APScheduler 설정
scheduler = BackgroundScheduler(daemon=True)
# 앱 시작 시 즉시 한 번 실행하고, 그 후 30분 간격으로 실행
scheduler.add_job(update_news_cache, 'interval', minutes=30, next_run_time=datetime.now())
scheduler.start()

# 앱 종료 시 스케줄러가 안전하게 종료되도록 등록
atexit.register(lambda: scheduler.shutdown())

if __name__ == '__main__':
    app.run(debug=True, port=5000)
