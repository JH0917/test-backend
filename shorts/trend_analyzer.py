import os
import re
import json
import asyncio
import anthropic

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

MODEL = "claude-opus-4-20250514"

# 전역변수: 선정된 주제
current_topic = "밸런스게임 결론내기"
current_topic_detail = "밸런스게임 질문에 논리와 유머로 결론을 내주는 채널"


async def analyze_youtube_trends() -> dict:
    """황금밸런스게임 질문을 선정한다."""
    global current_topic, current_topic_detail

    topic = await _select_balance_question()

    current_topic = topic["topic"]
    current_topic_detail = topic["detail"]
    return topic


def _parse_json_response(response_text: str) -> dict:
    """Claude 응답에서 JSON을 안전하게 추출한다."""
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", response_text)
    if match:
        return json.loads(match.group(1).strip())
    return json.loads(response_text.strip())


async def _select_balance_question() -> dict:
    """Claude로 황금밸런스게임 질문을 선정한다."""
    from shorts.video_creator import _load_episode_history

    history = _load_episode_history()
    history_text = ""
    if history:
        recent = history[-30:]
        history_text = "\n\n## 이미 다룬 질문 (절대 겹치지 말 것!)\n"
        for ep in recent:
            history_text += f"- {ep['title']}\n"

    prompt = f"""당신은 밸런스게임 전문가입니다.

## 임무
한국에서 유명한 황금밸런스게임 질문 중 하나를 골라주세요.
인터넷, 예능, 술자리 등에서 오래전부터 회자되는 클래식한 질문이어야 합니다.
{history_text}
## 좋은 질문의 조건
1. **5:5에 가까운 질문** — 정답이 없고 진심으로 갈리는 질문
2. **누구나 아는 질문** — 설명 없이 바로 이해 가능
3. **논쟁이 붙는 질문** — 댓글로 자기 의견을 쓰고 싶어지는 질문
4. **이미 유명한 질문** — 새로 만든 게 아니라 다들 한번쯤 들어본 질문

## 카테고리 우선순위 (위에서부터 우선)
1. **음식 논쟁** — 짜장vs짬뽕, 찍먹vs부먹, 소주vs맥주, 치킨vs피자, 민초vs반민초 등 (조회수 가장 높음)
2. **일상/취향** — 아침형vs저녁형, 강아지vs고양이, 여름vs겨울, 산vs바다 등
3. **돈/직장** — 연봉5천칼퇴vs연봉1억야근, 좋아하는일적은돈vs싫은일많은돈 등
4. **초능력/판타지** — 투명인간vs시간정지, 날기vs순간이동, 과거vs미래여행 등

## 질문 예시 (이런 느낌, 이것들도 사용 가능)
- 짜장면 vs 짬뽕
- 찍먹 vs 부먹
- 소주 vs 맥주
- 떡볶이 vs 라면
- 민초 vs 반민초
- 치킨 vs 피자
- 강아지 vs 고양이
- 평생 여름 vs 평생 겨울
- 산 vs 바다
- 아침형 인간 vs 저녁형 인간
- 똥맛 카레 vs 카레맛 똥
- 출근할 때 순간이동 vs 퇴근할 때 순간이동
- 투명인간 vs 시간 정지
- 날기 vs 순간이동

## 절대 금지
- ❌ 성적 뉘앙스가 있는 질문 (YouTube 알고리즘에서 노출 차단됨)
- ❌ 대형 채널이 이미 바이럴시킨 특정 주제 (10억 얼굴 랜덤 등)
- ❌ 답이 너무 뻔한 질문 (토론이 안 되면 댓글이 안 달림)

## 응답 형식 (JSON만)

{{
    "topic": "밸런스게임 결론내기",
    "detail": "A vs B (구체적인 밸런스게임 질문)",
    "reason": "이 질문을 선정한 이유"
}}"""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = await asyncio.to_thread(
        client.messages.create,
        model=MODEL,
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}],
    )

    return _parse_json_response(message.content[0].text)


async def pick_daily_question() -> str:
    """매일 황금밸런스 질문을 하나 골라서 current_topic_detail만 업데이트한다."""
    global current_topic_detail

    result = await _select_balance_question()
    current_topic_detail = result["detail"]
    return result["detail"]
