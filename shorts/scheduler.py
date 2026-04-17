import os
import glob
import asyncio
import logging
import tempfile
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger("shorts.scheduler")

scheduler = BackgroundScheduler()


def _run_daily_job():
    """동기 컨텍스트에서 비동기 작업을 실행하는 래퍼."""
    loop = asyncio.new_event_loop()
    try:
        from shorts.router import _full_pipeline
        loop.run_until_complete(_full_pipeline())
    except Exception as e:
        logger.error(f"쇼츠 자동 생성 실패: {e}", exc_info=True)
    finally:
        loop.close()


def _cleanup_temp_files():
    """영상 생성 과정에서 만들어진 임시 파일을 정리한다."""
    patterns = ["shorts_narration_*", "shorts_bg_*", "shorts_fallback_*",
                "shorts_text_*", "shorts_output_*", "shorts_runway_*",
                "shorts_dalle_*"]
    for pattern in patterns:
        for f in glob.glob(os.path.join(tempfile.gettempdir(), pattern)):
            try:
                os.remove(f)
            except OSError:
                pass


def start_scheduler():
    """매일 12:00, 18:00 KST에 쇼츠를 생성/업로드하는 스케줄러를 시작한다."""
    scheduler.add_job(
        _run_daily_job,
        trigger=CronTrigger(hour=12, minute=0, timezone="Asia/Seoul"),
        id="daily_shorts_lunch",
        replace_existing=True,
    )
    scheduler.add_job(
        _run_daily_job,
        trigger=CronTrigger(hour=18, minute=0, timezone="Asia/Seoul"),
        id="daily_shorts_evening",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("쇼츠 스케줄러 시작 (매일 12:00, 18:00 KST)")


def stop_scheduler():
    """스케줄러를 종료한다."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("쇼츠 스케줄러 종료")
