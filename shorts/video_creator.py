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

    # 매 영상마다 다른 톤과 숏폼 상황극 포맷을 랜덤 선택
    tones = [
        "단톡방에서 친구 놀리는 톤 — 짧고 얄밉게, 계속 태클 거는 느낌",
        "새벽에 커뮤니티 글 읽다가 급발진한 톤 — 과몰입 + 현실 비유",
        "예능 패널 톤 — 한 명은 말리고 한 명은 더 부추기는 느낌",
        "현실 시뮬레이션 톤 — 선택하는 순간 벌어지는 망한 장면을 보여줌",
        "억울한 변호사 톤 — 말도 안 되는 선택을 법정에서 변호하듯 웃김",
    ]
    formats = [
        "단톡방 박제형: 친구들이 A/B를 고르다가 한 명이 이상한 선택해서 단톡방이 터지는 구성",
        "긴급회의형: 인생대책회의처럼 시작해서 선택지 하나를 사회적으로 매장하는 구성",
        "법정재판형: A/B를 피고인처럼 세워놓고 증거사진 꺼내듯 몰아붙이는 구성",
        "생존시뮬레이터형: 선택 직후 1일차/3일차/30일차가 어떻게 망하는지 보여주는 구성",
        "소개팅참사형: 선택지가 소개팅/회사/가족 앞에서 들켰을 때를 상상하는 구성",
        "댓글전쟁형: 댓글창에서 A파/B파가 싸우는 모습을 대신 중계하다가 결론 내는 구성",
    ]
    hooks = [
        "잠깐. 이거 고르는 순간 단톡방에서 박제됩니다.",
        "이 질문은 밸런스게임이 아니라 인성검사입니다.",
        "친구한테 이거 물어봤다가 5분 동안 정적 흘렀습니다.",
        "둘 중 하나 고르면 인생 난이도가 갑자기 지옥불입니다.",
        "이건 고민하면 안 됩니다. 고민하는 순간 이미 위험합니다.",
        "댓글창 터질 질문 가져왔습니다. 진짜 싸우지 마세요.",
        "이 선택은 엄마 앞에서 설명 가능해야 인정입니다.",
    ]
    tone = random.choice(tones)
    format_style = random.choice(formats)
    hook = random.choice(hooks)

    prompt = f"""당신은 유튜브 쇼츠 밸런스게임 콘텐츠 스크립트 작가입니다.

⚠️ 이번 밸런스게임 질문 (반드시 이 질문으로 스크립트를 작성할 것!):
{detail}

⚠️ 이번 에피소드 번호: #{episode_number} (제목에 반드시 포함할 것. 예: "#{episode_number} 치킨vs피자 3초 안에 골라봐")
⚠️ 직전 영상 제목: "{last_title}" — 이와 다른 제목 패턴을 사용할 것!

⚠️ 이번 영상 톤: {tone}
⚠️ 이번 영상 포맷: {format_style}
⚠️ 첫 문장 후킹: "{hook}"

## 채널 컨셉
"밸런스게임 결론내기" — 선택지를 분석하는 채널이 아니라, 선택하는 순간 벌어지는 웃긴 참사를 보여주고 한쪽을 과감하게 찍어주는 채널.

## 핵심 변경: 분석문 금지, 숏폼 상황극으로 쓸 것
- 이 영상은 논리 발표가 아니라 "댓글창 터질 만한 상황극"입니다.
- 시청자가 웃는 지점은 근거가 아니라 "아 저건 진짜 망했다" 싶은 현실 장면입니다.
- 매 1~2문장마다 새로운 그림이 떠올라야 합니다. 같은 설명을 길게 끌지 마세요.
- "결론 내드립니다"는 1회만 사용하세요. 반복하면 재미가 죽습니다.

## 8컷 구조 (필수)
1. 훅: 반드시 "{hook}"로 시작하고 바로 질문을 던지기
2. A 선택 직후 벌어지는 첫 참사
3. A가 생각보다 괜찮아 보이는 반전
4. A의 치명적 웃긴 단점
5. B 선택 직후 벌어지는 더 큰 참사
6. B가 댓글창에서 옹호받는 이유
7. 카운트다운 직전 결론 떡밥: "3초 뒤에 찍습니다"
8. 결론 + 댓글 싸움 유도: 반드시 한쪽 선택, 마지막은 "여러분 선택은?"

## 재미 엔진 규칙
- 최소 4개 이상의 "구체적 현실 장면"을 넣으세요.
  예: 단톡방 캡처, 엄마가 방문 열고 봄, 회사 회식자리, 소개팅 첫 만남, 지하철 옆자리, 편의점 알바 표정, 친구가 릴스에 올림.
- 한쪽을 깔 때는 추상어 금지. "불편하다" 말고 "단톡방 이름이 너 때문에 바뀐다"처럼 장면으로 말하세요.
- 웃긴 비유를 최소 3개 넣으세요.
  예: "인생 난이도 DLC", "사회적 사망 버튼", "알고리즘이 부모님께 추천하는 재앙".
- 댓글이 갈릴 포인트를 일부러 남기세요. "A파 지금 화났죠?" 같은 멘트 OK.
- 과몰입은 허용하지만 욕설/혐오/성적 표현은 금지.

## 절대 금지 표현
- "자 일단", "근데 잘 생각해보세요", "핵심은", "가장 강력한 근거", "정답 쪽", "반대쪽"
- 교과서식 비교, 장황한 설명, 착한 결론, 양쪽 다 좋다는 마무리
- 가짜 통계 남발. 통계형 제목은 쓰지 말 것.

## 참고 스크립트 — 새 스타일

참고1 (랜덤 나라 vs 같은 방):
"잠깐. 이거 고르는 순간 여권이 아니라 멘탈이 먼저 찢깁니다. 매일 랜덤 나라에서 깨어나기 vs 평생 같은 방. 결론 내드립니다. 랜덤 나라요? 첫날은 낭만입니다. 눈 떴는데 파리. 오 좋다. 둘째 날은 사막. 셋째 날은 공항 노숙. 넷째 날부터 엄마가 전화합니다. 너 지금 어느 나라야? 본인도 모릅니다. 근데 같은 방은요. 처음엔 안정적이죠. 침대 있고 와이파이 있고. 근데 30일 지나면 벽지 무늬랑 대화합니다. 1년 지나면 방구석이 직장이고 여행지고 장례식장입니다. 3초 뒤에 찍습니다. 결론. 랜덤 나라. 적어도 인생이 로딩 화면은 아니잖아요. 같은 방파 지금 화났죠? 여러분 선택은?"

참고2 (검색기록 공개 vs 카톡 공개):
"이건 밸런스게임이 아니라 사회적 사망 버튼입니다. 검색기록 공개 vs 카톡 공개. 결론 내드립니다. 검색기록요? 민망합니다. 새벽 2시에 이상한 거 검색한 거 다 압니다. 근데 사람들은 하루면 잊어요. 문제는 카톡입니다. 카톡은 증거가 아니라 다큐멘터리예요. 친구 욕한 거, 전애인한테 쓴 장문, 엄마한테 거짓말한 시간까지 풀HD입니다. 단톡방에 올라가는 순간 이름이 '해명해'로 바뀝니다. 3초 뒤에 찍습니다. 결론. 검색기록 공개. 창피한 건 하루고 카톡은 인간관계 압수입니다. 카톡파 있으면 댓글로 변론하세요. 여러분 선택은?"

참고3 (100억 혼자 vs 가난한 사랑):
"댓글창 싸움 예약입니다. 100억 부자인데 평생 혼자 vs 가난하지만 사랑하는 사람. 결론 내드립니다. 사랑 좋죠. 근데 가난한 사랑은 월세날부터 장르가 바뀝니다. 로맨스인 줄 알았는데 생활고 스릴러예요. 치킨 한 마리에도 회의합니다. 반대로 100억 혼자는요? 외롭습니다. 근데 외로운 집이 80평입니다. 울어도 한강뷰 앞에서 울어요. 문제는 생일입니다. 케이크 초를 혼자 끕니다. 박수도 셀프예요. 3초 뒤에 찍습니다. 결론. 100억 혼자. 외로움은 힘든데 카드값 독촉은 더 무섭습니다. 사랑파 반박 받습니다. 여러분 선택은?"

## 톤 & 문체 규칙
- 한 문장 최대 28자. 숨 쉴 틈 없이 짧게.
- 문장 끝을 계속 "~거든요"로 반복하지 말 것. "끝.", "망했습니다.", "이건 압수.", "바로 박제."처럼 끊기.
- 설명보다 장면. 근거보다 짤감. 착함보다 댓글 유발.
- 반말/존댓말 섞기 OK. 단, 사람/집단 비하 금지.
- TTS가 읽었을 때 리듬이 살아야 함: 짧은 문장 3개 + 한 줄 펀치라인 패턴.

## 금지 사항
- ❌ 교훈적 마무리
- ❌ 양쪽 다 좋다는 애매한 결론
- ❌ 딱딱한 분석
- ❌ 욕설, 음란한 내용, 혐오 표현
- ❌ 실제 특정 개인을 조롱하는 표현

## 구성
- 총 28~38초 영상 (나레이션 240~340자)
- 8개 장면으로 구성 (빠른 컷 전환)
- 각 장면 2.5~4.5초
- 각 장면에 화면에 표시할 큰 자막 텍스트(10자 이내, 핵심 키워드 위주)
- 각 장면에 DALL-E용 배경 설명 (영어, 실사 사진 스타일, 35mm 필름 느낌의 부드러운 톤, 자연스러운 표정, 장면마다 다른 구도)
- 각 장면에 Runway 영상 변환용 모션 설명 (영어, 장면 안에서 일어나는 구체적 동작/움직임 묘사)
- 1번 장면: 질문 제시 (image_prompt_a: A 선택지 이미지, image_prompt_b: B 선택지 이미지 — 분할화면용)
- 2~6번 장면: 위 8컷 구조에 맞는 상황극 장면
- 7번 장면: 결론 떡밥 (image_prompt는 "Pure black background"로 고정)
- 8번 장면: 댓글 유도 "여러분 선택은?" (image_prompt는 "Pure black background"로 고정)
- ⚠️ 7번과 8번 사이에 3초 카운트다운이 자동 삽입됩니다 (스크립트에는 포함하지 마세요)

## 제목 규칙
- 결론을 제목에서 말하지 말 것. 클릭 이유가 사라집니다.
- 가짜 통계, IQ, 천재 테스트 금지. 촌스럽습니다.
- 아래 느낌으로 짧고 센 제목:
  * "이거 고르면 단톡방 박제됨"
  * "엄마 앞에서 설명 가능?"
  * "둘 중 하나면 인생 난이도 지옥"
  * "댓글창 싸움 예약"
  * "이 선택은 진짜 못 살린다"
- 선택지를 구체적으로 압축: "랜덤 나라 vs 같은 방", "검색기록 vs 카톡", "100억 혼자 vs 가난한 사랑"
- 직전 영상 제목과 다른 패턴을 사용할 것
- 40자 이내

## 설명 규칙
- 주제 키워드를 자연어로 포함 (SEO 최적화)
- 예: "치킨과 피자 중 하나를 평생 포기해야 한다면? 밸런스게임 결론!"
- 100자 이내

## 태그 규칙
- 처음 3개는 고정: "밸런스게임", "양자택일", "shorts"
- 나머지 5~7개는 해당 주제 키워드 (총 8~10개)

다음 JSON 형식으로만 응답하세요:
{{
    "title": "영상 제목 (참여 유도형, 선정적 표현 금지, 40자 이내)",
    "description": "영상 설명 (주제 키워드 포함, 100자 이내)",
    "tags": ["밸런스게임", "양자택일", "shorts", "결론내드립니다", "쇼츠", "주제태그1", "주제태그2", "주제태그3"],
    "narration": "전체 나레이션 (구어체. 240~340자. 반드시 한쪽을 선택하는 결론 포함)",
    "scenes": [
        {{
            "text": "큰 자막 텍스트 (10자 이내, 핵심 키워드)",
            "duration": 4.0,
            "image_prompt": "Editorial photograph of ... (English, 35mm film style)",
            "image_prompt_a": "(1번 장면만!) A 선택지 이미지 프롬프트 (English)",
            "image_prompt_b": "(1번 장면만!) B 선택지 이미지 프롬프트 (English)",
            "motion_prompt": "구체적 동작 묘사 (English, e.g. 'The man takes a bite and his eyes widen')"
        }}
    ]
}}

⚠️ 1번 장면에는 반드시 image_prompt_a와 image_prompt_b를 포함할 것! (분할화면용)
⚠️ 2~8번 장면에는 image_prompt만 사용할 것!"""

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
    if scene_count != 8:
        logger.warning(f"장면 수 {scene_count}개 (기대: 8개)")
    narration_len = len(script.get("narration", ""))
    if not (220 <= narration_len <= 370):
        logger.warning(f"나레이션 {narration_len}자 (기대: 240~340자)")
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
    """3, 2, 1 카운트다운 이미지 프레임을 생성한다."""
    frames = []
    colors = [(255, 80, 80), (255, 180, 50), (80, 255, 80)]  # 빨-주-초

    for i, (num, color) in enumerate(zip([3, 2, 1], colors)):
        img = Image.new("RGB", (WIDTH, HEIGHT), (15, 15, 25))
        draw = ImageDraw.Draw(img)

        # 큰 숫자
        font = _load_font(200)
        text = str(num)
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        x, y = (WIDTH - tw) // 2, (HEIGHT - th) // 2 - 50

        # 글로우 효과
        for offset in range(8, 0, -2):
            glow_color = (*color, 60)
            draw.text((x - offset, y), text, font=font, fill=color)
            draw.text((x + offset, y), text, font=font, fill=color)
        draw.text((x, y), text, font=font, fill=(255, 255, 255))

        # "결론 공개" 텍스트
        sub_font = _load_font(40)
        sub_text = "결론 공개까지..."
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
        "Cinematic editorial photograph, shot on 35mm Kodak Portra 400 film. "
        "Warm amber and teal color grading, soft golden hour lighting with gentle lens flare. "
        "Shallow depth of field, natural bokeh background. "
        "Real people in real settings, authentic expressions, not exaggerated or cartoonish. "
        "Consistent warm color palette: amber highlights, deep shadows, muted pastels. "
        "Clean composition, slightly desaturated skin tones, magazine-quality framing. "
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


def _create_text_image(text: str, run_id: str, index: int, total_scenes: int = 8,
                       width: int = WIDTH, height: int = HEIGHT) -> str:
    """PIL로 텍스트가 들어간 반투명 오버레이 이미지를 생성한다.
    자막 위치가 장면마다 다양하게 변경된다."""
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 첫 프레임은 더 큰 폰트, 마지막 2개도 큰 폰트 (결론/댓글유도)
    is_first = index == 0
    is_conclusion = index >= total_scenes - 2
    font_size = 80 if (is_first or is_conclusion) else 64
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

    padding = 28
    if is_first:
        # 첫 프레임: 강렬한 빨강 배경
        draw.rounded_rectangle(
            [x - padding, y - padding, x + text_w + padding, y + text_h + padding],
            radius=20, fill=(200, 30, 30, 220),
        )
    elif is_conclusion:
        # 결론/댓글 유도: 골드 배경
        draw.rounded_rectangle(
            [x - padding, y - padding, x + text_w + padding, y + text_h + padding],
            radius=20, fill=(180, 140, 20, 220),
        )
    else:
        # 일반 장면: 검정 반투명
        draw.rounded_rectangle(
            [x - padding, y - padding, x + text_w + padding, y + text_h + padding],
            radius=16, fill=(0, 0, 0, 180),
        )

    # 흰색 큰 글씨 + 테두리 효과
    for dx, dy in [(-2, -2), (-2, 2), (2, -2), (2, 2)]:
        draw.text((x + dx, y + dy), text, font=font, fill=(0, 0, 0, 200))
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

    # 카운트다운 3초를 포함한 전체 길이 계산
    countdown_duration = 3.0
    total_video_duration = tts_duration + countdown_duration

    # 장면별 시간 비율 계산 (카운트다운 제외)
    total_scene_duration = sum(s["duration"] for s in scenes)
    ratio = tts_duration / total_scene_duration if total_scene_duration > 0 else 1

    # 카운트다운 삽입 위치: 결론 장면(마지막에서 2번째) 직전
    countdown_insert_idx = max(total_scenes - 2, total_scenes // 2)

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
