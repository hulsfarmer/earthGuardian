# services.py

import json
import re
import logging
from datetime import datetime, timedelta, timezone
from collections import Counter
from nltk.tokenize import word_tokenize
from nltk.corpus import stopwords
import nltk

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

            # 샘플 뉴스 개수를 50개로 확대하여 필터링 정확도 향상
            trends_data['sample_news'] = recent_news[:50]

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