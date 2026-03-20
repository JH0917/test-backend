import os
import json
import asyncio
import tempfile
import uuid
import httpx
import anthropic
from PIL import Image, ImageDraw, ImageFont, ImageFilter

import shorts.trend_analyzer as trend_module
from shorts.trend_analyzer import _parse_json_response

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")
MODEL = "claude-opus-4-20250514"


async def generate_channel_branding() -> dict:
    """현재 주제에 맞는 채널명, 설명, 배너/프로필 이미지를 생성한다."""
    if not trend_module.current_topic:
        raise ValueError("주제가 설정되지 않았습니다. analyze를 먼저 실행하세요.")

    branding = await _generate_branding_with_ai(
        trend_module.current_topic,
        trend_module.current_topic_detail,
    )

    bg_image = await _fetch_branding_image(branding["search_keyword"])
    banner_path = _create_banner_image(branding["channel_name"], bg_image)
    profile_path = _create_profile_image(branding["channel_name"], bg_image)

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
3. 배경 이미지 검색 키워드: 채널 분위기에 맞는 영어 키워드 1개 (Pexels 검색용)

참고 채널명 예시: 사물의 경고, 유유미미, 침착맨, 지식한입, 1분과학

다음 JSON 형식으로만 응답하세요:
{{
    "channel_name": "채널명",
    "channel_description": "채널 소개 한 줄",
    "search_keyword": "english keyword"
}}"""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = await asyncio.to_thread(
        client.messages.create,
        model=MODEL,
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )

    return _parse_json_response(message.content[0].text)


async def _fetch_branding_image(keyword: str) -> str | None:
    """Pexels에서 브랜딩용 이미지를 1장 가져온다."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                "https://api.pexels.com/v1/search",
                headers={"Authorization": PEXELS_API_KEY},
                params={"query": keyword, "per_page": 1, "orientation": "landscape"},
            )
            resp.raise_for_status()
            photos = resp.json().get("photos", [])
            if not photos:
                return None

            img_resp = await client.get(photos[0]["src"]["large2x"])
            run_id = uuid.uuid4().hex[:8]
            path = os.path.join(tempfile.gettempdir(), f"branding_bg_{run_id}.jpg")
            with open(path, "wb") as f:
                f.write(img_resp.content)
            return path
    except Exception:
        return None


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


def _create_banner_image(channel_name: str, bg_image_path: str | None) -> str:
    """배너 이미지를 생성한다. (2560x1440)"""
    w, h = 2560, 1440

    if bg_image_path and os.path.exists(bg_image_path):
        img = Image.open(bg_image_path).convert("RGB")
        img = img.resize((w, h), Image.LANCZOS)
        img = img.filter(ImageFilter.GaussianBlur(radius=3))
        # 어두운 오버레이
        overlay = Image.new("RGBA", (w, h), (0, 0, 0, 140))
        img = Image.composite(Image.new("RGB", (w, h), (0, 0, 0)), img, overlay.split()[3])
    else:
        img = Image.new("RGB", (w, h), (25, 25, 35))

    draw = ImageDraw.Draw(img)
    font = _load_font(120)

    bbox = draw.textbbox((0, 0), channel_name, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (w - text_w) // 2
    y = (h - text_h) // 2

    # 텍스트 그림자 + 본문
    draw.text((x + 4, y + 4), channel_name, font=font, fill=(0, 0, 0))
    draw.text((x, y), channel_name, font=font, fill=(255, 255, 255))

    run_id = uuid.uuid4().hex[:8]
    path = os.path.join(tempfile.gettempdir(), f"channel_banner_{run_id}.png")
    img.save(path)
    return path


def _create_profile_image(channel_name: str, bg_image_path: str | None) -> str:
    """프로필 이미지를 생성한다. (800x800)"""
    size = 800

    if bg_image_path and os.path.exists(bg_image_path):
        img = Image.open(bg_image_path).convert("RGB")
        # 정사각형 크롭 (중앙)
        src_w, src_h = img.size
        crop_size = min(src_w, src_h)
        left = (src_w - crop_size) // 2
        top = (src_h - crop_size) // 2
        img = img.crop((left, top, left + crop_size, top + crop_size))
        img = img.resize((size, size), Image.LANCZOS)
        img = img.filter(ImageFilter.GaussianBlur(radius=2))
        # 어두운 오버레이
        overlay = Image.new("RGBA", (size, size), (0, 0, 0, 120))
        img = Image.composite(Image.new("RGB", (size, size), (0, 0, 0)), img, overlay.split()[3])
    else:
        img = Image.new("RGB", (size, size), (25, 25, 35))

    draw = ImageDraw.Draw(img)
    font = _load_font(100)

    # 채널명을 2줄로 나누기
    if len(channel_name) > 4:
        mid = len(channel_name) // 2
        lines = [channel_name[:mid], channel_name[mid:]]
    else:
        lines = [channel_name]

    center = size // 2
    y_offset = center - (len(lines) * 60)
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        text_w = bbox[2] - bbox[0]
        x = (size - text_w) // 2
        draw.text((x + 3, y_offset + 3), line, font=font, fill=(0, 0, 0))
        draw.text((x, y_offset), line, font=font, fill=(255, 255, 255))
        y_offset += 120

    run_id = uuid.uuid4().hex[:8]
    path = os.path.join(tempfile.gettempdir(), f"channel_profile_{run_id}.png")
    img.save(path)
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

    # 3. 프로필 이미지는 API로 변경 불가 — 경로만 안내
    results["channel_name_note"] = "채널명은 YouTube Studio에서 직접 변경해야 합니다"
    results["suggested_name"] = channel_name
    results["profile_image_note"] = "프로필 이미지는 YouTube Studio에서 직접 설정해야 합니다"
    results["profile_image_path"] = profile_path

    return results
