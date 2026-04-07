import os
import json
import asyncio
import tempfile
import time
import uuid
import httpx
import anthropic
import openai
from runwayml import RunwayML
from elevenlabs import ElevenLabs
from moviepy import (
    ImageClip,
    VideoFileClip,
    AudioFileClip,
    CompositeVideoClip,
    concatenate_videoclips,
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
RUNWAY_API_KEY = os.getenv("RUNWAY_API_KEY", "")
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


def _save_episode(title: str, description: str, keywords: str = ""):
    """생성된 에피소드를 히스토리에 저장한다."""
    history = _load_episode_history()
    history.append({"title": title, "description": description, "keywords": keywords})
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
    scene_video_paths = await _generate_scene_videos(script["scenes"], image_paths)
    video_path = await _compose_video(script, tts_path, scene_video_paths)

    return video_path


async def _generate_script(topic: str, detail: str) -> dict:
    """Claude API로 영상 스크립트를 생성한다."""
    prompt = f"""당신은 유튜브 쇼츠 밸런스게임 콘텐츠 스크립트 작가입니다.

⚠️ 이번 밸런스게임 질문 (반드시 이 질문으로 스크립트를 작성할 것!):
{detail}

## 채널 컨셉
"밸런스게임 결론내기" — 누구나 한번쯤 고민해본 황금 밸런스게임 질문에 나름의 논리와 유머로 결론을 내주는 채널.

## 스크립트 구조 (필수 준수)

### 1단계: 질문 던지기 (2~3초)
- 질문을 자연스럽게 읽고, 반드시 "결론 내드립니다."로 끝낼 것
- "결론 내드립니다"는 채널 정체성 캐치프레이즈. 절대 빠뜨리지 마세요.

### 2단계: 정답 쪽(A) 핵심 분석 (10~12초, 나레이션의 약 45%)
- 결론으로 선택할 쪽을 임팩트 있게 설명
- 가장 강력한 근거 2~3개만 빠르게
- 구체적인 상황 묘사 + 유머 포인트
- 군더더기 없이 핵심만

### 3단계: 반대쪽(B) 언급 + 즉시 반박 (5~7초, 나레이션의 약 25%)
- "근데 B는요?" 하면서 잠깐 B쪽 이야기
- 바로 반박 ("근데 잘 생각해보세요")

### 4단계: 결론 선언 (2~3초)
- "결론." 하고 확실하게 선택
- 한 줄로 임팩트 있는 최종 근거

### 5단계: 댓글 유도 (2초)
- 반드시 "여러분 선택은?" 으로 마무리
- 이 마무리 멘트도 채널 정체성. 절대 변경하지 마세요.

## 참고 스크립트 (이 리듬감과 구조를 따를 것! 소재는 그대로 쓰지 말 것!)

참고1 (똥맛 카레 vs 카레맛 똥):
"똥맛 카레 vs 카레맛 똥, 결론 내드립니다. 자 일단 똥맛 카레부터 봅시다. 보이는 건 카레거든요. 식당에서 먹어도 아무도 모릅니다. 누가 봐도 그냥 카레예요. 문제는 맛이죠. 한 숟갈 뜨는 순간 입 안에서 재앙이 펼쳐집니다. 근데요. 참을 수는 있어요. 코 막고 삼키면 됩니다. 감기 걸렸을 때 약 먹는 거랑 비슷한 거예요. 그리고 결정적으로 먹고 나서 인스타에 올릴 수 있거든요. 카레 먹었다고. 아무도 모릅니다. 자 카레맛 똥은요? 맛은 완벽합니다. 향신료 향이 솔솔 나요. 근데 잘 생각해보세요. 그게 똥입니다. 눈 감고 먹으면 된다고요? 식감이 다릅니다. 그리고 누가 보면요? 끝납니다. 인생이. 결론. 똥맛 카레입니다. 반박 불가. 여러분 선택은?"

참고2 (투명인간 vs 시간 정지):
"투명인간이 될래 시간을 멈출래. 결론 내드립니다. 시간 정지. 이건 사기입니다. 일단 늦잠 자도 지각이 없어요. 시간을 멈추면 되니까요. 시험 때 옆사람 답지 보는 건 기본이고요. 마감 전날 밤에 시간 멈추고 일주일치 작업 하면 됩니다. 상사한테 혼나는 중에 멈추고 도망가도 돼요. 아 물론 단점은 있습니다. 시간을 멈추면 나만 늙거든요. 혼자 막 10년 더 살 수도 있어요. 근데 투명인간은요? 처음 3일은 좋죠. 근데 잘 생각해보세요. 옷을 입으면 옷만 둥둥 떠다닙니다. 겨울에 밖을 못 나가요. 병원도 못 갑니다. 의사가 놀라서 도망가거든요. 결론. 시간 정지입니다. 10년 더 늙어도 지각 안 하는 게 더 중요하거든요. 여러분 선택은?"

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
- ❌ 선정적/19금 표현 (알고리즘 불이익)

## 구성
- 총 25~30초 영상 (나레이션 200~300자)
- 5개 장면으로 구성
- 각 장면 5~6초
- 각 장면에 화면에 표시할 큰 자막 텍스트(10자 이내, 핵심 키워드 위주)
- 각 장면에 DALL-E용 배경 설명 (영어, 실사 사진 스타일, 35mm 필름 느낌의 부드러운 톤, 자연스러운 표정, 장면마다 다른 구도)
- 각 장면에 Runway 영상 변환용 모션 설명 (영어, 장면 안에서 일어나는 구체적 동작/움직임 묘사)
- 1번 장면: 질문 제시 (image_prompt는 반드시 해당 밸런스게임 질문의 A vs B를 시각적으로 표현)
- 2~3번 장면: 정답 쪽(A) 핵심 분석 (2장면)
- 4번 장면: 반대쪽(B) 반박 (1장면)
- 5번 장면: 결론 + 댓글 유도 (image_prompt는 "Pure black background"로 고정. 텍스트로 결론 표시)

## 제목 규칙
- "최종 결론", "완벽 정리" 같은 결론 암시 부제 금지 (클릭 동기를 약화시킴)
- 대신 참여 유도형 사용: "당신의 선택은?", "너라면?", "결과가 충격적"
- 선택지를 구체적으로: "과거 여행" 대신 "2009년 비트코인 사러 가기"처럼 상황 묘사
- 40자 이내

## 설명 규칙
- 주제 키워드를 자연어로 포함 (SEO 최적화)
- 예: "치킨과 피자 중 하나를 평생 포기해야 한다면? 밸런스게임 결론!"
- 100자 이내

## 태그 규칙
- 처음 3개는 고정: "밸런스게임", "양자택일", "shorts"
- 나머지 2개는 해당 주제 키워드

다음 JSON 형식으로만 응답하세요:
{{
    "title": "영상 제목 (참여 유도형, 선정적 표현 금지, 40자 이내)",
    "description": "영상 설명 (주제 키워드 포함, 100자 이내)",
    "tags": ["밸런스게임", "양자택일", "shorts", "주제태그1", "주제태그2"],
    "narration": "전체 나레이션 (구어체. 200~300자. 반드시 한쪽을 선택하는 결론 포함)",
    "scenes": [
        {{
            "text": "큰 자막 텍스트 (10자 이내, 핵심 키워드)",
            "duration": 5.0,
            "image_prompt": "Editorial photograph of ... (English, 35mm film style, soft warm tones, natural expressions, real-world setting)",
            "motion_prompt": "구체적 동작 묘사 (English, e.g. 'The man takes a bite and his eyes widen, ice cream drips down')"
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
    style_suffix = "Editorial photograph style, shot on 35mm film, soft warm tones, gentle dreamy glow, real people in real settings, calm and natural expressions not exaggerated, natural daylight, vivid but natural colors, detailed background. No text or letters in the image."

    for i, scene in enumerate(scenes):
        try:
            prompt = scene.get("image_prompt", "abstract colorful background")
            full_prompt = f"{prompt}. {style_suffix}"

            response = await asyncio.to_thread(
                client.images.generate,
                model="dall-e-3",
                prompt=full_prompt,
                size="1024x1792",
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


async def _generate_scene_videos(scenes: list[dict], image_paths: list[str]) -> list[str]:
    """Runway Gen-4 Turbo로 각 장면의 이미지를 영상으로 변환한다."""
    run_id = uuid.uuid4().hex[:8]
    video_paths = []

    runway_client = RunwayML(api_key=RUNWAY_API_KEY)

    for i, (scene, img_path) in enumerate(zip(scenes, image_paths)):
        try:
            # 이미지를 data URI로 변환
            import base64
            with open(img_path, "rb") as f:
                img_data = base64.b64encode(f.read()).decode()
            ext = img_path.rsplit(".", 1)[-1]
            mime = "image/png" if ext == "png" else "image/jpeg"
            data_uri = f"data:{mime};base64,{img_data}"

            motion_prompt = scene.get("motion_prompt", scene.get("image_prompt", "gentle camera movement"))
            motion_prompt = f"Cinematic motion, dynamic and expressive. {motion_prompt}"

            task = await asyncio.to_thread(
                runway_client.image_to_video.create,
                model="gen4_turbo",
                prompt_image=data_uri,
                prompt_text=motion_prompt,
                ratio="720:1280",
                duration=5,
            )

            logger.info(f"Runway 장면 {i} 작업 시작: {task.id}")

            # 완료까지 polling (최대 5분)
            poll_start = time.monotonic()
            while True:
                if time.monotonic() - poll_start > 300:
                    raise RuntimeError(f"Runway 장면 {i} 타임아웃 (300초)")
                task_detail = await asyncio.to_thread(
                    runway_client.tasks.retrieve, task.id
                )
                if task_detail.status == "SUCCEEDED":
                    video_url = task_detail.output[0]
                    video_path = os.path.join(
                        tempfile.gettempdir(), f"shorts_runway_{run_id}_{i}.mp4"
                    )
                    async with httpx.AsyncClient(timeout=120) as http_client:
                        resp = await http_client.get(video_url)
                        with open(video_path, "wb") as f:
                            f.write(resp.content)
                    video_paths.append(video_path)
                    logger.info(f"Runway 장면 {i} 완료")
                    break
                elif task_detail.status in ("FAILED", "CANCELED"):
                    raise RuntimeError(f"Runway 실패: {task_detail.status}")
                await asyncio.sleep(5)

        except Exception as e:
            logger.error(f"Runway 장면 {i} 실패, 이미지 폴백: {e}")
            video_paths.append(img_path)  # 실패 시 이미지로 폴백

    return video_paths


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
            font = ImageFont.truetype(fp, 64)
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
    y = height - text_h - 200

    padding = 28
    draw.rounded_rectangle(
        [x - padding, y - padding, x + text_w + padding, y + text_h + padding],
        radius=16,
        fill=(0, 0, 0, 180),
    )
    # 흰색 큰 글씨 + 테두리 효과
    for dx, dy in [(-2, -2), (-2, 2), (2, -2), (2, 2)]:
        draw.text((x + dx, y + dy), text, font=font, fill=(0, 0, 0, 200))
    draw.text((x, y), text, font=font, fill=(255, 255, 255, 255))

    path = os.path.join(tempfile.gettempdir(), f"shorts_text_{run_id}_{index}.png")
    img.save(path)
    return path


async def _compose_video(script: dict, tts_path: str, scene_paths: list[str]) -> str:
    """MoviePy로 Runway 영상 클립들을 합성해 최종 영상을 만든다."""
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
        path = scene_paths[i] if i < len(scene_paths) else scene_paths[-1]

        # 영상 파일이면 VideoFileClip, 이미지면 ImageClip (폴백)
        if path.endswith(".mp4"):
            bg = VideoFileClip(path).resized((WIDTH, HEIGHT))
            # Runway 영상(5초)을 필요한 길이에 맞춤: 슬로모션으로 자연스럽게 늘림
            if bg.duration < duration:
                slow_factor = bg.duration / duration  # e.g. 5/7 = 0.71x 속도
                bg = bg.with_effects([vfx.MultiplySpeed(slow_factor)])
            bg = bg.subclipped(0, min(duration, bg.duration))
        else:
            bg_raw = ImageClip(path).resized((int(WIDTH * 1.15), int(HEIGHT * 1.15))).with_duration(duration)
            if i % 2 == 0:
                bg_zoomed = bg_raw.resized(lambda t, d=duration: 1 + 0.12 * (t / d))
            else:
                bg_zoomed = bg_raw.resized(lambda t, d=duration: 1.12 - 0.12 * (t / d))
            bg_zoomed = bg_zoomed.with_position("center")
            bg = CompositeVideoClip([bg_zoomed], size=(WIDTH, HEIGHT)).with_duration(duration)

        # 크로스페이드
        if i > 0:
            bg = bg.with_effects([vfx.CrossFadeIn(fade_duration)])
        if i < len(scenes) - 1:
            bg = bg.with_effects([vfx.CrossFadeOut(fade_duration)])

        text_img_path = _create_text_image(scene["text"], run_id, i)
        text_overlay = ImageClip(text_img_path).with_duration(bg.duration)

        composite = CompositeVideoClip([bg, text_overlay], size=(WIDTH, HEIGHT))
        composite = composite.with_start(current_time)
        clips.append(composite)

        if i < len(scenes) - 1:
            current_time += bg.duration - fade_duration
        else:
            current_time += bg.duration

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
