from flask import Flask, send_from_directory, render_template, jsonify
import logging
import os
import atexit
import redis

# 공용 확장 모듈과 서비스 로직을 가져옵니다.
from extensions import redis_client, scheduler
from services import update_news_cache, update_reports_cache

# 뷰(블루프린트)들을 가져옵니다.
from views.main import main_bp
from views.trends import trends_bp
from report import reports_bp # reports_bp로 이름이 변경되었습니다.
from views.home import home_bp

def create_app():
    """
    Flask 애플리케이션을 생성하고 설정합니다.
    """
    app = Flask(__name__)

    # 로깅 설정
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    # 블루프린트 등록
    app.register_blueprint(main_bp)
    app.register_blueprint(trends_bp)
    app.register_blueprint(reports_bp) # url_prefix='/reports'가 이미 설정되어 있습니다.
    app.register_blueprint(home_bp)

    # 임시 진단용 라우트
    @app.route('/debug/redis-reports')
    def debug_redis_reports():
        logger = app.logger
        logger.info("Starting Redis report key debug check.")
        
        try:
            redis_url = os.getenv('REDIS_URL')
            if not redis_url:
                return jsonify({"error": "REDIS_URL not set."}), 500
            
            # bytes를 직접 다루기 위해 decode_responses=False로 설정
            client = redis.StrictRedis.from_url(redis_url, decode_responses=False)
            client.ping()
            logger.info("Successfully connected to Redis for debug check.")
        except Exception as e:
            logger.error(f"DEBUG: Could not connect to Redis: {e}")
            return jsonify({"error": f"Could not connect to Redis: {e}"}), 500
        
        found_keys = {}
        try:
            for prefix in ["dailyreport-", "weeklyreport-", "monthlyreport-"]:
                # 키(bytes)를 utf-8로 디코딩하여 JSON으로 반환
                keys = [k.decode('utf-8') for k in client.keys(f"{prefix}*")]
                found_keys[prefix] = {
                    "count": len(keys),
                    "keys": keys[:20] # 샘플로 20개만 표시
                }
            logger.info(f"DEBUG: Found keys: {found_keys}")
            return jsonify(found_keys)
        except Exception as e:
            logger.error(f"DEBUG: Error while scanning keys: {e}")
            return jsonify({"error": f"Error while scanning keys: {e}"}), 500

    # 애플리케이션 컨텍스트 내에서 초기 캐시 업데이트를 직접 실행
    with app.app_context():
        try:
            update_news_cache()
            update_reports_cache()
            app.logger.info("Initial cache updates completed successfully on startup.")
        except Exception as e:
            app.logger.error(f"Error during initial cache update on startup: {e}")

    # 백그라운드 캐시 업데이트 작업 스케줄링
    if redis_client:
        if not scheduler.get_job('update_news_cache'):
            scheduler.add_job(
                func=update_news_cache, 
                trigger='interval', 
                minutes=30, 
                id='update_news_cache',
                name='Periodic News Cache Update',
                replace_existing=True
            )
            app.logger.info("Scheduled news cache update job (every 30 minutes).")

        if not scheduler.get_job('update_reports_cache'):
            scheduler.add_job(
                func=update_reports_cache,
                trigger='interval',
                minutes=30,
                id='update_reports_cache',
                name='Periodic Reports Cache Update',
                replace_existing=True
            )
            app.logger.info("Scheduled reports cache update job (every 30 minutes).")

    # 정적 파일 라우트
    @app.route('/ads.txt')
    def ads_txt():
        return send_from_directory(app.static_folder, 'ads.txt')

    @app.route('/sitemap.xml')
    def sitemap():
        # 동적으로 생성하거나 정적 파일을 제공할 수 있습니다.
        # 여기서는 정적 파일을 가정합니다.
        return send_from_directory(os.path.join(app.root_path, 'static'), 'sitemap.xml')

    @app.route('/robots.txt')
    def robots():
        return send_from_directory(os.path.join(app.root_path, 'static'), 'robots.txt')
    
    # 간단한 정보 페이지들
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

    if not scheduler.running:
        scheduler.start()
        # 애플리케이션 종료 시 스케줄러가 안전하게 종료되도록 등록
        atexit.register(lambda: scheduler.shutdown())
        app.logger.info("APScheduler started.")

    return app

# Gunicorn이 찾을 수 있도록 전역 스코프에서 app 객체 생성
app = create_app()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)
