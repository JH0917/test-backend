import os
import json
import asyncio
import tempfile
import uuid
import httpx
import anthropic
import openai
import edge_tts
from moviepy import (
    ImageClip,
    AudioFileClip,
    CompositeVideoClip,
    concatenate_videoclips,
    ColorClip,
    vfx,
)
from PIL import Image, ImageDraw, ImageFont

import logging

import shorts.trend_analyzer as trend_module
from shorts.trend_analyzer import _parse_json_response

logger = logging.getLogger("shorts.video_creator")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
TTS_VOICE = "ko-KR-InJoonNeural"

WIDTH = 720
HEIGHT = 1280

# 캐시: 마지막으로 생성된 스크립트 (업로드 시 재사용)
last_generated_script = None


async def create_shorts_video() -> str:
    """전역변수에서 주제를 읽어 20초 내외 쇼츠 영상을 생성한다. 생성된 파일 경로를 반환."""
    global last_generated_script

    if not trend_module.current_topic or not trend_module.current_topic_detail:
        raise ValueError("주제가 설정되지 않았습니다. analyze_youtube_trends()를 먼저 실행하세요.")

    script = await _generate_script(trend_module.current_topic, trend_module.current_topic_detail)
    last_generated_script = script

    tts_path = await _generate_tts(script["narration"])
    image_paths = await _generate_scene_images(script["scenes"])
    video_path = await _compose_video(script, tts_path, image_paths)

    return video_path


async def _generate_script(topic: str, detail: str) -> dict:
    """Claude API로 영상 스크립트를 생성한다."""
    prompt = f"""유튜브 쇼츠 영상 스크립트를 작성해주세요.

콘텐츠 포맷: {topic}
이번 에피소드 주제: {detail}

## 톤 & 스타일 (매우 중요!)
- **다큐멘터리 나레이터처럼 차분하고 진지하게 말하는데, 내용 자체가 웃긴** 스타일
- 미래 역사학자가 과거(현재)를 연구하면서 진지하게 분석하는데, 우리 입장에서 보면 어이없고 웃긴 것
- 좋은 예시: "이 시대 인류는 하루 평균 7시간을 15cm 유리판에 바쳤습니다. 식사 중에도, 심지어 배변 활동 중에도요. 학계에서는 이를 '자발적 뇌 위탁 현상'으로 분류하고 있습니다"
- 또 다른 예시: "옛날 사람들은 완전히 멘탈이 나가버렸습니다. 잠을 자야 하는 시간에 다른 사람이 잠자는 영상을 봤습니다"
- 또: "이들은 '좋아요'라는 가상의 숫자를 받기 위해 음식이 식을 때까지 각도를 맞춰 사진을 찍었습니다. 배고프면 그냥 먹으면 되는데요."
- **과장된 리액션 금지**. 담담하게, 학술적으로 말하되 내용이 웃겨야 함.
- 미래인이 만든 용어를 창의적으로 만들어 넣을 것 (예: '자발적 뇌 위탁', '디지털 수면 장애', '가상 승인 중독')

## 나레이션 규칙
- 하나의 이야기처럼 자연스럽게 이어져야 함 (장면별로 끊기면 안 됨)
- 말투: 차분한 다큐 나레이션. 진지할수록 좋음. 내용으로 웃기는 것.
- 첫 문장에서 바로 시선을 잡을 것 (충격적이지만 담담하게 던지는 사실)
- 마지막에 다음 편 궁금하면 팔로우 유도

## 구성
- 총 25~30초 영상
- 7~8개 장면으로 구성 (장면이 많을수록 역동적)
- 각 장면 2~4초
- 각 장면에 화면에 표시할 짧은 텍스트(15자 이내)
- 각 장면에 DALL-E용 일러스트 배경 설명 (영어, 장면마다 다른 구도와 색감)
- 저작권 없는 소재만 사용

다음 JSON 형식으로만 응답하세요:
{{
    "title": "영상 제목 (호기심 자극, 40자 이내)",
    "description": "영상 설명 (100자 이내)",
    "tags": ["태그1", "태그2", "태그3", "태그4", "태그5"],
    "narration": "전체 나레이션 텍스트 (하나의 자연스러운 이야기. 장면 구분 없이 매끄럽게 이어지는 문단)",
    "scenes": [
        {{
            "text": "화면에 표시할 텍스트",
            "duration": 3.0,
            "image_prompt": "Cute cartoon illustration of ... (English, specific visual scene, different angle/composition each scene)"
        }}
    ]
}}"""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = await asyncio.to_thread(
        client.messages.create,
        model="claude-opus-4-20250514",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )

    return _parse_json_response(message.content[0].text)


async def _generate_tts(narration: str) -> str:
    """edge-tts로 나레이션 음성을 생성한다."""
    tts_path = os.path.join(tempfile.gettempdir(), f"shorts_narration_{uuid.uuid4().hex[:8]}.mp3")
    communicate = edge_tts.Communicate(narration, TTS_VOICE)
    await communicate.save(tts_path)
    return tts_path


async def _generate_scene_images(scenes: list[dict]) -> list[str]:
    """DALL-E 3로 각 장면의 일러스트 배경을 생성한다."""
    run_id = uuid.uuid4().hex[:8]
    image_paths = []

    client = openai.OpenAI(api_key=OPENAI_API_KEY)
    style_suffix = "Cute cartoon illustration style, vibrant colors, expressive and funny, soft lighting, detailed background. No text or letters in the image."

    for i, scene in enumerate(scenes):
        try:
            prompt = scene.get("image_prompt", "abstract colorful background")
            full_prompt = f"{prompt}. {style_suffix}"

            response = await asyncio.to_thread(
                client.images.generate,
                model="dall-e-3",
                prompt=full_prompt,
                size="1024x1024",
                quality="standard",
                n=1,
            )

            image_url = response.data[0].url

            async with httpx.AsyncClient(timeout=60) as http_client:
                img_resp = await http_client.get(image_url)
                path = os.path.join(tempfile.gettempdir(), f"shorts_dalle_{run_id}_{i}.png")
                with open(path, "wb") as f:
                    f.write(img_resp.content)
                image_paths.append(path)
        except Exception as e:
            logger.error(f"DALL-E 장면 {i} 생성 실패: {e}")
            fallback_path = _create_fallback_background(run_id, i)
            image_paths.append(fallback_path)

    return image_paths


def _create_fallback_background(run_id: str, index: int) -> str:
    """DALL-E 실패 시 단색 배경을 생성한다."""
    img = Image.new("RGB", (WIDTH, HEIGHT), (30, 30, 50))
    path = os.path.join(tempfile.gettempdir(), f"shorts_fallback_{run_id}_{index}.jpg")
    img.save(path)
    return path


def _create_text_image(text: str, run_id: str, index: int, width: int = WIDTH, height: int = HEIGHT) -> str:
    """PIL로 텍스트가 들어간 반투명 오버레이 이미지를 생성한다."""
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    font_paths = [
        "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/noto/NotoSansCJK-Bold.ttc",
    ]
    font = None
    for fp in font_paths:
        if os.path.exists(fp):
            font = ImageFont.truetype(fp, 44)
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
    y = height - text_h - 160

    padding = 20
    draw.rounded_rectangle(
        [x - padding, y - padding, x + text_w + padding, y + text_h + padding],
        radius=12,
        fill=(0, 0, 0, 150),
    )
    draw.text((x, y), text, font=font, fill=(255, 255, 255, 255))

    path = os.path.join(tempfile.gettempdir(), f"shorts_text_{run_id}_{index}.png")
    img.save(path)
    return path


def _ken_burns_clip(img_path: str, duration: float, index: int) -> ImageClip:
    """Ken Burns 효과: 이미지를 살짝 줌인/줌아웃하며 패닝하는 움직이는 효과."""
    img = Image.open(img_path).convert("RGB")
    # 이미지를 약간 크게 리사이즈 (줌/패닝 여유)
    margin = 1.15
    big_w = int(WIDTH * margin)
    big_h = int(HEIGHT * margin)
    img = img.resize((big_w, big_h), Image.LANCZOS)

    big_path = img_path.replace(".png", "_big.png").replace(".jpg", "_big.jpg")
    img.save(big_path)

    clip = ImageClip(big_path).with_duration(duration)

    # 짝수 장면: 줌인 (넓게 → 좁게), 홀수 장면: 줌아웃 (좁게 → 넓게)
    if index % 2 == 0:
        start_scale = 1.0
        end_scale = 1.0 / margin
    else:
        start_scale = 1.0 / margin
        end_scale = 1.0

    def make_frame_transform(get_frame):
        def new_get_frame(t):
            frame = get_frame(t)
            progress = t / duration if duration > 0 else 0
            scale = start_scale + (end_scale - start_scale) * progress

            h, w = frame.shape[:2]
            new_w = int(WIDTH / scale)
            new_h = int(HEIGHT / scale)
            cx, cy = w // 2, h // 2

            x1 = max(0, cx - new_w // 2)
            y1 = max(0, cy - new_h // 2)
            x2 = min(w, x1 + new_w)
            y2 = min(h, y1 + new_h)

            cropped = frame[y1:y2, x1:x2]

            from PIL import Image as PILImage
            import numpy as np
            pil_img = PILImage.fromarray(cropped)
            pil_img = pil_img.resize((WIDTH, HEIGHT), PILImage.LANCZOS)
            return np.array(pil_img)
        return new_get_frame

    clip = clip.transform(make_frame_transform)
    return clip


async def _compose_video(script: dict, tts_path: str, image_paths: list[str]) -> str:
    """MoviePy로 장면들을 합성해 최종 영상을 만든다."""
    run_id = uuid.uuid4().hex[:8]
    output_path = os.path.join(tempfile.gettempdir(), f"shorts_output_{run_id}.mp4")
    audio = AudioFileClip(tts_path)
    total_duration = audio.duration

    scenes = script["scenes"]
    total_scene_duration = sum(s["duration"] for s in scenes)
    ratio = total_duration / total_scene_duration if total_scene_duration > 0 else 1

    fade_duration = 0.4
    clips = []
    current_time = 0

    for i, scene in enumerate(scenes):
        duration = scene["duration"] * ratio
        img_path = image_paths[i] if i < len(image_paths) else image_paths[-1]

        # Ken Burns 효과 (살짝 움직이는 느낌)
        bg = _ken_burns_clip(img_path, duration, i)

        # 크로스페이드
        if i > 0:
            bg = bg.with_effects([vfx.CrossFadeIn(fade_duration)])
        if i < len(scenes) - 1:
            bg = bg.with_effects([vfx.CrossFadeOut(fade_duration)])

        text_img_path = _create_text_image(scene["text"], run_id, i)
        text_overlay = ImageClip(text_img_path).with_duration(duration)
        # 텍스트도 페이드인
        text_overlay = text_overlay.with_effects([vfx.CrossFadeIn(0.3)])

        composite = CompositeVideoClip([bg, text_overlay], size=(WIDTH, HEIGHT))
        composite = composite.with_start(current_time)
        clips.append(composite)

        if i < len(scenes) - 1:
            current_time += duration - fade_duration
        else:
            current_time += duration

    final = CompositeVideoClip(clips, size=(WIDTH, HEIGHT))
    final = final.with_audio(audio)

    if final.duration > total_duration:
        final = final.subclipped(0, total_duration)

    await asyncio.to_thread(
        final.write_videofile,
        output_path,
        fps=24,
        codec="libx264",
        audio_codec="aac",
        preset="ultrafast",
        logger=None,
    )

    audio.close()
    for clip in clips:
        clip.close()
    final.close()

    return output_path
