import os
import json
import asyncio
import random
import tempfile
import time
import uuid
import httpx
import anthropic
from moviepy import (
    VideoFileClip,
    vfx,
)
import moviepy.audio.fx as afx
from moviepy.audio.AudioClip import CompositeAudioClip
from moviepy import AudioFileClip, CompositeVideoClip
from shorts.audio_assets import get_or_generate_sfx, generate_bgm_loop

import logging

import shorts.trend_analyzer as trend_module
from shorts.trend_analyzer import _parse_json_response

logger = logging.getLogger("shorts.video_creator")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "")
EPISODE_HISTORY_PATH = os.getenv("EPISODE_HISTORY_PATH", "/app/episode_history.json")

WIDTH = 720
HEIGHT = 1280

# 캐시: 마지막으로 생성된 스크립트 (업로드 시 재사용)
last_generated_script = None


def _load_episode_history() -> list[dict]:
    """에피소드 히스토리를 로드한다."""
    if os.path.exists(EPISODE_HISTORY_PATH):
        try:
            with open(EPISODE_HISTORY_PATH, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError):
            return []
    return []


def _save_episode(title: str, description: str, topic: str = ""):
    """생성된 에피소드를 히스토리에 저장한다."""
    history = _load_episode_history()
    entry = {"title": title, "description": description, "topic": topic}
    history.append(entry)
    with open(EPISODE_HISTORY_PATH, "w") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


async def create_shorts_video() -> str:
    """역사 IF 쇼츠 영상을 생성한다. 대사 없이 비주얼+SFX/BGM만."""
    global last_generated_script

    if not trend_module.current_topic_detail:
        raise ValueError("주제가 설정되지 않았습니다. analyze 먼저 실행하세요.")

    script = await _generate_script(trend_module.current_topic_detail)
    last_generated_script = script

    video_paths = await _generate_scene_videos(script["scenes"])

    # 전체 실패 시 중단
    success_count = sum(1 for p in video_paths if p is not None)
    if success_count == 0:
        raise RuntimeError("MiniMax 영상 전체 실패 — 영상 생성을 중단합니다.")

    video_path = await _compose_video(script, video_paths)
    return video_path


async def _generate_script(topic_detail: str) -> dict:
    """Claude API로 장면 프롬프트를 생성한다. 대사 없이 비주얼 시나리오만."""
    history = _load_episode_history()
    episode_number = len(history) + 1
    last_title = history[-1]["title"] if history else "없음"

    # 히스토리에서 최근 사용된 주제들
    recent_topics = [ep.get("topic", "") for ep in history[-20:]]

    prompt = f"""당신은 유튜브 쇼츠 "역사 IF" 영상 전문가입니다.
"만약 ~했다면?" 이라는 가정으로, AI 실사급 영상만으로 스토리를 전달합니다.
대사/나레이션/자막 없이, 영상만 보고도 "뭐야 이게?!" 하고 끝까지 보게 만들어야 합니다.

⚠️ 주제: {topic_detail}
⚠️ 에피소드: #{episode_number}
⚠️ 직전 제목: "{last_title}" — 다른 느낌!

## 최근 사용된 주제 (중복 방지)
{chr(10).join(recent_topics[-10:]) if recent_topics else "없음"}

## 핵심 원칙
1. 첫 1초에 "뭐야?!" — 현실에서 절대 볼 수 없는 충격적 비주얼
2. 대사 없이 영상만으로 스토리 전달 — 전 세계 누구나 이해
3. 매 장면이 점점 더 극적으로 — 스케일 확대
4. 마지막 장면에서 반전 또는 클라이맥스

## 5컷 구조 (정확히 5장면, 각 6초)
1. 🔥 훅: 현실과 비현실의 충돌 (예: 현대 도시에 공룡이 걸어다님)
2. 📈 전개: 상황이 확대됨 (사람들의 반응, 세계의 변화)
3. 💥 갈등: 예상치 못한 문제 발생 (충돌, 혼란, 위기)
4. 🌋 클라이맥스: 가장 극적인 장면 (폭발, 대규모 변화)
5. 🔄 엔딩: 반전 또는 여운 (마지막 숏으로 루프 유도)

## 영상 프롬프트 가이드 (MiniMax T2V용)
- 영어로 작성
- 실사 영화 퀄리티: "photorealistic, cinematic lighting, 4K, movie quality"
- 카메라 워크 반드시 포함: "slow pan", "dolly zoom", "aerial shot", "close-up tracking"
- 구체적 디테일: 시간대, 날씨, 인물 표정, 배경 오브젝트
- 동작 반드시 포함: 걷기, 달리기, 날기, 폭발 등
- 금지: 텍스트, 자막, UI, 워터마크 언급

## 제목 규칙 (영어+한국어 병행, 글로벌 타겟)
- 영어 제목이 메인, 한국어 부제
- 짧고 충격적: "What if dinosaurs never went extinct?"
- 30자 이내 (영어 기준)

다음 JSON으로만 응답:
{{
    "title": "영어 제목 | 한국어 부제",
    "description": "영어 설명 (80자 이내)",
    "tags": ["whatif", "history", "ai", "shorts", ...],
    "scenes": [
        {{
            "prompt": "Photorealistic cinematic ... (English, 상세한 영상 프롬프트, 최소 50단어)",
            "duration": 6
        }}
    ]
}}

⚠️ 정확히 5개 장면! 각 장면 prompt는 최소 50단어로 상세하게!"""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = await asyncio.to_thread(
        client.messages.create,
        model="claude-sonnet-4-6",
        max_tokens=2500,
        messages=[{"role": "user", "content": prompt}],
    )

    script = _parse_json_response(message.content[0].text)

    # 에피소드 번호 강제 삽입
    if f"#{episode_number}" not in script["title"]:
        script["title"] = f"#{episode_number} {script['title']}"

    # 검증
    scene_count = len(script.get("scenes", []))
    if scene_count != 5:
        logger.warning(f"장면 수 {scene_count}개 (기대: 5개)")
    logger.info(f"생성된 제목: {script.get('title')}")

    return script


async def _generate_single_video(prompt: str, run_id: str, index: int) -> str | None:
    """MiniMax API로 T2V 영상 1개를 생성한다."""
    headers = {
        "Authorization": f"Bearer {MINIMAX_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "T2V-01",
        "prompt": prompt,
        "duration": 6,
        "resolution": "720P",
        "prompt_optimizer": True,
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.minimax.io/v1/video_generation",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

            if "task_id" not in data:
                logger.error(f"MiniMax 장면 {index} task_id 없음: {data}")
                return None

            task_id = data["task_id"]
            logger.info(f"MiniMax 장면 {index} 작업 시작: {task_id}")

        # Polling (최대 5분)
        poll_start = time.monotonic()
        async with httpx.AsyncClient(timeout=30) as client:
            while True:
                if time.monotonic() - poll_start > 300:
                    logger.error(f"MiniMax 장면 {index} 타임아웃 (300초)")
                    return None

                resp = await client.get(
                    f"https://api.minimax.io/v1/query/video_generation?task_id={task_id}",
                    headers={"Authorization": f"Bearer {MINIMAX_API_KEY}"},
                )
                result = resp.json()
                status = result.get("status", "")

                if status == "Success":
                    file_id = result["file_id"]
                    break
                elif status == "Fail":
                    logger.error(f"MiniMax 장면 {index} 실패: {result}")
                    return None
                else:
                    await asyncio.sleep(10)

        # 다운로드 URL 획득
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"https://api.minimax.io/v1/files/retrieve?file_id={file_id}",
                headers={"Authorization": f"Bearer {MINIMAX_API_KEY}"},
            )
            download_url = resp.json()["file"]["download_url"]

        # 영상 다운로드
        video_path = os.path.join(
            tempfile.gettempdir(), f"shorts_minimax_{run_id}_{index}.mp4"
        )
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.get(download_url)
            with open(video_path, "wb") as f:
                f.write(resp.content)

        logger.info(f"MiniMax 장면 {index} 완료: {video_path}")
        return video_path

    except Exception as e:
        logger.error(f"MiniMax 장면 {index} 실패: {e}")
        return None


async def _generate_scene_videos(scenes: list[dict]) -> list[str | None]:
    """MiniMax T2V로 각 장면의 영상을 생성한다."""
    run_id = uuid.uuid4().hex[:8]

    # 병렬 생성
    tasks = [
        _generate_single_video(scene["prompt"], run_id, i)
        for i, scene in enumerate(scenes)
    ]
    results = await asyncio.gather(*tasks)
    return list(results)


async def _compose_video(script: dict, scene_paths: list[str | None]) -> str:
    """MoviePy로 영상을 합성한다. 대사 없이 BGM + SFX만."""
    run_id = uuid.uuid4().hex[:8]
    output_path = os.path.join(tempfile.gettempdir(), f"shorts_output_{run_id}.mp4")

    scenes = script["scenes"]
    valid_paths = [(i, p) for i, p in enumerate(scene_paths) if p is not None]

    if not valid_paths:
        raise RuntimeError("합성할 영상 클립이 없습니다.")

    clips = []
    current_time = 0
    fade_duration = 0.3
    sfx_timestamps = {
        "impact": 0.0,
        "whoosh_times": [],
    }

    for idx, (scene_idx, path) in enumerate(valid_paths):
        target_duration = scenes[scene_idx]["duration"]

        clip = VideoFileClip(path).resized((WIDTH, HEIGHT))

        # 클립 길이 조정
        if clip.duration > target_duration:
            clip = clip.subclipped(0, target_duration)
        elif clip.duration < target_duration:
            slow_factor = clip.duration / target_duration
            clip = clip.with_effects([vfx.MultiplySpeed(slow_factor)])
            clip = clip.subclipped(0, target_duration)

        # 크로스페이드
        fade_effects = []
        if idx > 0:
            fade_effects.append(vfx.CrossFadeIn(fade_duration))
        if idx < len(valid_paths) - 1:
            fade_effects.append(vfx.CrossFadeOut(fade_duration))
        if fade_effects:
            clip = clip.with_effects(fade_effects)

        clip = clip.with_start(current_time)
        clips.append(clip)

        # SFX 타이밍
        if idx > 0:
            sfx_timestamps["whoosh_times"].append(current_time)

        if idx < len(valid_paths) - 1:
            current_time += clip.duration - fade_duration
        else:
            current_time += clip.duration

    total_duration = current_time

    # === 오디오 믹싱: BGM + SFX (대사 없음) ===
    audio_clips = []

    # 1. BGM (메인 — 대사 없으므로 볼륨 높임)
    try:
        bgm_path = generate_bgm_loop(duration=total_duration + 5)
        bgm = AudioFileClip(bgm_path).with_effects([afx.MultiplyVolume(0.5)])
        if bgm.duration > total_duration:
            bgm = bgm.subclipped(0, total_duration)
        audio_clips.append(bgm)
    except Exception as e:
        logger.warning(f"BGM 로드 실패: {e}")

    # 2. SFX
    try:
        sfx = get_or_generate_sfx()

        # 후킹 임팩트 (0초)
        impact = AudioFileClip(sfx["impact"]).with_effects([afx.MultiplyVolume(0.6)])
        impact = impact.with_start(0.0)
        audio_clips.append(impact)

        # 장면 전환 whoosh
        for wt in sfx_timestamps["whoosh_times"][:5]:
            whoosh = AudioFileClip(sfx["whoosh"]).with_effects([afx.MultiplyVolume(0.4)])
            whoosh = whoosh.with_start(wt)
            audio_clips.append(whoosh)

    except Exception as e:
        logger.warning(f"SFX 로드 실패: {e}")

    # 최종 합성
    final = CompositeVideoClip(clips, size=(WIDTH, HEIGHT)).with_duration(total_duration)

    if audio_clips:
        mixed_audio = CompositeAudioClip(audio_clips)
        final = final.with_audio(mixed_audio)

    await asyncio.to_thread(
        final.write_videofile,
        output_path,
        fps=24,
        codec="libx264",
        audio_codec="aac",
        preset="ultrafast",
        logger=None,
    )

    # 리소스 정리
    for ac in audio_clips:
        try:
            ac.close()
        except Exception:
            pass
    for clip in clips:
        try:
            clip.close()
        except Exception:
            pass
    final.close()

    return output_path
