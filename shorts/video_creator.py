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

## 컨셉: 2124년 대학교 '21세기 문명학' 기말 발표
- 화자는 2124년 대학생. 역사학과 기말 발표로 21세기 인류의 기묘한 행동을 조사해서 발표하는 상황.
- 발표자 말투: 진지한 발표인데 본인도 중간중간 웃음이 새어나오는 느낌. "이건 저도 이해가 안 됩니다만," 같은 멘트.
- 21세기 행동을 설명할 때 미래 기준으로 해석해서 웃김을 만들 것.

## 참고 스타일 (유유미미 채널)
아래는 참고용 나레이션 예시. 이 리듬감과 전환 패턴을 참고하되 우리 컨셉에 맞게 변형할 것:
"옛날 사람들은 완전히 멘탈이 나가버렸습니다. 기차 선로는 긴 쇠막대를 이어붙여 만드는데, 볼트로 연결하면 금방 풀렸거든요. 그래서 쇠를 녹여서 하나로 붙이면 된다는 걸 알았지만, 전기도 없는 허벌판에서 그 열을 만들 방법이 없었죠. 그런데 똑똑한 장인이 이상한 걸 발견했습니다..."
→ 이 패턴의 핵심: 문제 제시 → "그런데" 반전 → 해결 → "진짜 문제는 여기서부터" → 또 반전

## 어그로 오프닝 (첫 문장이 제일 중요!)
- 발표 시작처럼 열되, 첫마디에 "뭐라고?" 하면서 스크롤을 멈추게 만들어야 함
- **매번 다른 창의적인 오프닝**. 아래는 참고용 예시일 뿐, 절대 그대로 쓰지 말고 매번 새롭게:
  - "안녕하십니까, 21세기 문명 연구 3조입니다. 오늘 발표 주제는, '왜 이 시대 인류는 밤에 자지 않았는가'입니다."
  - "교수님, 저희 조가 이번에 발굴한 자료를 보시면, 아마 커피를 뿜으실 겁니다."
  - "21세기 인류의 이 행동은, 저희 연구팀 전원이 3일간 토론하고도 결론을 내지 못했습니다."
- 핵심: 발표 형식 + 강렬한 호기심 유발

## 유머 규칙 (재미없으면 실패!)
- **공감형 유머**: 시청자가 "아 ㅋㅋ 맞아 나도 이럼" 하게 만들 것
- **구체적인 디테일이 웃김을 만든다**: "스마트폰을 봤다" ❌ → "새벽 3시에 이불 속에서 고개를 45도로 꺾은 채 남의 고양이 사진을 넘기고 있었다" ✅
- **반전 구조**: 진지하게 설명하다가 → 예상 못한 결론 → 웃음
- 좋은 예시: "이들은 음식을 주문하고, 2km 거리를 직접 갈 수 있는데도, 40분을 기다렸습니다. 그 40분 동안 뭘 했냐면요, 다른 사람이 음식 먹는 영상을 봤습니다."
- 또: "발표 중 죄송합니다만, 이건 저도 이해가 안 됩니다. 잠을 자야 하는 시간에, 다른 사람이 자는 영상을 봤습니다. 네, 다시 한번 말씀드립니다. 자야 하는 시간에, 남이 자는 걸, 봤습니다."
- 또: "교수님 이 부분에서 저희 조원 하나가 울었습니다. 감동이 아니라, 너무 공감돼서요."
- **비판/훈계 톤 절대 금지!** "어리석다", "한심하다" ❌ → "이해는 안 되지만 존중합니다", "이건 솔직히 좀 귀여운 것 같습니다" ✅
- 미래인이 만든 학술 용어를 창의적으로 (예: '취침 전 뇌 방전 의식', '자발적 배달 대기 명상', '읽씹 트라우마 증후군')
- **마지막에 반전 펀치라인 필수**: 제일 웃긴 한방 + 다음 발표 예고

## 나레이션 규칙
- 하나의 발표처럼 자연스럽게 흘러갈 것 (장면별로 끊기면 안 됨)
- **리듬감**: 짧은 문장 → 설명 → 짧은 펀치라인 반복. 한 문장이 2줄 넘어가면 안 됨
- 쉼표(,)와 마침표(.)를 적극 활용해서 TTS가 자연스럽게 끊어 읽게 할 것
- "근데요,", "여기서 놀라운 건요,", "잠깐, 이게 끝이 아닙니다," 같은 전환어 사용
- **"네, 다시 한번 말씀드립니다"** 같은 반복 강조 기법으로 웃긴 포인트를 두 번 때릴 것
- 발표 중 본인 감정 표현 OK ("이건 저도 좀 충격이었는데요,", "솔직히 좀 웃겼습니다,")
- 마지막에 "다음 발표가 궁금하시면 팔로우" 식으로 가볍게 유도

## 구성
- 총 20~25초 영상
- 5개 장면으로 구성
- 각 장면 4~5초
- 각 장면에 화면에 표시할 짧은 텍스트(15자 이내)
- 각 장면에 DALL-E용 일러스트 배경 설명 (영어, 장면마다 다른 구도와 색감)
- **장면 분위기 규칙**: 발표 장면(미래 강의실/홀로그램 등)과 21세기 재현 장면(현대인 일상)을 번갈아 배치
- 저작권 없는 소재만 사용

다음 JSON 형식으로만 응답하세요:
{{
    "title": "영상 제목 (호기심 자극, 40자 이내)",
    "description": "영상 설명 (100자 이내)",
    "tags": ["태그1", "태그2", "태그3", "태그4", "태그5"],
    "narration": "전체 나레이션 텍스트 (발표하듯 자연스럽게. 짧은 문장들. 한 문장이 길면 안 됨)",
    "scenes": [
        {{
            "text": "화면에 표시할 텍스트",
            "duration": 3.0,
            "image_prompt": "Cute cartoon illustration of ... (English, specific visual scene). 발표 장면은 futuristic classroom/hologram 느낌, 21세기 재현 장면은 modern daily life 느낌으로 번갈아 구성"
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
