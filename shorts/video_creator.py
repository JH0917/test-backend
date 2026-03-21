import os
import json
import asyncio
import tempfile
import uuid
import httpx
import anthropic
import openai
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

    script = await _generate_script(trend_module.current_topic, trend_module.current_topic_detail, trend_module.current_episode)
    last_generated_script = script

    tts_path = await _generate_tts(script["narration"])
    image_paths = await _generate_scene_images(script["scenes"])
    video_path = await _compose_video(script, tts_path, image_paths)

    return video_path


async def _generate_script(topic: str, detail: str, episode: str | None = None) -> dict:
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

    episode_text = ""
    if episode:
        episode_text = f"\n\n**이번 에피소드 소재 (반드시 이 소재로 만들 것!):** {episode}"

    prompt = f"""유튜브 쇼츠 영상 스크립트를 작성해주세요.

콘텐츠 포맷: {topic}
에피소드 방향: {detail}{episode_text}{history_text}

## 컨셉
100년 후 미래인이 21세기를 돌아보며 이야기하는 형식.
하지만 딱딱한 발표가 아니라, **친구한테 "야 이거 진짜 미친 거 알아?" 하면서 신나게 떠드는 느낌**.

## 스크립트 구조 (이 구조를 반드시 따를 것!)
유튜브 인기 채널들의 검증된 스토리텔링 패턴:

1. **어그로 오프닝** (1문장): 스크롤을 멈추게 하는 강렬한 첫마디
2. **상황 설명** (2~3문장): 뭐가 문제였는지 설명
3. **"그런데" 반전** (1~2문장): 예상 못한 전개
4. **"진짜 문제는 여기서부터"** (2~3문장): 더 깊은 이야기로 빠짐
5. **펀치라인 + 마무리** (1~2문장): 제일 웃긴 한방 + 팔로우 유도

## 실제 인기 채널 나레이션 참고 (이 리듬감을 따라할 것!)

참고1 (유유미미 - 돛의 원리, 조회수 수백만):
"옛날 사람들은 완전히 멘탈이 나가버렸습니다. 배 한 척에 돛대 하나만 달랑 있는데 바람이 정면에서 불어오면 배가 앞으로 나아갈 수가 없었거든요. 그래서 똑똑한 선원들이 사각돛 달고 지그재그로 항해하기 시작했습니다. 이리저리 꺾으면서 가니까 목적지에 도착할 수는 있었지만 시간이 배로 늘어나버렸죠. 그때 누군가 삼각돛을 만들었는데요..."

참고2 (유유미미 - 소금 만들기):
"옛날 사람들은 완전히 멘탈이 나가버렸습니다. 바닷물을 가마솥에 붓고 센 불로 끓이면 소금이 나온다는 걸 알았지만 심각한 문제가 생겼거든요. 물이 다 졸아들고 나니 온갖 지저분한 찌꺼기가 섞인 거친 소금만 남았습니다. 이걸 그냥 먹을 순 없었죠. 그래서 똑똑한 장인들이... 바로 그 순간 누군가가 완전히 미친 아이디어를 냈습니다."

→ **이 패턴의 핵심**:
- 강렬한 첫 문장으로 시작
- "~거든요", "~했죠", "~인데요" 같은 구어체 어미로 자연스럽게
- "그런데", "바로 그때", "진짜 문제는 여기서부터" 같은 전환어로 계속 궁금하게
- 하나의 이야기가 계속 전개되는 구조 (단순 나열 ❌)

## 우리 컨셉에 맞는 예시 (이런 느낌으로 만들 것!)
"21세기 사람들은 완전히 미쳐 돌아갔습니다. 초콜릿 하나가 유행하기 시작했는데요. 그냥 초콜릿이 아니라 안에 피스타치오 크림이 들어간 두바이 초콜릿이었거든요. 근데 문제는 이게 하나에 4만원이었습니다. 그래도 사람들이 4시간씩 줄을 섰거든요. 진짜 미친 건 여기서부터인데요. 품절되니까 되팔이가 나타났습니다. 3배 가격에요. 그리고 더 미친 건요. 그걸 또 샀습니다. 이 시대 사람들 진짜 대단하지 않나요? 다음에 더 미친 이야기 가져올게요."

## 절대 하지 말 것
- ❌ "~입니다. ~했습니다." 만 반복하는 딱딱한 발표 톤
- ❌ 단순 사실 나열 ("이런 게 있었습니다. 또 이런 것도 있었습니다. 끝.")
- ❌ 비판/훈계 톤 ("어리석다", "한심하다")
- ❌ 이야기 전개 없이 결론만 말하기

## 반드시 할 것
- ✅ "~거든요", "~했죠", "~인데요" 같은 구어체로 자연스럽게
- ✅ 이야기가 계속 전개되면서 궁금하게 (문제→반전→더 큰 문제→펀치라인)
- ✅ 구체적인 숫자/디테일로 웃김 만들기 (4만원, 4시간, 3배)
- ✅ "근데 진짜 미친 건요", "여기서부터가 진짜인데요" 같은 전환어
- ✅ 마지막에 "다음에 더 미친 이야기 가져올게요" 식으로 가볍게 마무리

## 구성
- 총 25~35초 영상 (이야기가 충분히 전개될 시간)
- 5개 장면으로 구성
- 각 장면 5~7초
- 각 장면에 화면에 표시할 짧은 텍스트(15자 이내)
- 각 장면에 DALL-E용 일러스트 배경 설명 (영어, 장면마다 다른 구도와 색감)
- **장면 분위기**: 미래 느낌 장면과 현대 일상 재현 장면을 섞어서
- 저작권 없는 소재만 사용

다음 JSON 형식으로만 응답하세요:
{{
    "title": "영상 제목 (호기심 자극, 40자 이내)",
    "description": "영상 설명 (100자 이내)",
    "tags": ["태그1", "태그2", "태그3", "태그4", "태그5"],
    "narration": "전체 나레이션 (자연스러운 구어체. 하나의 이야기로 전개. '~거든요' '~했죠' 같은 어미 사용)",
    "scenes": [
        {{
            "text": "화면에 표시할 텍스트",
            "duration": 5.0,
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
    """OpenAI TTS로 나레이션 음성을 생성한다."""
    tts_path = os.path.join(tempfile.gettempdir(), f"shorts_narration_{uuid.uuid4().hex[:8]}.mp3")

    client = openai.OpenAI(api_key=OPENAI_API_KEY)
    response = await asyncio.to_thread(
        client.audio.speech.create,
        model="gpt-4o-mini-tts",
        voice="coral",
        input=narration,
        instructions="""유튜브 쇼츠 나레이션을 해주세요. 반드시 한국어로 읽어주세요.

말투 스타일:
- 20대 남자가 친구한테 재밌는 이야기 해주는 것처럼 자연스럽게
- 절대 아나운서나 로봇처럼 읽지 말 것
- "있잖아 이거 진짜 웃긴데" 하면서 얘기하는 느낌

억양과 감정:
- 웃긴 부분에서는 살짝 웃음이 섞인 톤으로
- 충격적인 사실 말할 때는 "진짜?" 하듯이 톤을 올려서
- "네, 다시 말씀드립니다" 같은 반복 강조 부분은 힘주어서
- 마침표에서 확실히 끊고, 다음 문장 시작할 때 약간 텀 두기

속도:
- 전체적으로 빠르게, 텐션 있게
- 펀치라인 직전에만 살짝 느려졌다가 터뜨리기""",
        response_format="mp3",
        speed=1.2,
    )
    response.stream_to_file(tts_path)
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
