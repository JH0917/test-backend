import os
import json
import asyncio
import random
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
    vfx,
)
import moviepy.audio.fx as afx
from moviepy.audio.AudioClip import CompositeAudioClip
from PIL import Image, ImageDraw, ImageFont
from shorts.audio_assets import get_or_generate_sfx, generate_bgm_loop

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
        try:
            with open(EPISODE_HISTORY_PATH, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError):
            return []
    return []


def _save_episode(title: str, description: str, keywords: str = "", question: str = ""):
    """생성된 에피소드를 히스토리에 저장한다."""
    history = _load_episode_history()
    entry = {"title": title, "description": description, "keywords": keywords}
    if question:
        entry["question"] = question
    history.append(entry)
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

    # DALL-E 전체 실패 시 영상 생성 중단 (까만 화면 영상 업로드 방지)
    fallback_count = sum(1 for p in image_paths if "fallback" in os.path.basename(p))
    if fallback_count == len(image_paths):
        raise RuntimeError("DALL-E 이미지 전체 실패 — 영상 생성을 중단합니다. 크레딧을 확인하세요.")

    scene_video_paths = await _generate_scene_videos(script["scenes"], image_paths)
    video_path = await _compose_video(script, tts_path, scene_video_paths)

    return video_path


async def _generate_script(topic: str, detail: str) -> dict:
    """Claude API로 영상 스크립트를 생성한다."""
    history = _load_episode_history()
    episode_number = len(history) + 1
    last_title = history[-1]["title"] if history else "없음"

    # 매 영상마다 다른 톤과 포맷을 랜덤 선택
    tones = [
        "단톡방에서 친구 저격하는 톤 — 짧고 얄밉게, 웃기면서 찔리게",
        "새벽 커뮤 급발진 톤 — 과몰입해서 혼자 열받아 하는 느낌",
        "예능 MC 톤 — 선택지마다 리액션 넣고 관객석 웃음 터뜨리기",
        "참사 중계 톤 — 선택 직후 벌어지는 재앙을 뉴스 앵커처럼 전달",
        "선배 톤 — 인생 경험 많은 척 조언하다가 본인도 못 고름",
    ]
    hooks = [
        "잠깐. 이거 고르는 순간 단톡방에서 박제됩니다.",
        "이건 밸런스게임이 아니라 인성검사입니다.",
        "친구한테 물어봤다가 5분 동안 정적 흘렀습니다.",
        "이건 고민하면 안 됩니다. 고민 자체가 위험합니다.",
        "댓글창 터질 질문 가져왔습니다.",
        "엄마 앞에서 설명해보세요. 못 하면 틀린 겁니다.",
        "이거 잘못 고르면 사회적으로 끝납니다.",
        "솔직히 이거 3초 안에 못 고르면 문제 있는 겁니다.",
        "이 질문 만든 사람이 진짜 나쁜 사람입니다.",
    ]
    tone = random.choice(tones)
    hook = random.choice(hooks)

    prompt = f"""당신은 유튜브 쇼츠 밸런스게임 콘텐츠 스크립트 작가입니다.
조회수 100만 이상 바이럴 쇼츠만 만드는 전문가입니다.

⚠️ 질문: {detail}
⚠️ 에피소드: #{episode_number}
⚠️ 직전 제목: "{last_title}" — 다른 패턴 사용!
⚠️ 톤: {tone}
⚠️ 첫 문장: "{hook}"

## 핵심 원칙
이 영상은 "분석"이 아니라 "상황극"입니다.
시청자가 웃는 건 논리가 아니라 "아 ㅋㅋㅋ 저건 진짜 망했다" 하는 장면입니다.
매 문장이 새로운 그림을 그려야 합니다. 같은 말 반복하면 스와이프 당합니다.

## 6컷 구조 (정확히 6장면, 더 넣지 말 것)
1. 🔥 훅 + 질문: "{hook}" 후 바로 "A vs B. 결론 내드립니다."
2. 😱 A 선택 시 벌어지는 현실 (웃긴 참사 장면 2~3개 빠르게)
3. 💀 B 선택 시 벌어지는 현실 (A보다 더 극적인 참사)
4. 🤔 양쪽 비교하며 갈등 (어? 근데 이거 은근 고민되는데?)
5. ⚡ 결론 선언 — 확신에 찬 한마디 + 펀치라인
6. 🔁 "여러분 선택은?" + 떡밥 (첫 장면 질문을 다시 상기시키며 루프)

## 재미 엔진 — 이걸 안 넣으면 영상이 죽습니다
- 최소 3개의 "구체적 현실 장면" 필수:
  소개팅에서 들킴, 단톡방 폭발, 엄마가 방문 열음, 회사 프레젠테이션 중, 지하철 옆사람 표정, 전애인 SNS에 올라감, 편의점 CCTV에 찍힘
- 최소 2개의 "밈급 비유" 필수:
  "인생 난이도 DLC", "사회적 사망 선고", "영혼 탈곡기", "멘탈 포맷", "인간관계 공장초기화"
- 한쪽 팬 도발 필수: "B파 지금 화났죠?", "A 고른 사람 손?", "이거 고른 사람 진심?"

## 참고 스크립트 (이 수준의 재미와 속도감을 반드시 따를 것!)

참고1 (160자, 검색기록 vs 카톡):
"이건 인성검사입니다. 검색기록 공개 vs 카톡 공개. 결론 내드립니다. 검색기록요? 새벽 2시 검색 다 압니다. 근데 사람들 하루면 잊어요. 카톡은요? 친구 뒷담, 전애인 장문, 엄마한테 거짓말. 풀HD 다큐멘터리입니다. 공개되는 순간 단톡방 이름이 '해명해'로 바뀝니다. 결론. 검색기록. 창피한 건 하루고 카톡은 인간관계 압수입니다. 카톡파 댓글로 변론하세요. 여러분 선택은?"

참고2 (170자, 100억 혼자 vs 가난한 사랑):
"댓글창 싸움 예약입니다. 100억 혼자 vs 가난한 사랑. 결론 내드립니다. 가난한 사랑요? 월세날부터 장르가 바뀝니다. 로맨스인 줄 알았는데 생존 스릴러. 치킨 한 마리에 가족회의합니다. 100억은요? 외롭습니다. 근데 80평에서 외로운 겁니다. 울어도 한강뷰. 문제는 생일. 케이크 초를 혼자 끕니다. 결론. 100억. 외로움은 버티는데 카드값 독촉은 못 버팁니다. 여러분 선택은?"

참고3 (150자, 바퀴벌레 동거 vs 돈):
"잠깐. 이거 고르는 순간 멘탈 포맷됩니다. 바퀴벌레랑 1년 동거하고 10억 vs 돈 없이 깨끗한 집. 결론 내드립니다. 바퀴벌레 동거요? 첫날. 거실에 있습니다. 눈 마주칩니다. 일주일 후. 이름 붙여줍니다. 한 달 후. 걔가 내 방입니다. 근데 10억이잖아요. 10억이면 동거 끝나고 바로 해외 도피 가능합니다. 결론. 동거. 1년 참으면 평생 삽니다. 깨끗한 집파 솔직히 부럽죠? 여러분 선택은?"

참고4 (165자, 전애인 카톡 vs 직장 단톡):
"이 질문 만든 사람이 진짜 나쁜 사람입니다. 전애인한테 3년 전 카톡 재전송 vs 직장 단톡방에 혼잣말 전송. 결론 내드립니다. 전애인 카톡요? 새벽에 보낸 그거 다시 갑니다. 읽씹당하면 그나마 다행. 답장 오면 진짜 끝납니다. 직장 단톡은요? 부장님한테 '아 퇴근하고싶다' 날아갑니다. 월요일 아침에. 회의실 불려갑니다. 결론. 전애인. 전애인은 차단하면 끝인데 부장님은 내일도 봐야 합니다. 여러분 선택은?"

참고5 (140자, 냄새 vs 외모):
"솔직히 이거 3초 안에 못 고르면 문제 있는 겁니다. 외모 완벽 냄새 지옥 vs 외모 별로 향기 천국. 결론 내드립니다. 완벽 외모요? 카페 들어갑니다. 다 쳐다봅니다. 근데 5초 후 다 고개 돌립니다. 엘리베이터에서 둘이 타면 신고 들어옵니다. 향기 쪽은요? 스쳐지나가면 뒤돌아봅니다. 근데 얼굴 보고 다시 돌아섭니다. 결론. 향기. 외모는 눈 감으면 끝인데 냄새는 코를 못 막습니다. 여러분 선택은?"

## 문체 규칙
- 한 문장 최대 25자! 이거 넘기면 지루합니다.
- 문장 끝 다양하게: "끝.", "망.", "압수.", "박제.", "탈출 불가.", "바로 신고."
- "~거든요" 3회 이상 반복 금지.
- 설명 말고 장면. 근거 말고 그림. 착한 말 말고 댓글 폭탄.

## 절대 금지
- "자 일단", "잘 생각해보세요", "핵심은", "강력한 근거" — 이런 거 쓰면 채널 망합니다
- 장황한 설명, 교훈, 양비론, 가짜 통계
- "~이기 때문입니다", "~할 수 있습니다" 같은 문어체

## 구성
- 총 22~32초 영상 (나레이션 160~250자)
- 정확히 6개 장면
- 각 장면 3~5초
- 각 장면에 화면 자막 텍스트 (8자 이내! 짧을수록 임팩트)
- 각 장면에 DALL-E 이미지 프롬프트 (영어, 아래 스타일 가이드 참고)
- 1번 장면: image_prompt_a + image_prompt_b (분할화면용)
- 2~4번 장면: 상황극 장면 (표정, 리액션이 핵심!)
- 5번 장면: 결론 (image_prompt는 "Pure black background"로 고정)
- 6번 장면: 댓글 유도 (image_prompt는 "Pure black background"로 고정)
- ⚠️ 5번과 6번 사이에 카운트다운이 자동 삽입됩니다

## 이미지 프롬프트 스타일 가이드
- "editorial photograph" 대신 → "cinematic close-up" 또는 "dramatic wide shot" 사용
- 사람의 과장된 표정이 핵심: shocked face, disgusted expression, crying while laughing, jaw-dropping moment
- 색감: 네온 조명, 강한 명암 대비, 영화 같은 컬러 그레이딩
- 예시: "Cinematic close-up of a Korean man in his 20s looking at his phone with a horrified expression, neon blue lighting, dramatic shadows, 35mm film grain"
- 추상적 배경 금지. 구체적 장소와 상황이 있어야 함.

## 제목 규칙
- 짧고 자극적. 30자 이내.
- "이거 고르면 단톡방 박제됨", "엄마한테 설명 가능?", "댓글창 전쟁 예약"
- 선택지 압축: "검색기록 vs 카톡", "10억 냄새 vs 0원 향기"

다음 JSON으로만 응답:
{{
    "title": "제목 (30자 이내)",
    "description": "설명 (80자 이내)",
    "tags": ["밸런스게임", "양자택일", "shorts", "결론내드립니다", "쇼츠", ...],
    "narration": "나레이션 (160~250자, 구어체, 반드시 한쪽 선택)",
    "scenes": [
        {{
            "text": "자막 (8자 이내)",
            "duration": 4.0,
            "image_prompt": "Cinematic ... (English)",
            "image_prompt_a": "(1번만) A 이미지",
            "image_prompt_b": "(1번만) B 이미지",
            "motion_prompt": "동작 (English)"
        }}
    ]
}}

⚠️ 정확히 6개 장면! 1번만 image_prompt_a/b, 나머지는 image_prompt만!"""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = await asyncio.to_thread(
        client.messages.create,
        model="claude-sonnet-4-6",
        max_tokens=2500,
        messages=[{"role": "user", "content": prompt}],
    )

    script = _parse_json_response(message.content[0].text)

    # 에피소드 번호 강제 삽입 (LLM이 누락한 경우 대비)
    if f"#{episode_number}" not in script["title"]:
        script["title"] = f"#{episode_number} {script['title']}"

    # LLM 출력 검증 (장면 수, 나레이션 길이)
    scene_count = len(script.get("scenes", []))
    if scene_count != 6:
        logger.warning(f"장면 수 {scene_count}개 (기대: 6개)")
    narration_len = len(script.get("narration", ""))
    if not (140 <= narration_len <= 280):
        logger.warning(f"나레이션 {narration_len}자 (기대: 160~250자)")
    logger.info(f"생성된 제목: {script.get('title')}")
    logger.info(f"생성된 나레이션: {script.get('narration')}")

    return script


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


async def _generate_single_image(client, prompt: str, style_suffix: str, run_id: str, label: str) -> str | None:
    """DALL-E 이미지 1장을 생성한다."""
    try:
        import base64 as b64module
        full_prompt = f"{prompt}. {style_suffix}"
        response = await asyncio.to_thread(
            client.images.generate,
            model="gpt-image-1",
            prompt=full_prompt,
            size="1024x1536",
            quality="medium",
            n=1,
        )
        img_b64 = response.data[0].b64_json
        path = os.path.join(tempfile.gettempdir(), f"shorts_dalle_{run_id}_{label}.png")
        with open(path, "wb") as f:
            f.write(b64module.b64decode(img_b64))
        return path
    except Exception as e:
        logger.error(f"DALL-E {label} 생성 실패: {e}")
        return None


def _create_split_screen(img_a_path: str, img_b_path: str, question: str, run_id: str) -> str:
    """A vs B 분할화면 이미지를 생성한다. 상단=A, 하단=B, 중앙=VS."""
    half_h = HEIGHT // 2

    # A 이미지 (상단) - 주황 틴트
    img_a = Image.open(img_a_path).convert("RGBA").resize((WIDTH, half_h), Image.LANCZOS)
    orange_tint = Image.new("RGBA", (WIDTH, half_h), (255, 140, 0, 50))
    img_a = Image.alpha_composite(img_a, orange_tint)

    # B 이미지 (하단) - 파랑 틴트
    img_b = Image.open(img_b_path).convert("RGBA").resize((WIDTH, half_h), Image.LANCZOS)
    blue_tint = Image.new("RGBA", (WIDTH, half_h), (0, 100, 255, 50))
    img_b = Image.alpha_composite(img_b, blue_tint)

    # 합성
    canvas = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 255))
    canvas.paste(img_a, (0, 0))
    canvas.paste(img_b, (0, half_h))

    draw = ImageDraw.Draw(canvas)

    # 중앙 분할선 + VS 배지
    divider_y = half_h
    draw.rectangle([0, divider_y - 4, WIDTH, divider_y + 4], fill=(255, 255, 255, 200))

    # VS 원형 배지
    vs_radius = 50
    cx, cy = WIDTH // 2, divider_y
    draw.ellipse(
        [cx - vs_radius, cy - vs_radius, cx + vs_radius, cy + vs_radius],
        fill=(220, 30, 30, 255),
        outline=(255, 255, 255, 255),
        width=4,
    )

    # VS 텍스트
    font = _load_font(48)
    bbox = draw.textbbox((0, 0), "VS", font=font)
    vs_w = bbox[2] - bbox[0]
    vs_h = bbox[3] - bbox[1]
    draw.text((cx - vs_w // 2, cy - vs_h // 2), "VS", font=font, fill=(255, 255, 255, 255))

    # A/B 라벨
    label_font = _load_font(36)
    draw.text((30, 30), "A", font=label_font, fill=(255, 200, 50, 255))
    draw.text((30, half_h + 30), "B", font=label_font, fill=(100, 180, 255, 255))

    path = os.path.join(tempfile.gettempdir(), f"shorts_split_{run_id}.png")
    canvas.convert("RGB").save(path)
    return path


def _load_font(size: int):
    """한글 폰트를 로드한다."""
    font_paths = [
        "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/noto/NotoSansCJK-Bold.ttc",
    ]
    for fp in font_paths:
        if os.path.exists(fp):
            return ImageFont.truetype(fp, size)
    return ImageFont.load_default()


def _create_countdown_frames(run_id: str) -> list[str]:
    """2, 1 카운트다운 이미지 프레임을 생성한다."""
    frames = []
    colors = [(255, 80, 80), (80, 255, 80)]  # 빨-초

    for i, (num, color) in enumerate(zip([2, 1], colors)):
        img = Image.new("RGB", (WIDTH, HEIGHT), (15, 15, 25))
        draw = ImageDraw.Draw(img)

        # 큰 숫자
        font = _load_font(240)
        text = str(num)
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        x, y = (WIDTH - tw) // 2, (HEIGHT - th) // 2 - 50

        # 글로우 효과
        for offset in range(8, 0, -2):
            draw.text((x - offset, y), text, font=font, fill=color)
            draw.text((x + offset, y), text, font=font, fill=color)
        draw.text((x, y), text, font=font, fill=(255, 255, 255))

        # "결론 공개" 텍스트
        sub_font = _load_font(44)
        sub_text = "결론 공개"
        sb = draw.textbbox((0, 0), sub_text, font=sub_font)
        sw = sb[2] - sb[0]
        draw.text(((WIDTH - sw) // 2, y + th + 40), sub_text, font=sub_font, fill=(200, 200, 200))

        path = os.path.join(tempfile.gettempdir(), f"shorts_countdown_{run_id}_{i}.png")
        img.save(path)
        frames.append(path)

    return frames


async def _generate_scene_images(scenes: list[dict]) -> list[str]:
    """DALL-E로 각 장면의 배경 이미지를 생성한다. 첫 장면은 A/B 분할화면."""
    run_id = uuid.uuid4().hex[:8]
    image_paths = []

    client = openai.OpenAI(api_key=OPENAI_API_KEY)
    style_suffix = (
        "Cinematic photograph with dramatic lighting. "
        "Strong contrast, neon accent colors (blue/orange/red), deep shadows. "
        "Expressive human faces with exaggerated emotions: shock, disgust, laughter, horror. "
        "Real people in real settings, dynamic angles (low angle, dutch tilt, extreme close-up). "
        "Film grain texture, 35mm anamorphic lens feel. "
        "Vibrant, high-energy, YouTube thumbnail quality. "
        "No text, no letters, no watermarks in the image."
    )

    for i, scene in enumerate(scenes):
        if i == 0 and scene.get("image_prompt_a") and scene.get("image_prompt_b"):
            # 첫 장면: A/B 분할화면
            img_a = await _generate_single_image(client, scene["image_prompt_a"], style_suffix, run_id, "0a")
            img_b = await _generate_single_image(client, scene["image_prompt_b"], style_suffix, run_id, "0b")

            if img_a and img_b:
                split_path = _create_split_screen(img_a, img_b, scene.get("text", ""), run_id)
                image_paths.append(split_path)
            elif img_a:
                image_paths.append(img_a)
            elif img_b:
                image_paths.append(img_b)
            else:
                image_paths.append(_create_fallback_background(run_id, i))
        else:
            # 일반 장면
            path = await _generate_single_image(
                client, scene.get("image_prompt", "abstract colorful background"),
                style_suffix, run_id, str(i),
            )
            image_paths.append(path or _create_fallback_background(run_id, i))

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


def _create_text_image(text: str, run_id: str, index: int, total_scenes: int = 6,
                       width: int = WIDTH, height: int = HEIGHT) -> str:
    """PIL로 텍스트가 들어간 반투명 오버레이 이미지를 생성한다.
    자막 위치가 장면마다 다양하게 변경된다."""
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 첫 프레임은 더 큰 폰트, 마지막 2개도 큰 폰트 (결론/댓글유도)
    is_first = index == 0
    is_conclusion = index >= total_scenes - 2
    font_size = 88 if (is_first or is_conclusion) else 72
    font = _load_font(font_size)

    if not text:
        path = os.path.join(tempfile.gettempdir(), f"shorts_text_{run_id}_{index}.png")
        img.save(path)
        return path

    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (width - text_w) // 2

    # 자막 위치 다양화: 장면 인덱스에 따라 상단/중앙/하단 순환
    positions = [
        height - text_h - 200,       # 하단 (기본)
        120,                          # 상단
        (height - text_h) // 2,       # 중앙
        height - text_h - 200,        # 하단
        120,                          # 상단
        (height - text_h) // 2,       # 중앙
        (height - text_h) // 2 + 100, # 중앙 아래
        (height - text_h) // 2,       # 중앙
    ]
    y = positions[index % len(positions)]

    padding = 32
    if is_first:
        # 첫 프레임: 강렬한 빨강 + 네온 효과
        draw.rounded_rectangle(
            [x - padding, y - padding, x + text_w + padding, y + text_h + padding],
            radius=24, fill=(220, 20, 20, 230),
        )
    elif is_conclusion:
        # 결론/댓글 유도: 네온 블루
        draw.rounded_rectangle(
            [x - padding, y - padding, x + text_w + padding, y + text_h + padding],
            radius=24, fill=(20, 80, 220, 230),
        )
    else:
        # 일반 장면: 검정 반투명 + 테두리
        draw.rounded_rectangle(
            [x - padding, y - padding, x + text_w + padding, y + text_h + padding],
            radius=20, fill=(0, 0, 0, 200),
        )
        draw.rounded_rectangle(
            [x - padding, y - padding, x + text_w + padding, y + text_h + padding],
            radius=20, outline=(255, 255, 255, 100), width=2,
        )

    # 두꺼운 외곽선 + 흰색 글씨
    for dx, dy in [(-3, -3), (-3, 3), (3, -3), (3, 3), (-3, 0), (3, 0), (0, -3), (0, 3)]:
        draw.text((x + dx, y + dy), text, font=font, fill=(0, 0, 0, 230))
    draw.text((x, y), text, font=font, fill=(255, 255, 255, 255))

    path = os.path.join(tempfile.gettempdir(), f"shorts_text_{run_id}_{index}.png")
    img.save(path)
    return path


async def _compose_video(script: dict, tts_path: str, scene_paths: list[str]) -> str:
    """MoviePy로 영상을 합성한다. BGM/SFX 믹싱 + 카운트다운 삽입."""
    run_id = uuid.uuid4().hex[:8]
    output_path = os.path.join(tempfile.gettempdir(), f"shorts_output_{run_id}.mp4")
    tts_audio = AudioFileClip(tts_path)
    tts_duration = tts_audio.duration

    scenes = script["scenes"]
    total_scenes = len(scenes)

    # 카운트다운 2초를 포함한 전체 길이 계산
    countdown_duration = 2.0
    total_video_duration = tts_duration + countdown_duration

    # 장면별 시간 비율 계산 (카운트다운 제외)
    total_scene_duration = sum(s["duration"] for s in scenes)
    ratio = tts_duration / total_scene_duration if total_scene_duration > 0 else 1

    # 카운트다운 삽입 위치: 결론 장면(마지막에서 2번째) 직전
    countdown_insert_idx = total_scenes - 2

    fade_duration = 0.2  # 빠른 컷을 위해 페이드 줄임
    clips = []
    current_time = 0

    # === SFX 타이밍 기록용 ===
    sfx_timestamps = {
        "impact": 0.0,       # 후킹 시점
        "whoosh_times": [],   # 장면 전환마다
        "ding": None,         # 결론 시점
    }

    for i, scene in enumerate(scenes):
        duration = scene["duration"] * ratio
        path = scene_paths[i] if i < len(scene_paths) else scene_paths[-1]

        # 영상 파일이면 VideoFileClip, 이미지면 ImageClip (폴백)
        if path.endswith(".mp4"):
            bg = VideoFileClip(path).resized((WIDTH, HEIGHT))
            if bg.duration < duration:
                slow_factor = bg.duration / duration
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

        # 빠른 크로스페이드 (effects를 한번에 전달하여 덮어쓰기 방지)
        fade_effects = []
        if i > 0:
            fade_effects.append(vfx.CrossFadeIn(fade_duration))
        if i < total_scenes - 1:
            fade_effects.append(vfx.CrossFadeOut(fade_duration))
        if fade_effects:
            bg = bg.with_effects(fade_effects)

        text_img_path = _create_text_image(scene["text"], run_id, i, total_scenes)
        text_overlay = ImageClip(text_img_path).with_duration(bg.duration)

        composite = CompositeVideoClip([bg, text_overlay], size=(WIDTH, HEIGHT))
        composite = composite.with_start(current_time)
        clips.append(composite)

        # SFX 타이밍 기록
        if i > 0:
            sfx_timestamps["whoosh_times"].append(current_time)
        if i == total_scenes - 2:
            sfx_timestamps["ding"] = current_time

        if i < total_scenes - 1:
            current_time += bg.duration - fade_duration
        else:
            current_time += bg.duration

        # 카운트다운 삽입
        if i == countdown_insert_idx - 1:
            countdown_frames = _create_countdown_frames(run_id)
            for ci, frame_path in enumerate(countdown_frames):
                cd_clip = ImageClip(frame_path).with_duration(1.0)
                if ci == 0:
                    cd_clip = cd_clip.with_effects([vfx.CrossFadeIn(0.15)])
                cd_clip = cd_clip.with_start(current_time)
                clips.append(cd_clip)
                current_time += 1.0
            sfx_timestamps["countdown_start"] = current_time - countdown_duration

    # === 오디오 믹싱: TTS + BGM + SFX ===
    audio_clips = []

    # 1. TTS (메인 음성)
    audio_clips.append(tts_audio)

    # 2. BGM (낮은 볼륨)
    try:
        bgm_path = generate_bgm_loop(duration=total_video_duration + 5)
        bgm = AudioFileClip(bgm_path).with_effects([afx.MultiplyVolume(0.15)])
        if bgm.duration > total_video_duration:
            bgm = bgm.subclipped(0, total_video_duration)
        audio_clips.append(bgm)
    except Exception as e:
        logger.warning(f"BGM 로드 실패 (영상은 정상 생성): {e}")

    # 3. SFX
    try:
        sfx = get_or_generate_sfx()

        # 후킹 임팩트 (0초)
        impact = AudioFileClip(sfx["impact"]).with_effects([afx.MultiplyVolume(0.5)])
        impact = impact.with_start(0.0)
        audio_clips.append(impact)

        # 장면 전환 whoosh
        for wt in sfx_timestamps["whoosh_times"][:5]:
            whoosh = AudioFileClip(sfx["whoosh"]).with_effects([afx.MultiplyVolume(0.3)])
            whoosh = whoosh.with_start(wt)
            audio_clips.append(whoosh)

        # 카운트다운 틱
        if "countdown_start" in sfx_timestamps:
            for tick_i in range(3):
                tick = AudioFileClip(sfx["tick"]).with_effects([afx.MultiplyVolume(0.6)])
                tick = tick.with_start(sfx_timestamps["countdown_start"] + tick_i)
                audio_clips.append(tick)

        # 결론 딩
        if sfx_timestamps["ding"] is not None:
            ding = AudioFileClip(sfx["ding"]).with_effects([afx.MultiplyVolume(0.5)])
            ding = ding.with_start(sfx_timestamps["ding"])
            audio_clips.append(ding)

    except Exception as e:
        logger.warning(f"SFX 로드 실패 (영상은 정상 생성): {e}")

    # 최종 합성
    mixed_audio = CompositeAudioClip(audio_clips)
    final = CompositeVideoClip(clips, size=(WIDTH, HEIGHT)).with_duration(total_video_duration)
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

    tts_audio.close()
    for ac in audio_clips:
        try:
            ac.close()
        except Exception:
            pass
    for clip in clips:
        clip.close()
    final.close()

    return output_path
