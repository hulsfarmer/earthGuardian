from flask import Flask, render_template, request, jsonify
import feedparser
from datetime import datetime, timedelta
import logging
import requests
from bs4 import BeautifulSoup
import time
from dateutil import parser
from flask_caching import Cache
from collections import Counter
import json
import re
from nltk.tokenize import word_tokenize
from nltk.corpus import stopwords
import nltk
from celery import Celery
from apscheduler.schedulers.background import BackgroundScheduler
import os

app = Flask(__name__)

# Redis 캐시 설정
cache = Cache(app, config={
    'CACHE_TYPE': 'redis',
    'CACHE_REDIS_URL': os.getenv('REDIS_URL', 'redis://localhost:6379/0'),
    'CACHE_DEFAULT_TIMEOUT': 300  # 5분
})

# Celery 설정
celery = Celery('tasks', broker=os.environ.get('REDIS_URL'))
celery.conf.broker_pool_limit = 2  # 연결 풀 제한 (기본값 10)

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

# 뉴스 피드 설정
NEWS_FEEDS = {
    'BBC Environment': 'https://www.bbc.co.uk/news/science_and_environment/rss.xml',
    'The Guardian Environment': 'https://www.theguardian.com/uk/environment/rss',
    'Climate Home News': 'https://www.climatechangenews.com/feed/',
    'Reuters Environment': 'https://www.reutersagency.com/feed/?best-topics=environment&post_type=best',
    'EcoWatch': 'https://www.ecowatch.com/rss'
}

# NLTK 데이터 다운로드
try:
    nltk.data.find('tokenizers/punkt')
except LookupError:
    nltk.download('punkt')
try:
    nltk.data.find('corpora/stopwords')
except LookupError:
    nltk.download('stopwords')

def clean_html(html_content):
    """HTML 컨텐츠에서 텍스트만 추출"""
    if not html_content:
        return ""
    soup = BeautifulSoup(html_content, 'html.parser')
    return soup.get_text()

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

@cache.memoize(timeout=300)  # 5분 동안 캐시
def get_news():
    all_news = []
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    # 캐시된 뉴스 가져오기
    cached_news = cache.get('news_data') or []
    latest_published = None
    if cached_news:
        try:
            latest_published = max(parser.parse(item['published']) for item in cached_news)
        except:
            pass

    for source, feed_url in NEWS_FEEDS.items():
        try:
            logger.info(f"Fetching news from {source}")
            response = requests.get(feed_url, headers=headers, timeout=10)
            response.raise_for_status()
            
            feed = feedparser.parse(response.content)
            
            if not feed.entries:
                logger.warning(f"No entries found in feed from {source}")
                continue
                
            for entry in feed.entries:
                try:
                    # 이미지 URL 추출
                    image_url = None
                    if 'media_content' in entry:
                        for media in entry.media_content:
                            if 'url' in media:
                                image_url = media['url']
                                break
                    elif 'links' in entry:
                        for link in entry.links:
                            if link.get('type', '').startswith('image/'):
                                image_url = link['href']
                                break

                    # 날짜 파싱
                    published = entry.get('published', '')
                    try:
                        published_date = parser.parse(published)
                        # 캐시된 최신 뉴스보다 이전의 뉴스는 건너뛰기
                        if latest_published and published_date <= latest_published:
                            continue
                        published = published_date.strftime('%Y-%m-%d %H:%M')
                    except:
                        try:
                            published_date = datetime.strptime(published, '%Y-%m-%d %H:%M:%S')
                            if latest_published and published_date <= latest_published:
                                continue
                            published = published_date.strftime('%Y-%m-%d %H:%M')
                        except:
                            published = datetime.now().strftime('%Y-%m-%d %H:%M')

                    # HTML 태그 제거
                    summary = clean_html(entry.get('summary', ''))
                    if not summary and 'description' in entry:
                        summary = clean_html(entry.description)

                    news_item = {
                        'title': entry.title,
                        'link': entry.link,
                        'summary': summary,
                        'published': published,
                        'source': source,
                        'image_url': image_url
                    }
                    all_news.append(news_item)
                    logger.info(f"Added news: {news_item['title']}")
                    
                except Exception as e:
                    logger.error(f"Error processing entry from {source}: {str(e)}")
                    continue
                    
            # 피드 간 딜레이 추가
            time.sleep(1)
                
        except Exception as e:
            logger.error(f"Error fetching feed from {source}: {str(e)}")
            continue
    
    # 새로운 뉴스와 캐시된 뉴스 합치기
    if cached_news:
        all_news.extend(cached_news)
    
    # 날짜순으로 정렬
    all_news.sort(key=lambda x: parser.parse(x['published']), reverse=True)

    # 오래된 뉴스(7일 이전) 필터링
    cutoff_date = datetime.now() - timedelta(days=7)
    all_news = [item for item in all_news if parser.parse(item['published']) > cutoff_date]

    # 최대 개수 제한
    MAX_NEWS_COUNT = 300
    all_news = all_news[:MAX_NEWS_COUNT]
    
    # 캐시 업데이트
    cache.set('news_data', all_news)
            
    return all_news

@app.route('/')
def index():
    # 필터링 파라미터 가져오기
    category_filter = request.args.get('category', '')
    source_filter = request.args.get('source', '')
    sort_order = request.args.get('sort', 'newest')

    # 캐시된 뉴스 가져오기
    news_items = get_news()

    # 필터링 적용
    if category_filter:
        news_items = [item for item in news_items if categorize_news(item) == category_filter]
    
    if source_filter:
        news_items = [item for item in news_items if item['source'] == source_filter]

    # 정렬
    if sort_order == 'newest':
        news_items.sort(key=lambda x: parser.parse(x['published']), reverse=True)
    else:
        news_items.sort(key=lambda x: parser.parse(x['published']))

    # 카테고리별로 뉴스 분류
    categorized_news = {category_id: [] for category_id in CATEGORIES.keys()}
    for news in news_items:
        category = categorize_news(news)
        categorized_news[category].append(news)

    return render_template('index.html',
                         categorized_news=categorized_news,
                         categories=CATEGORIES,
                         sources=NEWS_FEEDS.keys(),
                         current_category=category_filter,
                         current_source=source_filter,
                         current_sort=sort_order)

# 캐시 초기화 엔드포인트 (필요시 수동으로 호출)
@app.route('/clear-cache')
def clear_cache():
    cache.clear()
    return 'Cache cleared'

def analyze_trends(news_items, period='weekly'):
    """뉴스 데이터를 분석하여 트렌드를 추출"""
    logger.info(f"Starting trend analysis for period: {period}")
    
    try:
        # 기간 설정
        now = datetime.now()
        if period == 'weekly':
            start_date = now - timedelta(days=7)
        else:  # monthly
            start_date = now - timedelta(days=30)
        
        logger.info(f"Filtering news from {start_date} to {now}")
        
        # 기간 내 뉴스 필터링
        recent_news = []
        for item in news_items:
            try:
                published_date = parser.parse(item['published'])
                if published_date >= start_date:
                    recent_news.append(item)
            except Exception as e:
                logger.warning(f"Error parsing date for news item: {str(e)}")
                continue
        
        logger.info(f"Found {len(recent_news)} news items in the period")

        # 최근 뉴스 개수 제한
        if len(recent_news) > 300:
            recent_news = recent_news[:300]
        
        if not recent_news:
            logger.warning("No news items found in the specified period")
            return {
                'period': period,
                'generated_at': now.strftime('%Y-%m-%d %H:%M:%S'),
                'total_news': 0,
                'top_keywords': [],
                'source_distribution': [],
                'category_distribution': [],
                'country_distribution': [],
                'sample_news': []
            }
        
        # 키워드 추출 및 분석
        all_text = ' '.join([item['title'] + ' ' + item['summary'] for item in recent_news])
        words = word_tokenize(all_text.lower())
        stop_words = set(stopwords.words('english'))
        words = [word for word in words if word.isalnum() and word not in stop_words and len(word) > 2]
        
        # 키워드 빈도 분석
        keyword_freq = Counter(words).most_common(20)
        logger.info(f"Top keywords: {keyword_freq}")
        
        # 출처별 뉴스 수
        source_stats = Counter(item['source'] for item in recent_news)
        logger.info(f"Source distribution: {source_stats}")
        
        # 카테고리별 뉴스 수
        category_stats = Counter(categorize_news(item) for item in recent_news)
        logger.info(f"Category distribution: {category_stats}")

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
                # 정확한 국가명 매칭
                if any(keyword in text for keyword in keywords):
                    country_mentions[country] += 1

        # 상위 10개 국가만 선택
        country_stats = country_mentions.most_common(10)
        logger.info(f"Country distribution: {country_stats}")
        
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
        
        logger.info("Trend analysis completed successfully")
        return report
        
    except Exception as e:
        logger.error(f"Error in trend analysis: {str(e)}")
        return {
            'period': period,
            'generated_at': now.strftime('%Y-%m-%d %H:%M:%S'),
            'error': str(e),
            'total_news': 0,
            'top_keywords': [],
            'source_distribution': [],
            'category_distribution': [],
            'country_distribution': [],
            'sample_news': []
        }

@celery.task
def collect_and_analyze_news():
    """뉴스 수집 및 분석을 비동기로 수행"""
    try:
        logger.info("Starting news collection and analysis")
        news_items = get_news()
        
        # 주간/월간 트렌드 분석
        weekly_trends = analyze_trends(news_items, 'weekly')
        monthly_trends = analyze_trends(news_items, 'monthly')
        
        # 캐시 업데이트
        cache.set('weekly_trends', weekly_trends)
        cache.set('monthly_trends', monthly_trends)
        
        logger.info("News collection and analysis completed")
    except Exception as e:
        logger.error(f"Error in collect_and_analyze_news: {str(e)}")

# 스케줄러 설정
scheduler = BackgroundScheduler()
scheduler.add_job(collect_and_analyze_news, 'interval', minutes=5)
scheduler.start()

@app.route('/api/trends')
@cache.cached(timeout=300, query_string=True)  # 5분 캐싱, 쿼리 파라미터 고려
def get_trends():
    """트렌드 리포트 API 엔드포인트"""
    period = request.args.get('period', 'weekly')
    if period not in ['weekly', 'monthly']:
        return jsonify({'error': 'Invalid period'}), 400
    
    try:
        # 캐시된 트렌드 데이터 확인
        cached_trends = cache.get(f'{period}_trends')
        if cached_trends:
            logger.info(f"Returning cached {period} trends")
            return jsonify(cached_trends)
        
        # 캐시가 없는 경우 새로운 분석 수행
        logger.info(f"Fetching news for {period} trends analysis")
        news_items = get_news()
        report = analyze_trends(news_items, period)
        
        if 'error' in report:
            return jsonify(report), 500
            
        # 결과 캐싱
        cache.set(f'{period}_trends', report)
        return jsonify(report)
    except Exception as e:
        logger.error(f"Error generating trends report: {str(e)}")
        return jsonify({'error': 'Failed to generate report'}), 500

@app.route('/trends')
def trends_page():
    """트렌드 리포트 페이지"""
    return render_template('trends.html')

if __name__ == '__main__':
    # NLTK 데이터 다운로드
    try:
        nltk.data.find('tokenizers/punkt')
    except LookupError:
        nltk.download('punkt')
    try:
        nltk.data.find('corpora/stopwords')
    except LookupError:
        nltk.download('stopwords')
    
    app.run(debug=True, port=5050) 
