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
current_topic = "밸런스게임 결론내기"
current_topic_detail = "밸런스게임 질문에 논리와 유머로 결론을 내주는 채널"
current_episode = None

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

    prompt = f"""당신은 유튜브 쇼츠 밸런스게임 콘텐츠 기획자입니다.

## 현재 한국 유튜브 인기 동영상 {len(sorted_data[:150])}개:

{trending_summary}

## 당신의 임무

위 트렌드를 참고해서, 지금 사람들이 관심 있어할 만한 **밸런스게임 질문**을 선정하세요.

## 채널 컨셉
"밸런스게임 결론내기" — 누구나 한번쯤 고민해본 황금 밸런스게임 질문을 꺼내서, 나름의 논리와 유머로 결론을 내주는 채널.

## 좋은 밸런스게임 질문의 조건
1. **5:5에 가까운 질문** — 정답이 없고 진심으로 갈리는 질문
2. **누구나 아는 질문** — 설명 없이 바로 이해 가능
3. **논쟁이 붙는 질문** — 댓글로 자기 의견을 쓰고 싶어지는 질문
4. **트렌드 연관** — 위 인기 동영상에서 파악한 관심사와 연결되면 더 좋음

## 질문 예시 (이런 느낌으로, 이것들은 쓰지 말 것)
- 똥맛 카레 vs 카레맛 똥
- 투명인간 vs 시간 정지
- 100억인데 감옥 10년 vs 지금 그대로
- 모든 벌레와 대화 가능 vs 모든 물고기와 대화 가능

## 응답 형식 (JSON만)

{{
    "topic": "밸런스게임 결론내기",
    "detail": "A vs B (구체적인 밸런스게임 질문)",
    "reason": "이 질문을 선정한 이유 (트렌드 연관성, 논쟁 가능성 등)"
}}"""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = await asyncio.to_thread(
        client.messages.create,
        model=MODEL,
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}],
    )

    return _parse_json_response(message.content[0].text)
