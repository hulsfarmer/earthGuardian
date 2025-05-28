# ───────────────────────────────────────────────────────────────
#  app.py  (Flask + Redis + Trend API)
# ───────────────────────────────────────────────────────────────
import os, time, logging, json, re
from datetime import datetime, timedelta
from collections import Counter

from flask import Flask, render_template, request, jsonify
from flask_caching import Cache
import feedparser, requests
from bs4 import BeautifulSoup
from dateutil import parser
import redis
import nltk
from nltk.tokenize import word_tokenize
from nltk.corpus import stopwords

# ── 기본 초기화 ────────────────────────────────────────────────
app   = Flask(__name__)
cache = Cache(app, config={
    "CACHE_TYPE"      : "redis",
    "CACHE_REDIS_URL" : os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    "CACHE_DEFAULT_TIMEOUT": 300
})
rds   = redis.StrictRedis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# nltk 데이터 1회만
for pkg in ("punkt", "stopwords"):
    try:
        nltk.data.find("tokenizers/"+pkg if pkg=="punkt" else "corpora/"+pkg)
    except LookupError:
        nltk.download(pkg)

# ── 카테고리 / 뉴스 피드 ─────────────────────────────────────
CATEGORIES = {
    "climate_change"   : {"name":"Climate Change", "keywords":["climate change","global warming","carbon"]},
    "biodiversity"     : {"name":"Biodiversity"   , "keywords":["biodiversity","wildlife","endangered"]},
    "renewable_energy" : {"name":"Renewable Energy","keywords":["solar","wind power","renewable"]},
    "pollution"        : {"name":"Pollution"      , "keywords":["pollution","plastic","air quality"]},
    "others"           : {"name":"Others"         , "keywords":[]},
}
NEWS_FEEDS = {
    "BBC Environment"       : "https://www.bbc.co.uk/news/science_and_environment/rss.xml",
    "The Guardian Env."     : "https://www.theguardian.com/uk/environment/rss",
    "Climate Home News"     : "https://www.climatechangenews.com/feed/",
    "Reuters Environment"   : "https://www.reutersagency.com/feed/?best-topics=environment&post_type=best",
    "EcoWatch"              : "https://www.ecowatch.com/rss",
}

# ── 헬퍼 ───────────────────────────────────────────────────────
def clean_html(text:str) -> str:
    return BeautifulSoup(text or "", "html.parser").get_text()

def categorize_news(item):
    tl = item["title"].lower()
    sm = item["summary"].lower()
    for cid, cfg in CATEGORIES.items():
        if cid=="others": continue
        if any(k in tl or k in sm for k in cfg["keywords"]):
            return cid
    return "others"

# ── 뉴스 크롤 & 캐시 (5분)──────────────────────────────────────
@cache.memoize(300)
def get_news():
    all_news, headers = [], {"User-Agent":"Mozilla/5.0"}
    for src, url in NEWS_FEEDS.items():
        try:
            res  = requests.get(url, headers=headers, timeout=10)
            feed = feedparser.parse(res.content)
            for e in feed.entries:
                pub_raw  = e.get("published") or e.get("updated","")
                try:
                    pub = parser.parse(pub_raw)
                except Exception:
                    pub = datetime.utcnow()
                all_news.append({
                    "title"    : e.title,
                    "link"     : e.link,
                    "summary"  : clean_html(e.get("summary") or e.get("description","")),
                    "published": pub.isoformat(),
                    "source"   : src,
                    "image_url": None,
                })
        except Exception as err:
            logger.warning(f"{src} fetch error: {err}")
        time.sleep(0.5)

    # 최신순 정렬 & 7일 이내만 유지
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    all_news = sorted([n for n in all_news if parser.parse(n["published"])>cutoff],
                      key=lambda x: x["published"], reverse=True)[:300]
    return all_news

# ── 트렌드 분석 함수 (원본)─────────────────────────────────────
def analyze_trends(news_items, period="weekly"):
    now = datetime.utcnow()
    start = now - timedelta(days=7 if period=="weekly" else 30)

    recent = [n for n in news_items if parser.parse(n["published"])>=start]
    if not recent:
        return {"period":period,"generated_at":now.isoformat(),"total_news":0,
                "top_keywords":[],"source_distribution":[],"category_distribution":[],
                "country_distribution":[],"sample_news":[]}

    # 키워드
    text = " ".join(n["title"]+" "+n["summary"] for n in recent).lower()
    words = [w for w in word_tokenize(text) if w.isalnum()
             and w not in set(stopwords.words("english")) and len(w)>2]
    kw   = Counter(words).most_common(20)

    src  = Counter(n["source"] for n in recent)
    cat  = Counter(categorize_news(n) for n in recent)

    # 국가 키워드 매칭
    country_kw = {"united states":["us","america","american"],
                  "china":["china","chinese"],
                  "india":["india","indian"],
                  "europe":["eu","europe"],
                  "japan":["japan","japanese"],
                  "south korea":["korea","korean"]}
    country = Counter()
    for n in recent:
        t=(n["title"]+" "+n["summary"]).lower()
        for c, ks in country_kw.items():
            if any(k in t for k in ks): country[c]+=1
    top_country = country.most_common(10)

    return {
        "period"               : period,
        "generated_at"         : now.isoformat(),
        "total_news"           : len(recent),
        "top_keywords"         : [{"keyword":k,"count":v} for k,v in kw],
        "source_distribution"  : [{"source":k,"count":v} for k,v in src.items()],
        "category_distribution": [{"category":k,"count":v} for k,v in cat.items()],
        "country_distribution" : [{"country":k,"count":v} for k,v in top_country],
        "sample_news"          : recent[:100],
    }

# ── ROUTES ────────────────────────────────────────────────────
@app.route("/")
def home():
    items = get_news()
    categorized = {cid:[] for cid in CATEGORIES}
    for n in items:
        categorized[categorize_news(n)].append(n)
    return render_template("index.html",
                           categorized_news=categorized,
                           categories=CATEGORIES,
                           sources=NEWS_FEEDS,
                           current_category="", current_source="", current_sort="newest")

@app.route("/api/trends")
def api_trends():
    period = request.args.get("period","weekly")
    if period not in ("weekly","monthly"):
        return jsonify({"error":"invalid period"}),400
    return jsonify(analyze_trends(get_news(), period))

@app.route("/trends")
def trends():       return render_template("trends.html")

@app.route("/reports")
def reports():      return render_template("reports.html",
                                          daily_keys=[], weekly_keys=[], monthly_keys=[])

# ── 실행 ──────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=True)
