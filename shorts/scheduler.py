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
        loop.run_until_complete(_daily_shorts_job())
    except Exception as e:
        logger.error(f"쇼츠 자동 생성 실패: {e}", exc_info=True)
    finally:
        loop.close()


async def _daily_shorts_job():
    """매일 실행: 기존 주제로 영상 생성 → 업로드. (주제는 수동 설정)"""
    from shorts.video_creator import create_shorts_video
    from shorts.youtube_uploader import upload_to_youtube
    import shorts.trend_analyzer as trend_module
    import shorts.video_creator as vc_module

    logger.info("=== 쇼츠 자동 생성 시작 ===")

    # 매일 새 밸런스게임 질문 선정 (topic은 유지, detail만 변경)
    from shorts.trend_analyzer import pick_daily_question
    question = await pick_daily_question()
    logger.info(f"오늘의 질문: {question}")

    video_path = await create_shorts_video()
    logger.info(f"영상 생성 완료: {video_path}")

    # 캐시된 스크립트 사용 (이중 생성 방지)
    script = vc_module.last_generated_script
    if not script:
        logger.error("스크립트 캐시가 없습니다")
        return

    result = await upload_to_youtube(
        video_path=video_path,
        title=script["title"],
        description=script["description"],
        tags=script["tags"],
    )
    logger.info(f"업로드 완료: {result['url']}")

    from shorts.video_creator import _save_episode
    _save_episode(script["title"], script["description"])

    _cleanup_temp_files()
    return result


def _cleanup_temp_files():
    """영상 생성 과정에서 만들어진 임시 파일을 정리한다."""
    patterns = ["shorts_narration_*", "shorts_bg_*", "shorts_fallback_*",
                "shorts_text_*", "shorts_output_*"]
    for pattern in patterns:
        for f in glob.glob(os.path.join(tempfile.gettempdir(), pattern)):
            try:
                os.remove(f)
            except OSError:
                pass


def start_scheduler():
    """매일 23:00 KST에 쇼츠를 생성/업로드하는 스케줄러를 시작한다."""
    scheduler.add_job(
        _run_daily_job,
        trigger=CronTrigger(hour=22, minute=0, timezone="Asia/Seoul"),
        id="daily_shorts",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("쇼츠 스케줄러 시작 (매일 22:00 KST)")


def stop_scheduler():
    """스케줄러를 종료한다."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("쇼츠 스케줄러 종료")
