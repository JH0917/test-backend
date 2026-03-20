import os
import re
import json
import asyncio
import httpx
import anthropic

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

MODEL = "claude-opus-4-20250514"

# 전역변수: 선정된 주제
current_topic = None
current_topic_detail = None

# 검색할 카테고리 (ID: 이름)
SEARCH_CATEGORIES = {
    "10": "음악",
    "20": "게임",
    "22": "일상/블로그",
    "23": "코미디",
    "24": "엔터테인먼트",
    "25": "뉴스",
    "26": "스타일",
    "27": "교육",
    "28": "과학기술",
}


async def analyze_youtube_trends() -> dict:
    """유튜브 트렌드를 분석하고 사람이 촬영하지 않고 만들 수 있는 쇼츠 주제를 선정한다."""
    global current_topic, current_topic_detail

    trending_data = await _fetch_trending_videos()
    topic = await _select_topic_with_ai(trending_data)

    current_topic = topic["topic"]
    current_topic_detail = topic["detail"]
    return topic


async def _fetch_trending_videos() -> list[dict]:
    """YouTube Data API로 한국 인기 동영상 200개 내외를 수집한다."""
    videos = []

    async with httpx.AsyncClient(timeout=30) as client:
        # 1) mostPopular 50개 (1 쿼터)
        resp = await client.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={
                "part": "snippet,statistics",
                "chart": "mostPopular",
                "regionCode": "KR",
                "maxResults": 50,
                "key": YOUTUBE_API_KEY,
            },
        )
        resp.raise_for_status()
        videos.extend(_parse_video_items(resp.json()))

        # 2) 카테고리별 search.list (각 25개, 100 쿼터 × 카테고리 수)
        for cat_id in SEARCH_CATEGORIES:
            resp = await client.get(
                "https://www.googleapis.com/youtube/v3/search",
                params={
                    "part": "snippet",
                    "type": "video",
                    "order": "viewCount",
                    "regionCode": "KR",
                    "publishedAfter": _days_ago(7),
                    "videoCategoryId": cat_id,
                    "maxResults": 25,
                    "key": YOUTUBE_API_KEY,
                },
            )
            if resp.status_code == 200:
                for item in resp.json().get("items", []):
                    snippet = item["snippet"]
                    videos.append({
                        "title": snippet["title"],
                        "channel": snippet["channelTitle"],
                        "category_id": cat_id,
                        "description": snippet.get("description", "")[:200],
                        "view_count": 0,
                        "like_count": 0,
                    })

    # 중복 제거 (제목 기준)
    seen = set()
    unique = []
    for v in videos:
        if v["title"] not in seen:
            seen.add(v["title"])
            unique.append(v)

    return unique


def _parse_video_items(data: dict) -> list[dict]:
    """videos.list 응답에서 영상 정보를 파싱한다."""
    videos = []
    for item in data.get("items", []):
        snippet = item["snippet"]
        stats = item.get("statistics", {})
        videos.append({
            "title": snippet["title"],
            "channel": snippet["channelTitle"],
            "category_id": snippet["categoryId"],
            "description": snippet["description"][:200],
            "view_count": int(stats.get("viewCount", 0)),
            "like_count": int(stats.get("likeCount", 0)),
        })
    return videos


def _days_ago(n: int) -> str:
    """n일 전 날짜를 RFC 3339 형식으로 반환한다."""
    from datetime import datetime, timedelta, timezone
    dt = datetime.now(timezone.utc) - timedelta(days=n)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_json_response(response_text: str) -> dict:
    """Claude 응답에서 JSON을 안전하게 추출한다."""
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", response_text)
    if match:
        return json.loads(match.group(1).strip())
    return json.loads(response_text.strip())


async def _select_topic_with_ai(trending_data: list[dict]) -> dict:
    """Claude API로 트렌드 데이터를 분석해 쇼츠 주제를 선정한다."""
    # 조회수 있는 것 우선, 나머지는 뒤에 붙임
    with_views = sorted(
        [v for v in trending_data if v["view_count"] > 0],
        key=lambda x: x["view_count"],
        reverse=True,
    )
    without_views = [v for v in trending_data if v["view_count"] == 0]
    sorted_data = with_views + without_views

    trending_summary = "\n".join(
        f"- {v['title']} (채널: {v['channel']}, 조회수: {v['view_count']:,})"
        if v["view_count"] > 0
        else f"- {v['title']} (채널: {v['channel']}, 최근 7일 인기)"
        for v in sorted_data[:150]
    )

    prompt = f"""당신은 유튜브 쇼츠 채널 성장 전략가입니다.

## 현재 한국 유튜브 인기 동영상 {len(sorted_data[:150])}개:

{trending_summary}

## 당신의 임무

위 트렌드를 참고하되, 단순히 "지금 뜨는 주제"를 따라가지 마세요.
대신, **채널을 장기적으로 성장시킬 수 있는 독창적인 콘텐츠 포맷**을 설계하세요.

## 성공 채널 분석 (참고)

- **사물의 경고**: 사물이 1인칭으로 말하는 포맷. "나는 전자레인지인데..." 식으로 물건의 입장에서 경고/팁을 전달. 독특한 시점 + 유머 = 평균 수만 조회수
- **유유미미**: 시그니처 멘트 + 신기한 과학/역사 원리를 짧게 설명. 중독성 있는 포맷 반복 = 채널 정체성 확립
- **핵심 공통점**: (1) 사람이 안 나옴 (2) 반복 가능한 포맷 (3) 채널만의 시그니처 (4) 무한히 에피소드 생산 가능

## 조건 (필수)

1. **사람이 직접 촬영하지 않고** 텍스트+이미지+나레이션만으로 제작 가능
2. **저작권 문제 없는 소재만** — 영화/드라마/음악 등 타인의 저작물 사용 불가. 과학 원리, 역사적 사실, 일상 상식, 심리학 등 누구나 쓸 수 있는 소재만 가능
3. **반복 가능한 포맷** — 같은 컨셉으로 수백 편 만들 수 있어야 함
4. **채널 정체성** — 이 포맷만의 독특한 시점이나 캐릭터가 있어야 함 (예: 사물의 입장, 미래인의 시점, 숫자가 말하는 것 등)
5. 욕설, 음란한 내용 제외
6. 20초 내외 짧은 영상
7. 위 트렌드에서 **사람들이 관심 있어하는 큰 카테고리**(과학, 심리, 역사, 일상 등)를 파악하되, 거기에 **독창적 시점/포맷**을 결합

## 응답 형식 (JSON만)

{{
    "topic": "콘텐츠 포맷명 (예: 사물의 과학수업, 숫자가 말하는 세계사 등)",
    "detail": "첫 번째 에피소드 주제 (구체적으로)",
    "why_repeatable": "왜 이 포맷으로 수백 편을 만들 수 있는지",
    "reason": "트렌드 분석 기반 선정 이유"
}}"""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = await asyncio.to_thread(
        client.messages.create,
        model=MODEL,
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}],
    )

    return _parse_json_response(message.content[0].text)
