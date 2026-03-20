import logging
from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel

import shorts.trend_analyzer as trend_module
import shorts.video_creator as vc_module
from shorts.trend_analyzer import analyze_youtube_trends
from shorts.video_creator import create_shorts_video
from shorts.youtube_uploader import upload_to_youtube


class TopicRequest(BaseModel):
    topic: str
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
    """트렌드를 분석하고 주제를 선정한다. (함수 1 수동 트리거)"""
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
    """선정된 주제로 영상을 생성한다. (함수 2 수동 트리거)"""
    background_tasks.add_task(create_shorts_video)
    return {"status": "started", "message": "영상 생성이 백그라운드에서 시작되었습니다."}


@router.post("/run")
async def run_full_pipeline(background_tasks: BackgroundTasks):
    """영상 생성 → 업로드 파이프라인을 실행한다. (주제는 미리 설정 필요)"""
    if not trend_module.current_topic:
        return {"status": "error", "message": "주제가 설정되지 않았습니다. /analyze 또는 /topic으로 먼저 설정하세요."}
    background_tasks.add_task(_full_pipeline)
    return {"status": "started", "message": f"주제 '{trend_module.current_topic_detail}'로 영상 생성이 시작되었습니다."}


async def _full_pipeline():
    """파이프라인: 영상 생성 → 업로드."""
    try:
        video_path = await create_shorts_video()
        logger.info(f"영상 생성: {video_path}")

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
    except Exception as e:
        logger.error(f"파이프라인 실패: {e}", exc_info=True)
