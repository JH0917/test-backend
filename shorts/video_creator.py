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
- 친구한테 술자리에서 신나게 설명하듯이, 재밌고 자연스러운 말투
- 미래 역사학자가 21세기를 연구하는 컨셉이지만, **딱딱한 다큐가 아니라 친구처럼 말하는 역사학자**
- 듣는 사람이 "ㅋㅋ 아 맞아 나도 이러는데" 하면서 공감하게 만드는 게 핵심

## 어그로 오프닝 (첫 문장이 제일 중요!)
- 첫 문장에서 "뭐라고?" 하면서 멈추게 만들어야 함
- **매번 다른 창의적인 어그로 문장**을 만들 것. 아래는 참고용 예시일 뿐, 절대 그대로 쓰지 말고 매번 새롭게:
  - "21세기 인류는요, 솔직히 좀 미쳤습니다."
  - "이 시대 사람들한테는, 도저히 이해할 수 없는 의식이 하나 있었습니다."
  - "100년 후 역사 교과서에 이건 반드시 실릴 겁니다."
  - "우리 연구팀이 21세기 데이터를 분석하다가, 셋이 동시에 커피를 뿜었습니다."
- 핵심: **짧고, 강렬하고, "왜?" 하게 만드는 한 문장**

## 유머 규칙 (재미없으면 실패!)
- **공감형 유머**: 듣는 사람이 "아 ㅋㅋ 맞아 나도 이럼" 하게 만들 것
- **구체적인 디테일이 웃김을 만든다**: "스마트폰을 봤다" ❌ → "새벽 3시에 이불 속에서 고개를 45도로 꺾은 채 남의 고양이 사진을 넘기고 있었다" ✅
- **반전 구조**: 진지하게 설명하다가 → 예상 못한 결론 → 웃음
- 좋은 예시: "배달 음식을 시켜놓고 2km 거리를, 직접 갈 수 있는데도 40분을 기다렸습니다. 그 40분 동안 뭘 했냐고요? 다른 사람이 음식 먹는 영상을 봤습니다."
- 또: "읽씹이라는 개념 때문에 극심한 스트레스를 받았는데요. 메시지를 읽고 답장을 안 하는 건데, 이게 왜 스트레스냐면... 저도 모르겠습니다. 근데 진짜 스트레스였답니다."
- 또: "잠을 자야 하는 시간에, 다른 사람이 잠자는 영상을 봤습니다. 네, 다시 말씀드리겠습니다. 잠을 자야 하는 시간에, 남이 자는 걸 봤습니다."
- **비판/훈계 톤 절대 금지!** "어리석다", "한심하다" ❌ → "귀엽다", "이해는 안 되는데 존중합니다" ✅
- 미래인이 만든 용어를 창의적으로 (예: '취침 전 뇌 방전 의식', '자발적 배달 대기 명상', '읽씹 트라우마 증후군')
- **마지막에 반전 펀치라인 필수**: 제일 웃긴 한방을 마지막에 배치

## 나레이션 규칙
- 하나의 이야기처럼 자연스럽게 흘러갈 것 (장면별로 끊기면 안 됨)
- **리듬감**: 짧은 문장 → 설명 → 짧은 펀치라인 반복. 한 문장이 2줄 넘어가면 안 됨
- 쉼표(,)와 마침표(.)를 적극 활용해서 TTS가 자연스럽게 끊어 읽게 할 것
- "근데요,", "그런데 말입니다,", "놀라운 건요," 같은 전환어로 말하듯이 이어갈 것
- **"네, 다시 말씀드리겠습니다"** 같은 반복 강조 기법으로 웃긴 포인트를 두 번 때릴 것
- 마지막에 다음 편 궁금하면 팔로우 유도 (가볍게, 1문장)

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
