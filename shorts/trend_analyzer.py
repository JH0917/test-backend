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

    prompt = f"""당신은 유튜브 쇼츠 콘텐츠 기획 전문가입니다.

아래는 현재 한국 유튜브 인기 동영상 {len(sorted_data[:150])}개 목록입니다:

{trending_summary}

이 트렌드를 분석하고, 다음 조건에 맞는 쇼츠 콘텐츠 주제를 1개 선정해주세요:

조건:
1. 사람이 직접 촬영하지 않고 만들 수 있는 영상 (텍스트, 이미지, 나레이션 조합)
2. 유유미미, 사물의 경고 같은 채널 스타일 참고 (흥미로운 사실, 심리테스트, 랭킹, 상식 퀴즈, 놀라운 이야기 등)
3. 욕설, 음란한 내용 제외
4. 20초 내외로 만들 수 있는 짧은 콘텐츠
5. 시청자의 호기심을 자극하는 주제

다음 JSON 형식으로만 응답하세요:
{{
    "topic": "주제 카테고리 (예: 놀라운 사실, 심리테스트, 랭킹 등)",
    "detail": "구체적인 영상 주제 (예: 세계에서 가장 비싼 음식 TOP 5)",
    "reason": "이 주제를 선정한 이유"
}}"""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = await asyncio.to_thread(
        client.messages.create,
        model=MODEL,
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}],
    )

    return _parse_json_response(message.content[0].text)
