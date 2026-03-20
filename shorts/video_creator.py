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
    vfx,
)
from PIL import Image, ImageDraw, ImageFont

import logging

import shorts.trend_analyzer as trend_module
from shorts.trend_analyzer import _parse_json_response

logger = logging.getLogger("shorts.video_creator")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
TTS_VOICE = "ko-KR-HyunsuMultilingualNeural"
EPISODE_HISTORY_PATH = os.getenv("EPISODE_HISTORY_PATH", "/app/episode_history.json")

WIDTH = 720
HEIGHT = 1280

# 캐시: 마지막으로 생성된 스크립트 (업로드 시 재사용)
last_generated_script = None


def _load_episode_history() -> list[dict]:
    """에피소드 히스토리를 로드한다."""
    if os.path.exists(EPISODE_HISTORY_PATH):
        with open(EPISODE_HISTORY_PATH, "r") as f:
            return json.load(f)
    return []


def _save_episode(title: str, description: str):
    """생성된 에피소드를 히스토리에 저장한다."""
    history = _load_episode_history()
    history.append({"title": title, "description": description})
    with open(EPISODE_HISTORY_PATH, "w") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


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
    # 기존 에피소드 히스토리
    history = _load_episode_history()
    history_text = ""
    if history:
        recent = history[-20:]  # 최근 20개만
        history_text = "\n\n## 이미 만든 에피소드 (절대 겹치지 말 것!)\n"
        for ep in recent:
            history_text += f"- {ep['title']}: {ep['description']}\n"
        history_text += "\n위 에피소드와 다른 새로운 소재/각도로 만들어주세요.\n"

    prompt = f"""유튜브 쇼츠 영상 스크립트를 작성해주세요.

콘텐츠 포맷: {topic}
이번 에피소드 주제: {detail}{history_text}

## 톤 & 스타일 (매우 중요!)
- **다큐 나레이터 톤인데, 말하는 내용이 웃겨서 보는 사람이 "ㅋㅋ 진짜 이러긴 하지" 하게 만드는** 스타일
- 미래 역사학자가 21세기를 연구하는데, 우리 입장에서 들으면 "아 맞아 나도 이러는데 ㅋㅋ" 하게 되는 공감+웃음
- **핵심: 비판이 아니라 공감이다.** "이 시대 인류는 어리석었다"가 아니라 "이 시대 인류는 너무 귀여웠다. 이해할 수 없지만 사랑스러웠다" 느낌
- 좋은 예시: "이 시대 인류는 잠들기 전 반드시 15cm 유리판을 30분간 응시하는 의식을 치렀습니다. 학계에서는 이를 '취침 전 뇌 방전 의식'이라 부릅니다. 안 하면 잠이 안 왔다고 합니다. 귀엽지 않나요?"
- 또: "가장 놀라운 건, 배달 음식을 시켜놓고 그게 오는 2km를 직접 갈 수 있는데도... 40분을 기다렸다는 겁니다. 그 40분 동안 뭘 했냐고요? 다른 사람이 음식 먹는 영상을 봤습니다."
- 또: "21세기인들은 '읽씹'이라는 개념 때문에 극심한 스트레스를 받았습니다. 메시지를 읽고 답장을 안 하는 건데요. 이게 왜 스트레스냐면... 저도 모르겠습니다. 근데 진짜 스트레스였다고 합니다."
- **비판/훈계 톤 절대 금지!** "어리석다", "한심하다" 같은 표현 쓰지 말 것. 대신 "귀엽다", "신기하다", "이해불가지만 사랑스럽다" 톤
- 미래인이 만든 용어를 재밌게 만들 것 (예: '취침 전 뇌 방전 의식', '자발적 배달 대기 명상', '읽씹 트라우마 증후군')
- **마지막에 반전이나 펀치라인 필수**: 뭔가 하나 더 던져서 "ㅋㅋㅋ" 하고 끝나게

## 나레이션 규칙
- 하나의 이야기처럼 자연스럽게 흘러가야 함 (장면별로 끊기면 안 됨)
- **리듬감 있게**: 짧은 문장 → 살짝 긴 설명 → 짧은 펀치라인 반복
- 쉼표(,)와 마침표(.)를 적극적으로 써서 TTS가 자연스럽게 끊어 읽게 할 것
- "근데요.", "그런데 말입니다.", "놀라운 건요," 같은 전환어로 말하듯이 이어갈 것
- 첫 문장에서 바로 시선을 잡되, 호기심 유발 (충격이 아니라 "뭔소리야?" 느낌)
- 마지막에 다음 편 궁금하면 팔로우 유도 (가볍게)

## 구성
- 총 20~25초 영상
- 5개 장면으로 구성
- 각 장면 4~5초
- 각 장면에 화면에 표시할 짧은 텍스트(15자 이내)
- 각 장면에 DALL-E용 일러스트 배경 설명 (영어, 장면마다 다른 구도와 색감)
- 저작권 없는 소재만 사용

다음 JSON 형식으로만 응답하세요:
{{
    "title": "영상 제목 (호기심 자극, 40자 이내)",
    "description": "영상 설명 (100자 이내)",
    "tags": ["태그1", "태그2", "태그3", "태그4", "태그5"],
    "narration": "전체 나레이션 텍스트 (짧고 임팩트 있는 문장들. 군더더기 없이. 한 문장이 길면 안 됨)",
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
    communicate = edge_tts.Communicate(narration, TTS_VOICE, rate="+15%")
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


async def _compose_video(script: dict, tts_path: str, image_paths: list[str]) -> str:
    """MoviePy로 장면들을 합성해 최종 영상을 만든다."""
    run_id = uuid.uuid4().hex[:8]
    output_path = os.path.join(tempfile.gettempdir(), f"shorts_output_{run_id}.mp4")
    audio = AudioFileClip(tts_path)
    total_duration = audio.duration

    scenes = script["scenes"]
    total_scene_duration = sum(s["duration"] for s in scenes)
    ratio = total_duration / total_scene_duration if total_scene_duration > 0 else 1

    fade_duration = 0.3
    clips = []
    current_time = 0

    for i, scene in enumerate(scenes):
        duration = scene["duration"] * ratio
        img_path = image_paths[i] if i < len(image_paths) else image_paths[-1]

        bg = ImageClip(img_path).resized((WIDTH, HEIGHT)).with_duration(duration)

        # 크로스페이드
        if i > 0:
            bg = bg.with_effects([vfx.CrossFadeIn(fade_duration)])
        if i < len(scenes) - 1:
            bg = bg.with_effects([vfx.CrossFadeOut(fade_duration)])

        text_img_path = _create_text_image(scene["text"], run_id, i)
        text_overlay = ImageClip(text_img_path).with_duration(duration)

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
