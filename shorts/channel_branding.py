import os
import json
import asyncio
import tempfile
import uuid
import math
import random
import httpx
import anthropic
from PIL import Image, ImageDraw, ImageFont, ImageFilter

import shorts.trend_analyzer as trend_module
from shorts.trend_analyzer import _parse_json_response

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")
MODEL = "claude-opus-4-20250514"

# 파스텔 컬러 팔레트
PASTEL_PALETTES = [
    {"bg1": (255, 182, 193), "bg2": (186, 225, 255), "accent": (255, 218, 185)},  # 핑크-블루
    {"bg1": (200, 230, 201), "bg2": (255, 245, 157), "accent": (255, 204, 128)},  # 민트-옐로
    {"bg1": (225, 190, 231), "bg2": (179, 229, 252), "accent": (255, 183, 197)},  # 퍼플-스카이
    {"bg1": (255, 224, 178), "bg2": (248, 187, 208), "accent": (200, 230, 201)},  # 오렌지-핑크
    {"bg1": (178, 235, 242), "bg2": (225, 190, 231), "accent": (255, 245, 157)},  # 시안-퍼플
]


async def generate_channel_branding() -> dict:
    """현재 주제에 맞는 채널명, 설명, 배너/프로필 이미지를 생성한다."""
    if not trend_module.current_topic:
        raise ValueError("주제가 설정되지 않았습니다. analyze를 먼저 실행하세요.")

    branding = await _generate_branding_with_ai(
        trend_module.current_topic,
        trend_module.current_topic_detail,
    )

    palette = random.choice(PASTEL_PALETTES)
    banner_path = _create_banner_image(branding["channel_name"], palette)
    profile_path = _create_profile_image(branding["channel_name"], palette)

    branding["banner_path"] = banner_path
    branding["profile_path"] = profile_path
    return branding


async def _generate_branding_with_ai(topic: str, detail: str) -> dict:
    """Claude로 채널 브랜딩을 생성한다."""
    prompt = f"""유튜브 쇼츠 채널의 브랜딩을 만들어주세요.

콘텐츠 포맷: {topic}
첫 에피소드: {detail}

다음을 만들어주세요:
1. 채널명: 짧고 임팩트 있게 (2~4단어). 자극적이거나 유머러스해도 OK. 한눈에 뭐하는 채널인지 느낌이 와야 함.
2. 채널 설명: 한 줄로. 호기심 자극하는 톤. 구독 유도 느낌.

참고 채널명 예시: 사물의 경고, 유유미미, 침착맨, 지식한입, 1분과학

다음 JSON 형식으로만 응답하세요:
{{
    "channel_name": "채널명",
    "channel_description": "채널 소개 한 줄"
}}"""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = await asyncio.to_thread(
        client.messages.create,
        model=MODEL,
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )

    return _parse_json_response(message.content[0].text)


def _load_font(size: int):
    """한글 폰트를 로드한다."""
    font_paths = [
        "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    ]
    for fp in font_paths:
        if os.path.exists(fp):
            return ImageFont.truetype(fp, size)
    return ImageFont.load_default()


def _draw_pastel_gradient(img: Image.Image, color1: tuple, color2: tuple):
    """파스텔 그라데이션 배경을 그린다."""
    w, h = img.size
    for y in range(h):
        ratio = y / h
        r = int(color1[0] + (color2[0] - color1[0]) * ratio)
        g = int(color1[1] + (color2[1] - color1[1]) * ratio)
        b = int(color1[2] + (color2[2] - color1[2]) * ratio)
        for x in range(w):
            img.putpixel((x, y), (r, g, b))


def _draw_decorations(draw: ImageDraw.Draw, w: int, h: int, accent: tuple):
    """귀여운 장식 요소들을 그린다 (별, 원, 하트 등)."""
    random.seed(42)

    # 둥근 도트들
    for _ in range(15):
        x = random.randint(0, w)
        y = random.randint(0, h)
        size = random.randint(10, 40)
        alpha_color = (*accent, 120)
        draw.ellipse([x, y, x + size, y + size], fill=accent)

    # 작은 별 모양 (다이아몬드)
    for _ in range(8):
        cx = random.randint(0, w)
        cy = random.randint(0, h)
        s = random.randint(8, 20)
        draw.polygon([(cx, cy - s), (cx + s // 2, cy), (cx, cy + s), (cx - s // 2, cy)], fill="white")

    # 큰 반투명 원 (버블 느낌)
    for _ in range(5):
        cx = random.randint(0, w)
        cy = random.randint(0, h)
        r = random.randint(50, 150)
        light = tuple(min(c + 40, 255) for c in accent)
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=light, width=3)


def _draw_rounded_text_box(draw: ImageDraw.Draw, x: int, y: int, text_w: int, text_h: int, color: tuple):
    """둥근 텍스트 배경 박스를 그린다."""
    pad_x, pad_y = 50, 30
    draw.rounded_rectangle(
        [x - pad_x, y - pad_y, x + text_w + pad_x, y + text_h + pad_y],
        radius=30,
        fill=(*color, 200) if len(color) == 3 else color,
    )


def _create_banner_image(channel_name: str, palette: dict) -> str:
    """배너 이미지를 생성한다. (2560x1440) 파스텔 + 귀여운 스타일."""
    w, h = 2560, 1440
    img = Image.new("RGBA", (w, h), (255, 255, 255, 255))

    # 파스텔 그라데이션 배경
    bg = Image.new("RGB", (w, h))
    _draw_pastel_gradient(bg, palette["bg1"], palette["bg2"])
    img.paste(bg)

    draw = ImageDraw.Draw(img, "RGBA")

    # 장식 요소
    _draw_decorations(draw, w, h, palette["accent"])

    # 채널명 텍스트
    font = _load_font(140)
    bbox = draw.textbbox((0, 0), channel_name, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (w - text_w) // 2
    y = (h - text_h) // 2

    # 둥근 배경 박스
    _draw_rounded_text_box(draw, x, y, text_w, text_h, (255, 255, 255))

    # 텍스트 (진한 색)
    draw.text((x + 3, y + 3), channel_name, font=font, fill=(100, 100, 100, 80))
    draw.text((x, y), channel_name, font=font, fill=(60, 60, 80))

    # 서브 텍스트
    sub_font = _load_font(50)
    sub_text = "YouTube Shorts"
    sub_bbox = draw.textbbox((0, 0), sub_text, font=sub_font)
    sub_w = sub_bbox[2] - sub_bbox[0]
    sub_x = (w - sub_w) // 2
    sub_y = y + text_h + 60
    draw.text((sub_x, sub_y), sub_text, font=sub_font, fill=(120, 120, 140))

    result = img.convert("RGB")
    run_id = uuid.uuid4().hex[:8]
    path = os.path.join(tempfile.gettempdir(), f"channel_banner_{run_id}.png")
    result.save(path)
    return path


def _create_profile_image(channel_name: str, palette: dict) -> str:
    """프로필 이미지를 생성한다. (800x800) 파스텔 + 귀여운 스타일."""
    size = 800
    img = Image.new("RGBA", (size, size), (255, 255, 255, 255))

    # 파스텔 그라데이션 배경
    bg = Image.new("RGB", (size, size))
    _draw_pastel_gradient(bg, palette["bg1"], palette["bg2"])
    img.paste(bg)

    draw = ImageDraw.Draw(img, "RGBA")

    # 장식
    _draw_decorations(draw, size, size, palette["accent"])

    # 중앙에 큰 원형 배경
    center = size // 2
    circle_r = 280
    draw.ellipse(
        [center - circle_r, center - circle_r, center + circle_r, center + circle_r],
        fill=(255, 255, 255, 200),
    )

    # 채널명
    font = _load_font(90)
    if len(channel_name) > 4:
        mid = len(channel_name) // 2
        lines = [channel_name[:mid], channel_name[mid:]]
    else:
        lines = [channel_name]

    total_h = len(lines) * 110
    y_offset = center - total_h // 2
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        text_w = bbox[2] - bbox[0]
        x = (size - text_w) // 2
        draw.text((x + 2, y_offset + 2), line, font=font, fill=(150, 150, 150, 80))
        draw.text((x, y_offset), line, font=font, fill=(60, 60, 80))
        y_offset += 110

    result = img.convert("RGB")
    run_id = uuid.uuid4().hex[:8]
    path = os.path.join(tempfile.gettempdir(), f"channel_profile_{run_id}.png")
    result.save(path)
    return path


async def update_youtube_channel(channel_name: str, channel_description: str, banner_path: str, profile_path: str) -> dict:
    """YouTube 채널 설명과 배너를 업데이트한다."""
    from shorts.youtube_uploader import _get_authenticated_service
    from googleapiclient.http import MediaFileUpload

    youtube = _get_authenticated_service()
    results = {}

    # 1. 채널 정보 조회
    try:
        channels = youtube.channels().list(part="brandingSettings", mine=True).execute()
        channel = channels["items"][0] if channels.get("items") else None
    except Exception as e:
        results["error"] = f"채널 조회 실패: {e}"
        return results

    if not channel:
        results["error"] = "채널을 찾을 수 없습니다"
        return results

    # 2. 배너 이미지 업로드
    try:
        media = MediaFileUpload(banner_path, mimetype="image/png")
        banner = youtube.channelBanners().insert(media_body=media).execute()
        channel["brandingSettings"].setdefault("image", {})
        channel["brandingSettings"]["image"]["bannerExternalUrl"] = banner["url"]
        results["banner_uploaded"] = True
    except Exception as e:
        results["banner_updated"] = False
        results["banner_error"] = str(e)

    # 3. 채널 설명 + 배너 한 번에 업데이트
    try:
        channel["brandingSettings"]["channel"]["description"] = channel_description
        youtube.channels().update(
            part="brandingSettings",
            body=channel,
        ).execute()
        results["description_updated"] = True
        if results.get("banner_uploaded"):
            results["banner_updated"] = True
    except Exception as e:
        results["description_updated"] = False
        results["update_error"] = str(e)

    # 4. 프로필 이미지는 API로 변경 불가 — 경로만 안내
    results["channel_name_note"] = "채널명은 YouTube Studio에서 직접 변경해야 합니다"
    results["suggested_name"] = channel_name
    results["profile_image_note"] = "프로필 이미지는 YouTube Studio에서 직접 설정해야 합니다"
    results["profile_image_path"] = profile_path

    return results
