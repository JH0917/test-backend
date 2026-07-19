import logging
from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel

import shorts.trend_analyzer as trend_module
import shorts.video_creator as vc_module
from shorts.trend_analyzer import analyze_youtube_trends
from shorts.video_creator import create_shorts_video
from shorts.youtube_uploader import upload_to_youtube
from shorts.video_creator import _save_episode


class TopicRequest(BaseModel):
    topic: str = "역사 IF"
    detail: str

logger = logging.getLogger("shorts.router")

router = APIRouter(prefix="/api_ljh/shorts")


@router.get("/status")
def get_status():
    """현재 선정된 주제와 상태를 확인한다."""
    return {
        "current_topic": trend_module.current_topic,
        "current_topic_detail": trend_module.current_topic_detail,
    }


@router.post("/analyze")
async def run_analyze():
    """주제를 선정한다."""
    topic = await analyze_youtube_trends()
    return {"status": "success", "topic": topic}


@router.post("/topic")
def set_topic(req: TopicRequest):
    """주제를 직접 수동 설정한다."""
    trend_module.current_topic = req.topic
    trend_module.current_topic_detail = req.detail
    return {
        "status": "success",
        "current_topic": req.topic,
        "current_topic_detail": req.detail,
    }


@router.post("/create")
async def run_create(background_tasks: BackgroundTasks):
    """선정된 주제로 영상을 생성한다."""
    background_tasks.add_task(_create_pipeline)
    return {"status": "started", "message": "영상 생성이 백그라운드에서 시작되었습니다."}


@router.post("/run")
async def run_full_pipeline(background_tasks: BackgroundTasks):
    """주제 선정 → 영상 생성 → 업로드 파이프라인을 실행한다."""
    background_tasks.add_task(_full_pipeline)
    return {"status": "started", "message": "역사 IF 영상 생성이 시작되었습니다."}


async def _create_pipeline():
    """파이프라인: 영상 생성 → 업로드 → 히스토리 저장 → 정리."""
    try:
        import os
        import shorts.trend_analyzer as trend_module
        from shorts.scheduler import _cleanup_temp_files

        video_path = await create_shorts_video()
        logger.info(f"영상 생성: {video_path}")

        # 영상 파일 검증 (100KB 미만이면 비정상)
        if not os.path.exists(video_path) or os.path.getsize(video_path) < 100_000:
            logger.error(f"영상 파일 비정상 (크기: {os.path.getsize(video_path) if os.path.exists(video_path) else 0}). 업로드 중단.")
            _cleanup_temp_files()
            return

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
        logger.info(f"업로드 완료: {result}")
        _save_episode(script["title"], script["description"], trend_module.current_topic_detail)
        _cleanup_temp_files()
    except Exception as e:
        logger.error(f"파이프라인 실패 (업로드 안 함): {e}", exc_info=True)


async def _full_pipeline():
    """파이프라인: 주제 선정 → 영상 생성 → 업로드 → 히스토리 저장 → 정리."""
    try:
        import os
        from shorts.trend_analyzer import pick_daily_question
        import shorts.trend_analyzer as trend_module
        from shorts.scheduler import _cleanup_temp_files

        topic = await pick_daily_question()
        logger.info(f"오늘의 주제: {topic.get('detail', topic)}")

        video_path = await create_shorts_video()
        logger.info(f"영상 생성: {video_path}")

        # 영상 파일 검증 (100KB 미만이면 비정상)
        if not os.path.exists(video_path) or os.path.getsize(video_path) < 100_000:
            logger.error(f"영상 파일 비정상 (크기: {os.path.getsize(video_path) if os.path.exists(video_path) else 0}). 업로드 중단.")
            _cleanup_temp_files()
            return

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
        logger.info(f"업로드 완료: {result}")
        _save_episode(script["title"], script["description"], trend_module.current_topic_detail)
        _cleanup_temp_files()
    except Exception as e:
        logger.error(f"파이프라인 실패 (업로드 안 함): {e}", exc_info=True)
