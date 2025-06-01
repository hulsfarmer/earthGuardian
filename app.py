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
        logger.error(f"Failed to download NLTK resources: {download_e}")


# 카테고리 키워드 정의 - 더 다양한 키워드 포함
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
redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)

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
                return assigned_category
    
    return assigned_category

def fetch_news_from_redis():
    """Redis에서 모든 뉴스 항목을 가져와 정렬하고, Redis의 category 정보가 있으면 우선 사용"""
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
                
                # Redis에 'category' 필드가 이미 있거나, 빈 값이 아니라면 그대로 사용
                # 그렇지 않다면 categorize_news 함수를 통해 분류
                if 'category' not in news_data or not news_data['category']:
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
    """메인 페이지 라우트"""
    news_items = fetch_news_from_redis()

    categorized_news = {category_id: [] for category_id in CATEGORIES.keys()}
    
    for news in news_items:
        for category_id, category_info in CATEGORIES.items():
            if news.get('category') == category_info['name']:
                categorized_news[category_id].append(news)
                break 
    
    for cat_id, news_list in categorized_news.items():
        logger.info(f"Category '{CATEGORIES[cat_id]['name']}': {len(news_list)} news items")

    return render_template('index.html',
                         categorized_news=categorized_news,
                         categories=CATEGORIES,
                         sources=sorted(list(set(item.get('source', 'Unknown') for item in news_items if item.get('source')))), 
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
        news_items = fetch_news_from_redis()
        
        now = datetime.now(timezone.utc)
        if period == 'weekly':
            cutoff = now - timedelta(days=7)
        else:
            cutoff = now - timedelta(days=30)
        
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
                continue
                
        # --- 실제 트렌드 데이터 계산 ---
        
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
                logger.error(f"Error tokenizing/filtering words for news item: {e}")
                continue
        
        common_exclude_keywords = set(['news', 'report', 'world', 'global', 'issue', 'new', 'says', 'company', 'government', 'country', 'state', 'million', 'billion', 'week', 'year', 'time', 'people'])
        filtered_keywords = [word for word in all_words if word not in common_exclude_keywords]

        keyword_counts = Counter(filtered_keywords)
        top_keywords = [{'keyword': keyword, 'count': count} for keyword, count in keyword_counts.most_common(20)]

        # 2. 출처 분포 계산
        source_counts = Counter(news.get('source', 'Unknown') for news in recent_news)
        source_distribution = [{'source': source, 'count': count} for source, count in source_counts.most_common()]

        # 3. 카테고리 분포 계산
        category_counts_dict = {CATEGORIES[c_id]['name']: 0 for c_id in CATEGORIES} 
        
        for news in recent_news:
            cat_name = news.get('category', CATEGORIES['others']['name'])
            if cat_name in category_counts_dict: 
                category_counts_dict[cat_name] += 1
            else: 
                category_counts_dict[CATEGORIES['others']['name']] += 1

        category_distribution = [{'category': cat, 'count': count} for cat, count in category_counts_dict.items()]
        category_distribution.sort(key=lambda x: x['count'], reverse=True) 
        
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

        return jsonify({
            'top_keywords': top_keywords,
            'source_distribution': source_distribution,
            'category_distribution': category_distribution, 
            'country_distribution': country_distribution,
            'sample_news': recent_news
        })

    except Exception as e:
        logger.error(f"Error generating trends: {str(e)}")
        return jsonify({'error': 'Failed to generate trends'}), 500

@app.route('/trends')
def trends_page():
    return render_template('trends.html')

if __name__ == '__main__':
    app.run(debug=True, port=5000)
