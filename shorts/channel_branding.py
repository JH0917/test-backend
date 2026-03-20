import os
import json
import asyncio
import logging
import tempfile
import uuid
import httpx
import anthropic
import openai
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger("shorts.channel_branding")

import shorts.trend_analyzer as trend_module
from shorts.trend_analyzer import _parse_json_response

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
MODEL = "claude-opus-4-20250514"


async def generate_channel_branding() -> dict:
    """현재 주제에 맞는 채널명, 설명, 배너/프로필 이미지를 생성한다."""
    if not trend_module.current_topic:
        raise ValueError("주제가 설정되지 않았습니다. analyze를 먼저 실행하세요.")

    branding = await _generate_branding_with_ai(
        trend_module.current_topic,
        trend_module.current_topic_detail,
    )

    banner_path = await _generate_banner_image(branding["channel_name"], branding["banner_prompt"])
    profile_path = await _generate_profile_image(branding["channel_name"], branding["profile_prompt"])

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
3. 배너 이미지 프롬프트: DALL-E용 영어 프롬프트. 채널 주제를 표현하는 귀여운 만화/일러스트 스타일. 가로형 배경 이미지. 텍스트 없이.
4. 프로필 이미지 프롬프트: DALL-E용 영어 프롬프트. 채널을 상징하는 귀여운 캐릭터 또는 아이콘. 심플하고 눈에 띄는 디자인. 텍스트 없이.

참고 채널명 예시: 사물의 경고, 유유미미, 침착맨, 지식한입, 1분과학

다음 JSON 형식으로만 응답하세요:
{{
    "channel_name": "채널명",
    "channel_description": "채널 소개 한 줄",
    "banner_prompt": "English DALL-E prompt for banner image",
    "profile_prompt": "English DALL-E prompt for profile icon"
}}"""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = await asyncio.to_thread(
        client.messages.create,
        model=MODEL,
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}],
    )

    return _parse_json_response(message.content[0].text)


async def _generate_dalle_image(prompt: str, size: str) -> str | None:
    """DALL-E 3로 이미지를 생성한다."""
    try:
        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        response = await asyncio.to_thread(
            client.images.generate,
            model="dall-e-3",
            prompt=prompt,
            size=size,
            quality="standard",
            n=1,
        )
        image_url = response.data[0].url

        run_id = uuid.uuid4().hex[:8]
        path = os.path.join(tempfile.gettempdir(), f"dalle_{run_id}.png")
        async with httpx.AsyncClient(timeout=60) as http_client:
            resp = await http_client.get(image_url)
            with open(path, "wb") as f:
                f.write(resp.content)
        return path
    except Exception as e:
        logger.error(f"DALL-E 이미지 생성 실패: {e}")
        return None


async def _generate_banner_image(channel_name: str, dalle_prompt: str) -> str:
    """DALL-E로 배너 이미지를 생성한다. (1792x1024)"""
    full_prompt = f"{dalle_prompt}. Cute cartoon illustration style, vibrant pastel colors, wide landscape composition for YouTube channel banner. No text in the image."
    path = await _generate_dalle_image(full_prompt, "1792x1024")

    if path:
        # 채널명 텍스트 오버레이
        img = Image.open(path).convert("RGBA")
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        font = _load_font(80)

        bbox = draw.textbbox((0, 0), channel_name, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        w, h = img.size
        x = (w - text_w) // 2
        y = h - text_h - 80

        # 반투명 배경 박스
        pad = 30
        draw.rounded_rectangle(
            [x - pad, y - pad, x + text_w + pad, y + text_h + pad],
            radius=20,
            fill=(255, 255, 255, 180),
        )
        draw.text((x, y), channel_name, font=font, fill=(40, 40, 60, 255))

        result = Image.alpha_composite(img, overlay).convert("RGB")
        result.save(path)
        return path

    # 폴백: 단색 배경
    return _create_fallback_banner(channel_name)


async def _generate_profile_image(channel_name: str, dalle_prompt: str) -> str:
    """DALL-E로 프로필 이미지를 생성한다. (1024x1024)"""
    full_prompt = f"{dalle_prompt}. Cute cartoon style icon, vibrant colors, simple design, centered composition, suitable for a small circular profile picture. No text in the image."
    path = await _generate_dalle_image(full_prompt, "1024x1024")

    if path:
        return path

    # 폴백: 단색 배경 + 텍스트
    return _create_fallback_profile(channel_name)


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


def _create_fallback_banner(channel_name: str) -> str:
    """DALL-E 실패 시 단색 배너를 생성한다."""
    w, h = 2560, 1440
    img = Image.new("RGB", (w, h), (45, 45, 65))
    draw = ImageDraw.Draw(img)
    font = _load_font(120)
    bbox = draw.textbbox((0, 0), channel_name, font=font)
    text_w = bbox[2] - bbox[0]
    x = (w - text_w) // 2
    y = h // 2 - 60
    draw.text((x, y), channel_name, font=font, fill=(255, 255, 255))
    run_id = uuid.uuid4().hex[:8]
    path = os.path.join(tempfile.gettempdir(), f"banner_fallback_{run_id}.png")
    img.save(path)
    return path


def _create_fallback_profile(channel_name: str) -> str:
    """DALL-E 실패 시 단색 프로필을 생성한다."""
    size = 800
    img = Image.new("RGB", (size, size), (45, 45, 65))
    draw = ImageDraw.Draw(img)
    font = _load_font(100)
    short = channel_name[:2]
    bbox = draw.textbbox((0, 0), short, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (size - text_w) // 2
    y = (size - text_h) // 2
    draw.text((x, y), short, font=font, fill=(255, 255, 255))
    run_id = uuid.uuid4().hex[:8]
    path = os.path.join(tempfile.gettempdir(), f"profile_fallback_{run_id}.png")
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

    # 4. 프로필 이미지는 API로 변경 불가 — 경로만 안내
    results["channel_name_note"] = "채널명은 YouTube Studio에서 직접 변경해야 합니다"
    results["suggested_name"] = channel_name
    results["profile_image_note"] = "프로필 이미지는 YouTube Studio에서 직접 설정해야 합니다"
    results["profile_image_path"] = profile_path

    return results
