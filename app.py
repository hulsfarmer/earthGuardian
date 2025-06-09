from flask import Flask, send_from_directory, render_template
import logging
import os
import atexit

# 공용 확장 모듈과 서비스 로직을 가져옵니다.
from extensions import redis_client, scheduler
from services import update_news_cache, update_reports_cache

# 뷰(블루프린트)들을 가져옵니다.
from views.main import main_bp
from views.trends import trends_bp
from report import reports_bp # reports_bp로 이름이 변경되었습니다.

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

    return app

# Gunicorn이 찾을 수 있도록 전역 스코프에서 app 객체 생성
app = create_app()

if __name__ == '__main__':
    # 로컬에서 실행 시 스케줄러 시작
    if scheduler.state != 1: # Not running
        scheduler.start()
        # 애플리케이션 종료 시 스케줄러가 안전하게 종료되도록 등록
        atexit.register(lambda: scheduler.shutdown())
        app.logger.info("APScheduler started.")
    
    app.run(debug=True, host='0.0.0.0', port=5001)
