import os
import json
import asyncio
import tempfile
import uuid
import anthropic
from PIL import Image, ImageDraw, ImageFont

import shorts.trend_analyzer as trend_module
from shorts.trend_analyzer import _parse_json_response

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
MODEL = "claude-opus-4-20250514"


async def generate_channel_branding() -> dict:
    """현재 주제에 맞는 채널명, 설명, 프로필 이미지를 생성한다."""
    if not trend_module.current_topic:
        raise ValueError("주제가 설정되지 않았습니다. analyze를 먼저 실행하세요.")

    branding = await _generate_branding_with_ai(
        trend_module.current_topic,
        trend_module.current_topic_detail,
    )

    image_path = _create_channel_image(branding["channel_name"])

    branding["image_path"] = image_path
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


def _create_channel_image(channel_name: str) -> str:
    """채널명으로 프로필 이미지를 생성한다. (800x800)"""
    size = 800
    img = Image.new("RGB", (size, size), (25, 25, 35))
    draw = ImageDraw.Draw(img)

    # 한글 폰트
    font_paths = [
        "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    ]
    font_large = None
    for fp in font_paths:
        if os.path.exists(fp):
            font_large = ImageFont.truetype(fp, 120)
            break
    if font_large is None:
        font_large = ImageFont.load_default()

    # 배경 원형 그라데이션 효과
    center = size // 2
    for r in range(300, 0, -3):
        ratio = r / 300
        color = (
            int(80 + 120 * (1 - ratio)),
            int(40 + 80 * (1 - ratio)),
            int(180 + 60 * (1 - ratio)),
        )
        draw.ellipse(
            [center - r, center - r, center + r, center + r],
            fill=color,
        )

    # 채널명 텍스트 (2줄로 나눌 수 있게)
    lines = []
    if len(channel_name) > 4:
        mid = len(channel_name) // 2
        lines = [channel_name[:mid], channel_name[mid:]]
    else:
        lines = [channel_name]

    y_offset = center - (len(lines) * 70)
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font_large)
        text_w = bbox[2] - bbox[0]
        x = (size - text_w) // 2
        # 텍스트 그림자
        draw.text((x + 3, y_offset + 3), line, font=font_large, fill=(0, 0, 0, 180))
        draw.text((x, y_offset), line, font=font_large, fill=(255, 255, 255))
        y_offset += 130

    run_id = uuid.uuid4().hex[:8]
    path = os.path.join(tempfile.gettempdir(), f"channel_profile_{run_id}.png")
    img.save(path)
    return path


async def update_youtube_channel(channel_name: str, channel_description: str, image_path: str) -> dict:
    """YouTube 채널 이름, 설명, 이미지를 업데이트한다."""
    from shorts.youtube_uploader import _get_authenticated_service
    from googleapiclient.http import MediaFileUpload

    youtube = _get_authenticated_service()
    results = {}

    # 1. 채널 설명 업데이트
    try:
        channels = youtube.channels().list(part="brandingSettings", mine=True).execute()
        if channels.get("items"):
            channel = channels["items"][0]
            channel["brandingSettings"]["channel"]["description"] = channel_description
            youtube.channels().update(
                part="brandingSettings",
                body=channel,
            ).execute()
            results["description_updated"] = True
        else:
            results["description_updated"] = False
            results["description_error"] = "채널을 찾을 수 없습니다"
    except Exception as e:
        results["description_updated"] = False
        results["description_error"] = str(e)

    # 2. 채널 프로필 이미지 업로드 (배너)
    try:
        media = MediaFileUpload(image_path, mimetype="image/png")
        banner = youtube.channelBanners().insert(media_body=media).execute()
        youtube.channels().update(
            part="brandingSettings",
            body={
                "id": channels["items"][0]["id"],
                "brandingSettings": {
                    "image": {"bannerExternalUrl": banner["url"]},
                },
            },
        ).execute()
        results["banner_updated"] = True
    except Exception as e:
        results["banner_updated"] = False
        results["banner_error"] = str(e)

    results["channel_name_note"] = "채널명은 YouTube Studio에서 직접 변경해야 합니다"
    results["suggested_name"] = channel_name

    return results
