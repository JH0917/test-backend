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

    # 매 영상마다 다른 톤과 구성을 랜덤 선택
    tones = [
        "냉소적이고 시니컬한 톤 — '이걸 진지하게 고민한다고?' 느낌",
        "열정적이고 흥분된 톤 — '이건 진짜 역대급 질문!' 느낌",
        "학술적이지만 웃긴 톤 — 논문 발표처럼 근거를 대는데 결론이 웃김",
        "친근한 형/누나 톤 — 동생한테 설명하듯 쉽게",
        "도발적인 톤 — '이거 못 고르면 인생 다시 사세요' 느낌",
    ]
    structures = [
        "A 분석 → B 반박 → 결론 (기본 구조)",
        "결론 먼저 선언 → 근거 제시 → 반대편 반박 → 확인사살",
        "B부터 먼저 깔아놓고 → A의 반전 매력으로 뒤집기 → 결론",
    ]
    tone = random.choice(tones)
    structure = random.choice(structures)

    prompt = f"""당신은 유튜브 쇼츠 밸런스게임 콘텐츠 스크립트 작가입니다.

⚠️ 이번 밸런스게임 질문 (반드시 이 질문으로 스크립트를 작성할 것!):
{detail}

⚠️ 이번 에피소드 번호: #{episode_number} (제목에 반드시 포함할 것. 예: "#{episode_number} 치킨vs피자 3초 안에 골라봐")
⚠️ 직전 영상 제목: "{last_title}" — 이와 다른 제목 패턴을 사용할 것!

⚠️ 이번 영상 톤: {tone}
⚠️ 이번 영상 구성: {structure}

## 채널 컨셉
"밸런스게임 결론내기" — 누구나 한번쯤 고민해본 황금 밸런스게임 질문에 나름의 논리와 유머로 결론을 내주는 채널.

## 스크립트 구조 (필수 준수)

### 1단계: 질문 던지기 — 후킹 (2~3초)
- 첫 문장은 반드시 시청자를 멈추게 하는 후킹으로 시작할 것!
- ⚠️ 이번 영상에 사용할 후킹 패턴 (반드시 이 패턴으로!): {random.choice([
        '통계형: "한국인 87%가 A를 고른다는데..."',
        '도발형: "이거 고르면 진짜 이상한 사람입니다"',
        '공감형: "솔직히 이건 고민 1초도 안 걸려요"',
        '충격형: "이거 잘못 고르면 인생 끝입니다"',
        '질문형: "자 여러분 딱 3초 줄게요. 골라보세요"',
        '대화형: "야 이거 친구한테 물어봤는데 싸울뻔했거든요"',
        '고백형: "저도 처음엔 A인 줄 알았습니다. 근데요."',
    ])}
- 후킹 뒤에 반드시 "결론 내드립니다."로 이어갈 것
- "결론 내드립니다"는 채널 정체성 캐치프레이즈. 절대 빠뜨리지 마세요.

### 2단계: 정답 쪽(A) 핵심 분석 (15~18초, 나레이션의 약 45%)
- 결론으로 선택할 쪽을 임팩트 있게 설명
- 가장 강력한 근거 3~4개
- 구체적인 상황 묘사 + 유머 포인트
- 군더더기 없이 핵심만, 하지만 충분히 설득력 있게

### 3단계: 반대쪽(B) 언급 + 즉시 반박 (8~10초, 나레이션의 약 25%)
- "근데 B는요?" 하면서 잠깐 B쪽 이야기
- 바로 반박 ("근데 잘 생각해보세요")
- B의 매력적인 포인트 인정 후 치명적 단점 제시

### 4단계: 결론 선언 (3~4초)
- "결론." 하고 확실하게 선택
- 한 줄로 임팩트 있는 최종 근거

### 5단계: 댓글 유도 (2~3초)
- 반드시 "여러분 선택은?" 으로 마무리
- 이 마무리 멘트도 채널 정체성. 절대 변경하지 마세요.

## 참고 스크립트 (이 리듬감과 구조를 따를 것! 소재는 그대로 쓰지 말 것!)

참고1 (똥맛 카레 vs 카레맛 똥):
"똥맛 카레 vs 카레맛 똥, 결론 내드립니다. 자 일단 똥맛 카레부터 봅시다. 보이는 건 카레거든요. 식당에서 먹어도 아무도 모릅니다. 누가 봐도 그냥 카레예요. 문제는 맛이죠. 한 숟갈 뜨는 순간 입 안에서 재앙이 펼쳐집니다. 근데요. 참을 수는 있어요. 코 막고 삼키면 됩니다. 감기 걸렸을 때 약 먹는 거랑 비슷한 거예요. 그리고 결정적으로 먹고 나서 인스타에 올릴 수 있거든요. 카레 먹었다고. 아무도 모릅니다. 자 카레맛 똥은요? 맛은 완벽합니다. 향신료 향이 솔솔 나요. 근데 잘 생각해보세요. 그게 똥입니다. 눈 감고 먹으면 된다고요? 식감이 다릅니다. 그리고 누가 보면요? 끝납니다. 인생이. 결론. 똥맛 카레입니다. 반박 불가. 여러분 선택은?"

참고2 (투명인간 vs 시간 정지):
"투명인간이 될래 시간을 멈출래. 결론 내드립니다. 시간 정지. 이건 사기입니다. 일단 늦잠 자도 지각이 없어요. 시간을 멈추면 되니까요. 시험 때 옆사람 답지 보는 건 기본이고요. 마감 전날 밤에 시간 멈추고 일주일치 작업 하면 됩니다. 상사한테 혼나는 중에 멈추고 도망가도 돼요. 아 물론 단점은 있습니다. 시간을 멈추면 나만 늙거든요. 혼자 막 10년 더 살 수도 있어요. 근데 투명인간은요? 처음 3일은 좋죠. 근데 잘 생각해보세요. 옷을 입으면 옷만 둥둥 떠다닙니다. 겨울에 밖을 못 나가요. 병원도 못 갑니다. 의사가 놀라서 도망가거든요. 결론. 시간 정지입니다. 10년 더 늙어도 지각 안 하는 게 더 중요하거든요. 여러분 선택은?"

참고3 (1억 vs 차은우 외모):
"다시 태어난다면 100억 부자 vs 차은우 외모. 결론 내드립니다. 야 이거 친구한테 물어봤는데 싸울뻔했거든요. 일단 100억부터 봅시다. 100억이면요. 강남 아파트 사고도 남습니다. 매일 한우 먹어도 100년은 갑니다. 근데 차은우 얼굴이면요? 걸어만 다녀도 광고 들어옵니다. 한 달이면 억 단위로 벌어요. 잠깐. 그러면 결국 돈도 벌잖아? 근데 100억은 확정입니다. 차은우 얼굴은요. 연예계 안 하면 그냥 잘생긴 백수예요. 결론. 100억입니다. 잘생긴 거 한 달이면 질립니다. 100억은 평생 안 질려요. 여러분 선택은?"

참고4 (평생 여름 vs 평생 겨울) — 결론 먼저 구조:
"결론부터 말합니다. 평생 여름입니다. 이유요? 겨울에 밖에 나가보세요. 코가 떨어질 것 같거든요. 패딩 입고 목도리 하고 장갑 끼고. 준비만 20분입니다. 여름은요? 반팔 하나면 끝이에요. 에어컨 틀면 천국이고요. 근데 겨울파들은 이래요. 여름엔 못 벗잖아요. 맞아요. 근데 잘 생각해보세요. 겨울엔 아무리 입어도 추워요. 여름엔 물 뿌리면 됩니다. 반박 불가. 여러분 선택은?"

참고5 (160cm 바퀴벌레 vs 1cm 강동원) — 도발형 톤:
"이거 고르면 진짜 이상한 사람입니다. 160cm 바퀴벌레랑 같이 살기 vs 1cm 강동원이랑 같이 살기. 결론 내드립니다. 자 일단 160cm 바퀴벌레요. 사람 키만 한 바퀴벌레입니다. 상상이 됩니까? 현관문 열었는데 서 있어요. 눈 마주칩니다. 이건 공포영화가 아니라 일상입니다. 1cm 강동원은요? 귀엽잖아요. 책상 위에 올려놓으면 됩니다. 밥도 쌀 한 톨이면 돼요. 유지비 제로입니다. 근데 강동원이잖아요. 작아도 강동원입니다. 결론. 1cm 강동원. 바퀴벌레는 크기가 문제가 아닙니다. 존재 자체가 공포거든요. 여러분 선택은?"

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
- 총 35~45초 영상 (나레이션 300~400자)
- 8개 장면으로 구성 (빠른 컷 전환!)
- 각 장면 3~5초 (짧고 빠르게!)
- 각 장면에 화면에 표시할 큰 자막 텍스트(10자 이내, 핵심 키워드 위주)
- 각 장면에 DALL-E용 배경 설명 (영어, 실사 사진 스타일, 35mm 필름 느낌의 부드러운 톤, 자연스러운 표정, 장면마다 다른 구도)
- 각 장면에 Runway 영상 변환용 모션 설명 (영어, 장면 안에서 일어나는 구체적 동작/움직임 묘사)
- 1번 장면: 질문 제시 (image_prompt_a: A 선택지 이미지, image_prompt_b: B 선택지 이미지 — 분할화면용)
- 2~4번 장면: 정답 쪽(A) 핵심 분석 (3장면, 빠르게!)
- 5~6번 장면: 반대쪽(B) 반박 (2장면)
- 7번 장면: 결론 선언 (image_prompt는 "Pure black background"로 고정)
- 8번 장면: 댓글 유도 "여러분 선택은?" (image_prompt는 "Pure black background"로 고정)
- ⚠️ 7번과 8번 사이에 3초 카운트다운이 자동 삽입됩니다 (스크립트에는 포함하지 마세요)

## 제목 규칙
- "최종 결론", "완벽 정리" 같은 결론 암시 부제 금지 (클릭 동기를 약화시킴)
- ⚠️ "당신의 선택은?" 패턴을 남발하지 말 것! 아래 패턴 중 랜덤으로 골라 사용:
  * 도발형: "이거 고르면 진짜 이상한 사람" / "반박 불가 결론"
  * 통계형: "99%가 틀리는 선택" / "한국인 73%가 고른 답"
  * 도전형: "3초 안에 골라봐" / "이거 맞추면 IQ 130"
  * 충격형: "결과가 충격적" / "마지막에 반전 있음"
  * 공감형: "솔직히 이건 답 나왔잖아" / "이것도 고민하는 사람 있어?"
  * 시리즈형: "너라면?" / "골라봐"
- 선택지를 구체적으로: "과거 여행" 대신 "2009년 비트코인 사러 가기"처럼 상황 묘사
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
    "narration": "전체 나레이션 (구어체. 300~400자. 반드시 한쪽을 선택하는 결론 포함)",
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
    if not (280 <= narration_len <= 450):
        logger.warning(f"나레이션 {narration_len}자 (기대: 300~400자)")

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
        bgm = AudioFileClip(bgm_path).with_effects([vfx.MultiplyVolume(0.15)])
        if bgm.duration > total_video_duration:
            bgm = bgm.subclipped(0, total_video_duration)
        audio_clips.append(bgm)
    except Exception as e:
        logger.warning(f"BGM 로드 실패 (영상은 정상 생성): {e}")

    # 3. SFX
    try:
        sfx = get_or_generate_sfx()

        # 후킹 임팩트 (0초)
        impact = AudioFileClip(sfx["impact"]).with_effects([vfx.MultiplyVolume(0.5)])
        impact = impact.with_start(0.0)
        audio_clips.append(impact)

        # 장면 전환 whoosh
        for wt in sfx_timestamps["whoosh_times"][:5]:
            whoosh = AudioFileClip(sfx["whoosh"]).with_effects([vfx.MultiplyVolume(0.3)])
            whoosh = whoosh.with_start(wt)
            audio_clips.append(whoosh)

        # 카운트다운 틱
        if "countdown_start" in sfx_timestamps:
            for tick_i in range(3):
                tick = AudioFileClip(sfx["tick"]).with_effects([vfx.MultiplyVolume(0.6)])
                tick = tick.with_start(sfx_timestamps["countdown_start"] + tick_i)
                audio_clips.append(tick)

        # 결론 딩
        if sfx_timestamps["ding"] is not None:
            ding = AudioFileClip(sfx["ding"]).with_effects([vfx.MultiplyVolume(0.5)])
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
