# services.py

import json
import re
import logging
from datetime import datetime, timedelta, timezone
from collections import Counter
from nltk.tokenize import word_tokenize
from nltk.corpus import stopwords
import nltk
import redis

from extensions import redis_client

logger = logging.getLogger(__name__)

# NLTK 데이터가 로드되었는지 확인하고, 없으면 다운로드
try:
    nltk.data.find('corpora/stopwords')
    nltk.data.find('tokenizers/punkt')
    stop_words = set(stopwords.words('english'))
except Exception:
    logger.info("Downloading NLTK data (stopwords, punkt)...")
    nltk.download('stopwords')
    nltk.download('punkt')
    stop_words = set(stopwords.words('english'))

# 카테고리 정의
CATEGORIES = {
    'sustainability': { 'name': 'Sustainability', 'keywords': ['sustainability', 'sustainable', 'circular economy', 'green economy', 'esg', 'csr', 'corporate social responsibility', 'sustainable development goals', 'sdg', 'eco-friendly', 'resource efficiency', 'reuse', 'reduce', 'recycle', 'zero waste', 'waste management', 'green business', 'green building', 'low carbon', 'carbon neutral', 'green bond', 'sustainable finance', 'responsible sourcing', 'life cycle assessment', 'agriculture', 'farming', 'regenerative agriculture', 'organic farming', 'sustainable food', 'supply chain', 'fair trade', 'eco-tourism', 'green tourism', 'sustainable packaging', 'circular fashion'] },
    'climate_change': { 'name': 'Climate Change', 'keywords': ['climate change', 'global warming', 'greenhouse gas', 'greenhouse gases', 'carbon emission', 'carbon emissions', 'co2', 'ch4', 'methane', 'temperature rise', 'net zero', 'paris agreement', 'ipcc', 'cop26', 'cop27', 'cop28', 'climate crisis', 'warming planet', 'carbon footprint', 'emission reduction', 'carbon offset', 'sea level rise', 'extreme weather', 'climate resilience', 'fossil fuel', 'fossil fuels', 'oil and gas', 'pipeline', 'pipelines', 'global heating', 'decarbonization', '1.5c', '2c', 'tipping point', 'carbon budget', 'permafrost', 'el niño', 'el nino', 'la niña', 'la nina', 'heatwave'] },
    'biodiversity': { 'name': 'Biodiversity', 'keywords': ['biodiversity', 'endangered', 'endangered species', 'wildlife', 'ecosystem', 'habitat loss', 'deforestation', 'reforestation', 'conservation', 'extinction', 'protected areas', 'species loss', 'nature restoration', 'marine life', 'ocean biodiversity', 'pollinator', 'coral reef', 'habitat fragmentation', 'ecosystem services', 'rewilding', 'invasive species', 'poaching', 'wildlife trade', 'species reintroduction', 'biodiversity hotspot'] },
    'renewable_energy': { 'name': 'Renewable Energy', 'keywords': ['renewable', 'renewables', 'solar', 'solar panel', 'solar farm', 'wind', 'wind turbine', 'wind farm', 'windfarm', 'hydro', 'hydropower', 'geothermal', 'biofuel', 'biomass', 'energy transition', 'sustainable energy', 'green energy', 'battery storage', 'ev', 'electric vehicle', 'ev charging', 'charging station', 'hydrogen', 'offshore wind', 'pv', 'microgrid', 'photovoltaic', 'photovoltaic cell', 'clean power', 'grid integration', 'transmission line', 'green hydrogen', 'fuel cell'] },
    'pollution': { 'name': 'Pollution', 'keywords': ['pollution', 'air quality', 'air pollution', 'water pollution', 'plastic waste', 'chemical pollution', 'microplastic', 'microplastics', 'ocean pollution', 'smog', 'contaminants', 'toxic waste', 'wastewater', 'industrial pollution', 'noise pollution', 'soil contamination', 'particulate matter', 'pm2.5', 'pm10', 'ozone', 'sulfur dioxide', 'pfas', 'forever chemicals', 'heavy metal', 'lead', 'mercury', 'arsenic', 'chemical spill', 'pesticide', 'herbicide', 'black carbon', 'soot', 'nox', 'nitrogen oxide', 'sewage', 'e-waste'] },
    'environmental_policy': { 'name': 'Environmental Policy', 'keywords': ['environmental policy', 'climate policy', 'environmental regulation', 'environmental regulations', 'environmental law', 'carbon pricing', 'carbon tax', 'emissions trading', 'cap and trade', 'green deal', 'government policy', 'legislation', 'policy initiative', 'environmental standard', 'regulation', 'regulations', 'directive', 'epa', 'eia', 'environmental impact assessment', 'kyoto protocol', 'farm bill', 'subsidy', 'subsidies', 'tax credit', 'appropriations', 'supreme court', 'climate finance', 'trade agreement', 'infrastructure bill'] },
    'environmental_tech': { 'name': 'Environmental Technology', 'keywords': ['environmental technology', 'green tech', 'clean tech', 'cleantech', 'carbon capture', 'carbon capture technology', 'ccs', 'direct air capture', 'dacs', 'environmental monitoring', 'sensor', 'satellite', 'smart grid', 'smart city', 'waste treatment', 'water treatment', 'eco-innovation', 'recycling technology', 'waste-to-energy', 'bioremediation', 'ai', 'iot', 'drone', 'smart irrigation', 'energy storage', 'grid modernization', 'biotech', 'battery', 'solid-state battery', 'perovskite solar', 'biochar', 'negative emissions', 'synthetic biology', 'digital twin', 'blockchain energy', 'quantum sensing', 'drone mapping'] },
    'others': { 'name': 'Others', 'keywords': [] }
}

# 국가 추론을 위한 목록
COUNTRY_LIST = [
    'argentina', 'australia', 'brazil', 'canada', 'china', 'france', 'germany', 'india', 
    'indonesia', 'italy', 'japan', 'mexico', 'russia', 'saudi arabia', 'south africa', 
    'south korea', 'korea', 'turkey', 'uk', 'united kingdom', 'u.k.', 'britain',
    'us', 'u.s.', 'states', 'america', 'eu', 'european union'
]

def infer_country(news_item):
    """뉴스 제목과 요약에서 국가를 추론합니다."""
    text = (news_item.get('title', '') + ' ' + news_item.get('summary', '')).lower()
    for country in COUNTRY_LIST:
        # 단어 경계를 확인하여 'us'가 'russia'의 일부로 인식되는 것을 방지
        if re.search(r'\b' + re.escape(country) + r'\b', text):
            # 표준 이름으로 변환
            if country in ['us', 'u.s.', 'states', 'america']: return 'United States'
            if country in ['uk', 'u.k.', 'britain', 'united kingdom']: return 'United Kingdom'
            if country in ['south korea']: return 'Korea'
            return country.capitalize()
    return None

def categorize_news(news_item):
    title_lower = news_item.get('title', '').lower()
    summary_lower = news_item.get('summary', '').lower()
    combined_text = title_lower + " " + summary_lower
    for category_id, category_info in CATEGORIES.items():
        if category_id == 'others': continue
        for keyword in category_info['keywords']:
            if keyword in combined_text: return category_info['name']
    return CATEGORIES['others']['name']

def fetch_all_news_from_redis():
    if not redis_client: return []
    news_pattern = re.compile(r'^news-(\d{8})-(\d{3})$')
    keys = [key for key in redis_client.scan_iter('news-*') if news_pattern.match(key)]
    if not keys: return []
    
    pipe = redis_client.pipeline()
    for key in keys: pipe.get(key)
    values = pipe.execute()
    
    news_list = []
    for key, value in zip(keys, values):
        if not value: continue
        try:
            news_item = json.loads(value)
            news_data = news_item.get('value', {})
            news_data['redis_key'] = key
            
            # category와 country 필드를 news_data에 확실하게 포함시킵니다.
            news_data['country'] = news_item.get('value', {}).get('country')
            redis_category = news_data.get('category')
            is_valid = any(redis_category == cat_info['name'] for cat_info in CATEGORIES.values())
            news_data['category'] = redis_category if is_valid else categorize_news(news_data)

            m = news_pattern.match(key)
            if m:
                news_data['_parsed_published_date'] = datetime.strptime(m.group(1), "%Y%m%d").replace(tzinfo=timezone.utc)
            else:
                news_data['_parsed_published_date'] = datetime.min.replace(tzinfo=timezone.utc)
            news_list.append(news_data)
        except Exception as e:
            logger.error(f"Error processing key {key}: {e}")

    news_list.sort(key=lambda x: x.get('_parsed_published_date', datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
    return news_list

def update_news_cache():
    if not redis_client:
        logger.error("CACHE_UPDATE_JOB: Redis client not available.")
        return

    logger.info("CACHE_UPDATE_JOB: Starting news cache update.")
    all_news = fetch_all_news_from_redis()
    if not all_news:
        logger.warning("CACHE_UPDATE_JOB: No news items to update.")
        return

    # 메인 페이지 데이터
    categorized_news = {cat_id: [] for cat_id in CATEGORIES.keys()}
    for news in all_news:
        cat_name = news.get('category', 'Others')
        matched_id = next((cid for cid, info in CATEGORIES.items() if info['name'] == cat_name), 'others')
        categorized_news[matched_id].append(news)
    
    sorted_sources = sorted({n['source'] for n in all_news if n.get('source')})
    
    homepage_data = {
        'categorized_news_json': json.dumps(categorized_news, default=str),
        'sorted_sources_json': json.dumps(sorted_sources)
    }
    redis_client.hmset('cache:homepage', homepage_data)
    
    # 트렌드 데이터
    for period in ['weekly', 'monthly']:
        cutoff = datetime.now(timezone.utc) - timedelta(days=7 if period == 'weekly' else 30)
        recent_news = [item for item in all_news if item.get('_parsed_published_date', datetime.min.replace(tzinfo=timezone.utc)) >= cutoff]
        
        trends_data = { 'top_keywords': [], 'source_distribution': [], 'category_distribution': [], 'country_distribution': [], 'sample_news': [] }
        if recent_news:
            # 국가 정보가 없는 경우, 제목/요약에서 추론하여 채워넣기
            for news in recent_news:
                if not news.get('country'):
                    news['country'] = infer_country(news)

            all_words = []
            for news in recent_news:
                combined = f"{news.get('title','')} {news.get('summary','')}".lower()
                cleaned = re.sub(r'[^a-zA-Z\s]', '', combined)
                tokens = [w for w in word_tokenize(cleaned) if w.isalnum() and w not in stop_words and len(w) > 2]
                all_words.extend(tokens)
            
            common_exclude = {'news','report','world','global','issue','new','says','company','government','country','state','million','billion','week','year','time','people','climate','energy','environmental'}
            keyword_counts = Counter(w for w in all_words if w not in common_exclude)
            
            # 데이터 계산
            trends_data['top_keywords'] = [{'keyword': k, 'count': c} for k, c in keyword_counts.most_common(20)]
            trends_data['source_distribution'] = [{'source': s, 'count': c} for s, c in Counter(n['source'] for n in recent_news if 'source' in n).most_common(10)]
            trends_data['category_distribution'] = [{'category': cat, 'count': c} for cat, c in Counter(n.get('category', 'Others') for n in recent_news).items()]
            
            # 국가 분포 계산 로직 추가
            country_counts = Counter(n['country'] for n in recent_news if n.get('country'))
            trends_data['country_distribution'] = [{'country': country, 'count': count} for country, count in country_counts.most_common(10)]

            # 샘플 뉴스 제한을 제거하고, 기간 내 모든 뉴스를 전송하여 필터링 정확도 보장
            trends_data['sample_news'] = recent_news

        redis_client.set(f'cache:trends:{period}', json.dumps(trends_data, default=str))
    logger.info("CACHE_UPDATE_JOB: Finished news cache update.")

def get_cached_homepage_data():
    """캐시된 홈페이지 데이터를 가져옵니다."""
    if not redis_client: return None
    cached_data = redis_client.hgetall('cache:homepage')
    if not cached_data: return None
    
    return {
        'categorized_news': json.loads(cached_data['categorized_news_json']),
        'sorted_sources': json.loads(cached_data['sorted_sources_json'])
    }

def get_cached_trends_data(period='weekly'):
    """캐시된 트렌드 데이터를 가져옵니다."""
    if not redis_client: return None
    cached_trends = redis_client.get(f'cache:trends:{period}')
    if not cached_trends: return None
    
    return json.loads(cached_trends)

def update_reports_cache():
    """Reports 페이지에 필요한 데이터를 미리 계산하여 캐시에 저장합니다."""
    if not redis_client:
        logger.error("CACHE_REPORTS_JOB: Redis client not available.")
        return

    logger.info("CACHE_REPORTS_JOB: Starting reports cache update.")

    def _get_all_dates_from_redis(prefix):
        """지정된 prefix를 가진 모든 키에서 날짜를 추출합니다."""
        keys = sorted(redis_client.keys(f"{prefix}*"), reverse=True)
        dates = []
        for k in keys:
            date_part = k.decode('utf-8')[len(prefix):]
            if len(date_part) == 8 and date_part.isdigit():
                dates.append(f"{date_part[0:4]}-{date_part[4:6]}-{date_part[6:8]}")
        return dates

    def _load_report_content(key):
        """Redis에서 리포트 내용을 로드합니다."""
        raw = redis_client.get(key)
        if not raw: return None
        # 간단한 텍스트 처리만 가정합니다. 필요시 load_report_from_redis의 복잡한 로직 추가.
        return raw.decode('utf-8').replace('\\n', '<br>')

    daily_dates = _get_all_dates_from_redis("dailyreport-")
    weekly_dates = _get_all_dates_from_redis("weeklyreport-")
    monthly_dates = _get_all_dates_from_redis("monthlyreport-")

    latest_daily_report = None
    if daily_dates:
        latest_daily_report = _load_report_content(f"dailyreport-{daily_dates[0].replace('-', '')}")

    latest_weekly_report = None
    if weekly_dates:
        latest_weekly_report = _load_report_content(f"weeklyreport-{weekly_dates[0].replace('-', '')}")

    latest_monthly_report = None
    if monthly_dates:
        latest_monthly_report = _load_report_content(f"monthlyreport-{monthly_dates[0].replace('-', '')}")

    reports_page_data = {
        "daily_dates": json.dumps(daily_dates),
        "weekly_dates": json.dumps(weekly_dates),
        "monthly_dates": json.dumps(monthly_dates),
        "latest_daily_report": json.dumps(latest_daily_report),
        "latest_weekly_report": json.dumps(latest_weekly_report),
        "latest_monthly_report": json.dumps(latest_monthly_report)
    }
    
    redis_client.hmset('cache:reports_page', reports_page_data)
    logger.info("CACHE_REPORTS_JOB: Finished reports cache update.")

def get_cached_reports_data():
    """캐시된 Reports 페이지 데이터를 가져옵니다."""
    if not redis_client: return (None,) * 6
    
    try:
        cached_data = redis_client.hgetall('cache:reports_page')
    except redis.exceptions.ResponseError as e:
        if "WRONGTYPE" in str(e):
            logger.warning(
                "Deleting 'cache:reports_page' key due to WRONGTYPE error. "
                "The key will be regenerated by the next cache update."
            )
            redis_client.delete('cache:reports_page')
            return (None,) * 6
        else:
            logger.error(f"An unexpected Redis error occurred in get_cached_reports_data: {e}")
            raise

    if not cached_data: return (None,) * 6

    try:
        daily_dates = json.loads(cached_data.get(b'daily_dates', b'[]'))
        weekly_dates = json.loads(cached_data.get(b'weekly_dates', b'[]'))
        monthly_dates = json.loads(cached_data.get(b'monthly_dates', b'[]'))
        latest_daily_report = json.loads(cached_data.get(b'latest_daily_report', b'null'))
        latest_weekly_report = json.loads(cached_data.get(b'latest_weekly_report', b'null'))
        latest_monthly_report = json.loads(cached_data.get(b'latest_monthly_report', b'null'))
        return daily_dates, weekly_dates, monthly_dates, latest_daily_report, latest_weekly_report, latest_monthly_report
    except (json.JSONDecodeError, TypeError) as e:
        logger.error(f"Error decoding cached reports data: {e}")
        return (None,) * 6 