import os
import json
import asyncio
import tempfile
import uuid
import httpx
import anthropic
import openai
from elevenlabs import ElevenLabs
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
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
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
    # 이전 질문 히스토리
    history = _load_episode_history()
    history_text = ""
    if history:
        recent = history[-20:]
        history_text = "\n\n## 이미 다룬 질문 (절대 겹치지 말 것!)\n"
        for ep in recent:
            history_text += f"- {ep['title']}\n"

    prompt = f"""당신은 유튜브 쇼츠 밸런스게임 콘텐츠 스크립트 작가입니다.

⚠️ 이번 밸런스게임 질문 (반드시 이 질문으로 스크립트를 작성할 것!):
{detail}{history_text}

## 채널 컨셉
"밸런스게임 결론내기" — 누구나 한번쯤 고민해본 황금 밸런스게임 질문에 나름의 논리와 유머로 결론을 내주는 채널.

## 스크립트 구조 (필수 준수)

### 1단계: 질문 던지기 (3~4초)
- 질문을 자연스럽게 읽고, 반드시 "결론 내드립니다."로 끝낼 것
- "결론 내드립니다"는 채널 정체성 캐치프레이즈. 절대 빠뜨리지 마세요.
- 질문 읽는 방식은 자유 (예: "똥맛 카레 vs 카레맛 똥, 결론 내드립니다." 또는 "투명인간이 될래 시간을 멈출래. 결론 내드립니다.")

### 2단계: A쪽 분석 (6~8초)
- A를 선택했을 때의 상황을 구체적으로 묘사
- 논리적인 듯 하면서 웃긴 포인트
- 예상치 못한 각도로 분석 (단순히 "맛이 나쁘다" 수준이 아니라)

### 3단계: B쪽 분석 (6~8초)
- B를 선택했을 때의 상황을 구체적으로 묘사
- A보다 더 깊이 있는 분석 or 더 웃긴 포인트
- "근데 B를 잘 생각해보면..." 하면서 전환

### 4단계: 결론 (5~7초)
- 한쪽을 확실하게 선택
- 근거가 논리적이면서도 웃김
- 약간 우기는 느낌도 OK ("이건 반박 불가입니다")
- 또는 예상 밖의 창의적 논리로 설득

### 5단계: 댓글 유도 (2~3초)
- 반드시 "여러분 선택은?" 으로 마무리
- 이 마무리 멘트도 채널 정체성. 절대 변경하지 마세요.

## 참고 스크립트 (이 리듬감과 구조를 따를 것! 소재는 그대로 쓰지 말 것!)

참고1 (똥맛 카레 vs 카레맛 똥):
"똥맛 카레 vs 카레맛 똥, 결론 내드립니다. 먼저 똥맛 카레. 일단 보이는 건 카레거든요. 식당에서 먹어도 아무도 모릅니다. 근데 한 숟갈 뜨는 순간 입 안에서 재앙이 펼쳐지죠. 그래도 참고 삼킬 수는 있습니다. 자 카레맛 똥. 맛은 완벽합니다. 향신료 향이 솔솔 나요. 근데 문제는 그게 똥이라는 겁니다. 눈 감고 먹으면 되지 않냐고요? 식감이 다릅니다. 결론. 똥맛 카레입니다. 이유는 단 하나. 먹고 나서 인스타에 올릴 수 있거든요. 여러분 선택은?"

참고2 (투명인간 vs 시간 정지):
"투명인간 vs 시간 정지, 결론 내드립니다. 투명인간. 솔직히 처음 3일은 천국이죠. 근데 문제가 있습니다. 옷을 입으면 옷만 둥둥 떠다닙니다. 겨울에 밖을 못 나가요. 감기 걸리면 병원도 못 갑니다. 의사가 놀라서 도망가거든요. 시간 정지. 이건 사기입니다. 시험 때 옆사람 답지 보는 건 기본이고요. 늦잠 자도 지각이 없습니다. 근데 진짜 핵심은 이겁니다. 시간을 멈추면 나만 늙어요. 혼자 막 10년 더 사는 겁니다. 결론. 그래도 시간 정지입니다. 10년 더 늙어도 지각 안 하는 게 더 중요하거든요. 여러분 선택은?"

## 톤 & 문체 규칙
- 구어체 필수: "~거든요", "~했죠", "~인데요", "~잖아요"
- 문장 길이: 한 문장 최대 40자. 짧게 끊어야 TTS 리듬이 살아남
- 과장과 유머 적극 사용
- 약간 건방진 듯 자신감 있는 톤 ("결론 내드립니다", "반박 불가입니다")
- 딱딱한 표현 금지: "~하였습니다", "~인 것이다" 같은 문어체 절대 사용 금지
- 반말/존댓말 섞어쓰기 OK (자연스러운 유튜버 말투)

## 금지 사항
- ❌ 교훈적 마무리
- ❌ 양쪽 다 좋다는 애매한 결론 (반드시 한쪽을 선택!)
- ❌ 딱딱한 분석 (재미가 최우선)
- ❌ 너무 진지한 톤
- ❌ 욕설, 음란한 내용

## 구성
- 총 30~40초 영상 (나레이션 300~450자)
- 5개 장면으로 구성
- 각 장면 5~8초
- 각 장면에 화면에 표시할 짧은 텍스트(15자 이내)
- 각 장면에 DALL-E용 일러스트 배경 설명 (영어, 유머러스한 카툰 스타일, 장면마다 다른 구도)
- 1번 장면: 질문 제시 (image_prompt는 "Pure black background"로 고정. 텍스트로 A vs B 질문 표시)
- 2번 장면: A쪽 상황 일러스트
- 3번 장면: B쪽 상황 일러스트
- 4번 장면: 결론 장면 (선택한 쪽을 강조)
- 5번 장면: 댓글 유도 (VS 배틀 느낌)

다음 JSON 형식으로만 응답하세요:
{{
    "title": "영상 제목 (호기심 자극, 40자 이내)",
    "description": "영상 설명 (100자 이내)",
    "tags": ["태그1", "태그2", "태그3", "태그4", "태그5"],
    "narration": "전체 나레이션 (구어체. 300~450자. 반드시 한쪽을 선택하는 결론 포함)",
    "scenes": [
        {{
            "text": "화면에 표시할 텍스트",
            "duration": 7.0,
            "image_prompt": "Funny cartoon illustration of ... (English, humorous style, vivid colors)"
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
    """ElevenLabs TTS로 나레이션 음성을 생성한다."""
    tts_path = os.path.join(tempfile.gettempdir(), f"shorts_narration_{uuid.uuid4().hex[:8]}.mp3")

    client = ElevenLabs(api_key=ELEVENLABS_API_KEY)
    audio_gen = await asyncio.to_thread(
        client.text_to_speech.convert,
        text=narration,
        voice_id="m3gJBS8OofDJfycyA2Ip",  # Taehyung - Natural, Friendly and Clear
        model_id="eleven_multilingual_v2",
        voice_settings={
            "stability": 0.35,
            "similarity_boost": 0.75,
            "style": 0.6,
            "speed": 1.2,
        },
    )

    with open(tts_path, "wb") as f:
        for chunk in audio_gen:
            f.write(chunk)
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

        # 이미지를 약간 크게 로드 (줌 효과용 여유분)
        bg_raw = ImageClip(img_path).resized((int(WIDTH * 1.15), int(HEIGHT * 1.15))).with_duration(duration)

        # 줌인/줌아웃 교차 적용
        if i % 2 == 0:
            # 줌인: 1.0x → 1.12x
            bg_zoomed = bg_raw.resized(lambda t, d=duration: 1 + 0.12 * (t / d))
        else:
            # 줌아웃: 1.12x → 1.0x
            bg_zoomed = bg_raw.resized(lambda t, d=duration: 1.12 - 0.12 * (t / d))

        bg_zoomed = bg_zoomed.with_position("center")
        bg = CompositeVideoClip([bg_zoomed], size=(WIDTH, HEIGHT)).with_duration(duration)

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
