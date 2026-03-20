import os
import json
import asyncio
import tempfile
import uuid
import httpx
import anthropic
import edge_tts
from moviepy import (
    ImageClip,
    AudioFileClip,
    CompositeVideoClip,
    concatenate_videoclips,
    ColorClip,
)
from PIL import Image, ImageDraw, ImageFont

import shorts.trend_analyzer as trend_module
from shorts.trend_analyzer import _parse_json_response

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")
TTS_VOICE = "ko-KR-SunHiNeural"

WIDTH = 1080
HEIGHT = 1920

# 캐시: 마지막으로 생성된 스크립트 (업로드 시 재사용)
last_generated_script = None


async def create_shorts_video() -> str:
    """전역변수에서 주제를 읽어 20초 내외 쇼츠 영상을 생성한다. 생성된 파일 경로를 반환."""
    global last_generated_script

    if not trend_module.current_topic or not trend_module.current_topic_detail:
        raise ValueError("주제가 설정되지 않았습니다. analyze_youtube_trends()를 먼저 실행하세요.")

    script = await _generate_script(trend_module.current_topic, trend_module.current_topic_detail, trend_module.current_concept)
    last_generated_script = script

    tts_path = await _generate_tts(script["narration"])
    image_paths = await _fetch_background_images(script["search_keyword"], count=len(script["scenes"]))
    video_path = await _compose_video(script, tts_path, image_paths)

    return video_path


async def _generate_script(topic: str, detail: str, concept: str = "") -> dict:
    """Claude API로 영상 스크립트를 생성한다."""
    concept_line = f"\n채널 컨셉: {concept}" if concept else ""

    prompt = f"""유튜브 쇼츠 영상 스크립트를 작성해주세요.

콘텐츠 포맷: {topic}
이번 에피소드 주제: {detail}{concept_line}

조건:
- 총 20초 내외 영상
- 4~5개 장면으로 구성
- 각 장면에 화면에 표시할 짧은 텍스트(15자 이내)와 나레이션 포함
- 채널 컨셉에 맞는 독특한 시점/톤 유지 (매 영상 일관되게)
- 시청자의 호기심을 자극하는 도입부 (첫 1초에 시선 잡기)
- 마지막에 "다음 편도 궁금하면 팔로우!" 식 유도 문구
- 저작권 없는 소재만 사용 (영화/드라마/음악 등 타인 저작물 언급 금지)

다음 JSON 형식으로만 응답하세요:
{{
    "title": "영상 제목 (호기심 자극, 40자 이내)",
    "description": "영상 설명 (100자 이내)",
    "tags": ["태그1", "태그2", "태그3", "태그4", "태그5"],
    "search_keyword": "배경 이미지 검색에 쓸 영어 키워드 1개",
    "narration": "전체 나레이션 텍스트 (자연스럽게 이어지는 하나의 문단)",
    "scenes": [
        {{
            "text": "화면에 표시할 텍스트",
            "duration": 4.0
        }}
    ]
}}"""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = await asyncio.to_thread(
        client.messages.create,
        model="claude-opus-4-20250514",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}],
    )

    return _parse_json_response(message.content[0].text)


async def _generate_tts(narration: str) -> str:
    """edge-tts로 나레이션 음성을 생성한다."""
    tts_path = os.path.join(tempfile.gettempdir(), f"shorts_narration_{uuid.uuid4().hex[:8]}.mp3")
    communicate = edge_tts.Communicate(narration, TTS_VOICE)
    await communicate.save(tts_path)
    return tts_path


async def _fetch_background_images(keyword: str, count: int) -> list[str]:
    """Pexels API에서 배경 이미지를 가져온다. 실패 시 단색 배경으로 폴백."""
    run_id = uuid.uuid4().hex[:8]
    image_paths = []

    try:
        url = "https://api.pexels.com/v1/search"
        headers = {"Authorization": PEXELS_API_KEY}
        params = {"query": keyword, "per_page": count, "orientation": "portrait"}

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()

        photos = data.get("photos", [])
        async with httpx.AsyncClient(timeout=30) as client:
            for i, photo in enumerate(photos[:count]):
                try:
                    img_url = photo["src"]["large2x"]
                    resp = await client.get(img_url)
                    path = os.path.join(tempfile.gettempdir(), f"shorts_bg_{run_id}_{i}.jpg")
                    with open(path, "wb") as f:
                        f.write(resp.content)
                    image_paths.append(path)
                except Exception:
                    pass
    except Exception:
        pass

    # 이미지가 부족하면 단색 배경 생성
    while len(image_paths) < count:
        fallback_path = _create_fallback_background(run_id, len(image_paths))
        image_paths.append(fallback_path)

    return image_paths


def _create_fallback_background(run_id: str, index: int) -> str:
    """Pexels에서 이미지를 못 가져왔을 때 단색 배경을 생성한다."""
    img = Image.new("RGB", (WIDTH, HEIGHT), (30, 30, 50))
    path = os.path.join(tempfile.gettempdir(), f"shorts_fallback_{run_id}_{index}.jpg")
    img.save(path)
    return path


def _create_text_image(text: str, run_id: str, index: int, width: int = WIDTH, height: int = HEIGHT) -> str:
    """PIL로 텍스트가 들어간 반투명 오버레이 이미지를 생성한다."""
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 한글 폰트 로드
    font_paths = [
        "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/noto/NotoSansCJK-Bold.ttc",
    ]
    font = None
    for fp in font_paths:
        if os.path.exists(fp):
            font = ImageFont.truetype(fp, 60)
            break
    if font is None:
        font = ImageFont.load_default()

    if not text:
        path = os.path.join(tempfile.gettempdir(), f"shorts_text_{run_id}_{index}.png")
        img.save(path)
        return path

    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (width - text_w) // 2
    y = (height - text_h) // 2

    padding = 30
    draw.rounded_rectangle(
        [x - padding, y - padding, x + text_w + padding, y + text_h + padding],
        radius=20,
        fill=(0, 0, 0, 180),
    )
    draw.text((x, y), text, font=font, fill=(255, 255, 255, 255))

    path = os.path.join(tempfile.gettempdir(), f"shorts_text_{run_id}_{index}.png")
    img.save(path)
    return path


async def _compose_video(script: dict, tts_path: str, image_paths: list[str]) -> str:
    """MoviePy로 장면들을 합성해 최종 영상을 만든다."""
    run_id = uuid.uuid4().hex[:8]
    output_path = os.path.join(tempfile.gettempdir(), f"shorts_output_{run_id}.mp4")
    audio = AudioFileClip(tts_path)
    total_duration = audio.duration

    scenes = script["scenes"]
    total_scene_duration = sum(s["duration"] for s in scenes)
    ratio = total_duration / total_scene_duration if total_scene_duration > 0 else 1

    clips = []
    for i, scene in enumerate(scenes):
        duration = scene["duration"] * ratio
        img_path = image_paths[i] if i < len(image_paths) else image_paths[-1]

        bg = ImageClip(img_path).resized((WIDTH, HEIGHT)).with_duration(duration)

        text_img_path = _create_text_image(scene["text"], run_id, i)
        text_overlay = ImageClip(text_img_path).with_duration(duration)

        composite = CompositeVideoClip([bg, text_overlay], size=(WIDTH, HEIGHT))
        clips.append(composite)

    final = concatenate_videoclips(clips, method="compose")
    final = final.with_audio(audio)

    if final.duration > total_duration:
        final = final.subclipped(0, total_duration)

    await asyncio.to_thread(
        final.write_videofile,
        output_path,
        fps=30,
        codec="libx264",
        audio_codec="aac",
        preset="fast",
        logger=None,
    )

    audio.close()
    for clip in clips:
        clip.close()
    final.close()

    return output_path
