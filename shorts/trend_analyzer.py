import os
import re
import json
import random
import logging

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

logger = logging.getLogger("shorts.trend_analyzer")

# 전역변수: 선정된 주제
current_topic = "밸런스게임 결론내기"
current_topic_detail = "밸런스게임 질문에 논리와 유머로 결론을 내주는 채널"
current_keywords = ""

# 진짜 고민되는 밸런스게임 질문 (양쪽 다 끌리고 양쪽 다 끔찍한 것만)
BALANCE_QUESTIONS = [
    # === 연애/관계 (댓글 갈림 보장) ===
    "매일 싸우지만 화해 섹스가 미친 커플 vs 안 싸우지만 스킨십 제로 커플",
    "나를 미치게 좋아하는 평범한 사람 vs 나도 미치게 좋아하지만 나한테 관심 없는 사람",
    "전 애인이 나보다 훨씬 잘됨 vs 전 애인이 나 때문에 인생 망함",
    "애인이 이성 절친이 딱 1명 (매일 연락함) vs 애인이 전 애인 20명과 아직 친함",
    "첫사랑이 지금 나한테 고백함 (현재 애인 있음) vs 현재 애인이 첫사랑에게 고백받음",
    "완벽한 애인인데 우리 부모님이 극혐 vs 별로인 애인인데 부모님이 극찬",
    "연애 초반 설렘이 평생 지속 but 깊은 정은 못 느낌 vs 설렘 제로 but 가족 같은 안정감",
    "애인의 과거 연애 영상을 발견함 vs 애인이 내 과거 연애 영상을 발견함",
    "3년 사귄 애인이 사실 쌍둥이랑 번갈아 만남 vs 내가 쌍둥이인데 애인이 모름",
    # === 돈/직장 (현실 공감) ===
    "월 500인데 매일 상사한테 인격모독 vs 월 200인데 동료들이 가족 같음",
    "로또 1등 당첨인데 가족 전원이 알게 됨 vs 당첨 안 되고 조용히 살기",
    "연봉 2억인데 하는 일이 매일 똑같은 단순 반복 vs 연봉 3천인데 매일 새로운 도전",
    "월급 800인데 성장 제로인 회사 vs 월급 250인데 1년 뒤 몸값 3배 되는 회사",
    "40살에 은퇴하고 월 300만원 평생 받기 vs 65살까지 일하고 월 1000만원 받기",
    "내가 사장인데 직원들이 다 나를 싫어함 vs 막내인데 모든 사람이 나를 좋아함",
    "재택근무인데 24시간 카메라 ON vs 출근인데 하루 4시간만 일함",
    # === 능력/판타지 (상상력 폭발) ===
    "먹어도 안 찌는 체질인데 맛을 50%만 느낌 vs 한 입만 먹어도 찌는데 맛이 10배",
    "모든 사람의 나에 대한 진심을 알 수 있음 vs 절대 모르고 살기",
    "과거를 바꿀 수 있는데 현재 기억이 사라짐 vs 미래를 볼 수 있는데 바꿀 수 없음",
    "누구든 한 번 만나면 나를 좋아하게 만드는 능력 vs 한 번 만나면 진심을 알 수 있는 능력",
    "잠을 안 자도 되는데 혼자만의 시간이 없음 vs 하루 10시간 자야 하지만 꿈을 조종 가능",
    "외국어 전부 자유자재인데 한국어를 점점 잊음 vs 한국어만 완벽하고 외국어 영원히 못 배움",
    "하루를 48시간으로 쓸 수 있는데 남들 눈에 2배 빨리 늙음 vs 보통 24시간",
    "거짓말을 100% 감지하는 능력 vs 누구한테든 거짓말이 100% 통하는 능력",
    # === 일상/사회생활 (공감 폭발) ===
    "평생 월요일 아침 기분 vs 평생 일요일 밤 기분",
    "항상 5분 늦는 사람 vs 항상 30분 일찍 도착해서 기다리는 사람",
    "모든 사람이 내 나이를 10살 많게 봄 vs 10살 어리게 봄",
    "절대 비밀을 못 지키는 체질 vs 절대 농담을 이해 못 하는 체질",
    "화장실 갈 때마다 30분씩 걸림 vs 재채기 할 때마다 방귀가 같이 나옴",
    "평생 엘리베이터 못 탐 (계단만) vs 평생 계단 못 씀 (엘리베이터만)",
    "모든 택배가 3주 걸림 vs 모든 배달음식이 2시간 걸림",
    # === 음식 (모두가 공감) ===
    "평생 매운 거 못 먹음 vs 평생 단 거 못 먹음",
    "맛있는 건 다 먹을 수 있는데 항상 배부른 느낌 vs 항상 배고프지만 뭘 먹어도 맛없음",
    "치킨은 먹을 수 있는데 피자 평생 금지 vs 피자는 먹을 수 있는데 치킨 평생 금지",
    "평생 뜨거운 음식 못 먹음 (다 식혀서) vs 평생 차가운 음식 못 먹음 (아이스크림 포함)",
    # === 황당/바이럴 (웃음+고민) ===
    "말할 때마다 속마음이 자막으로 뜸 vs 걸을 때마다 브금이 랜덤으로 나옴",
    "카레맛 똥 vs 똥맛 카레",
    "웃을 때 돼지 소리 나는데 웃음 참기 불가 vs 울 때 닭 소리 나는데 울음 참기 불가",
    "모기가 말 걸어오는데 은근 재밌음 vs 바퀴벌레가 편지 쓰는데 글씨가 예쁨",
    "내 방귀가 장미향이지만 소리가 확성기급 vs 내 방귀가 무음이지만 냄새가 생화학무기",
    "귀신이 보이는데 다 착함 vs 귀신은 안 보이는데 가끔 만져짐",
    "내 그림자가 5초 늦게 따라오는데 가끔 딴짓함 vs 내 메아리가 내가 안 한 말을 함",
]

# 진짜 50:50 갈리는 고열도 질문. 새 영상은 이 풀을 우선 사용한다.
HIGH_HEAT_QUESTIONS = [
    # === 연애 (양쪽 다 진짜 끌림) ===
    "나를 미치게 좋아하는 평범한 사람 vs 나도 미치게 좋아하지만 나한테 관심 없는 사람",
    "첫사랑이 지금 나한테 고백함 (현재 애인 있음) vs 현재 애인이 첫사랑에게 고백받음",
    "연애 초반 설렘이 평생 지속 but 깊은 정은 못 느낌 vs 설렘 제로 but 가족 같은 안정감",
    "3년 사귄 애인이 사실 쌍둥이랑 번갈아 만남 vs 내가 쌍둥이인데 애인이 모름",
    "완벽한 애인인데 우리 부모님이 극혐 vs 별로인 애인인데 부모님이 극찬",
    "전 애인이 나보다 훨씬 잘됨 vs 전 애인이 나 때문에 인생 망함",
    # === 능력 (양쪽 다 탐남) ===
    "모든 사람의 나에 대한 진심을 알 수 있음 vs 절대 모르고 살기",
    "거짓말을 100% 감지하는 능력 vs 누구한테든 거짓말이 100% 통하는 능력",
    "먹어도 안 찌는 체질인데 맛을 50%만 느낌 vs 한 입만 먹어도 찌는데 맛이 10배",
    "누구든 한 번 만나면 나를 좋아하게 만드는 능력 vs 한 번 만나면 진심을 알 수 있는 능력",
    "외국어 전부 자유자재인데 한국어를 점점 잊음 vs 한국어만 완벽하고 외국어 영원히 못 배움",
    # === 돈/현실 (양쪽 다 아픔) ===
    "월 500인데 매일 상사한테 인격모독 vs 월 200인데 동료들이 가족 같음",
    "40살에 은퇴하고 월 300만원 평생 받기 vs 65살까지 일하고 월 1000만원 받기",
    "로또 1등 당첨인데 가족 전원이 알게 됨 vs 당첨 안 되고 조용히 살기",
    "연봉 2억인데 매일 단순 반복 vs 연봉 3천인데 매일 새로운 도전",
    # === 일상 (공감 극대화) ===
    "평생 월요일 아침 기분 vs 평생 일요일 밤 기분",
    "절대 비밀을 못 지키는 체질 vs 절대 농담을 이해 못 하는 체질",
    "치킨 평생 금지 vs 피자 평생 금지",
    "과거를 바꿀 수 있는데 현재 기억이 사라짐 vs 미래를 볼 수 있는데 바꿀 수 없음",
    "말할 때마다 속마음이 자막으로 뜸 vs 걸을 때마다 브금이 랜덤으로 나옴",
    "카레맛 똥 vs 똥맛 카레",
]


def _parse_json_response(response_text: str) -> dict:
    """Claude 응답에서 JSON을 안전하게 추출한다."""
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", response_text)
    if match:
        return json.loads(match.group(1).strip())
    return json.loads(response_text.strip())


def _pick_unused_question(history: list[dict]) -> str:
    """히스토리에서 사용하지 않은 질문을 랜덤으로 뽑는다."""
    # 1차: question 필드로 정확 매칭 (신규 히스토리)
    used_questions = {ep["question"] for ep in history if "question" in ep}
    # 2차: question 필드 없는 구 히스토리는 제목에서 vs 양쪽 핵심어로 매칭
    used_titles = {ep["title"] for ep in history if "question" not in ep and "title" in ep}

    question_pool = list(dict.fromkeys(HIGH_HEAT_QUESTIONS + BALANCE_QUESTIONS))
    unused = []
    for q in question_pool:
        if q in used_questions:
            continue
        # 구 히스토리 호환: vs 양쪽에서 2자 이상 단어를 모두 추출, 절반 이상 매칭 시 사용된 것으로 판단
        if used_titles and " vs " in q:
            a_side, b_side = q.split(" vs ", 1)
            keywords = [w for w in a_side.split() + b_side.split() if len(w) >= 2 and w != "vs"]
            if keywords and any(
                sum(1 for kw in keywords if kw in title) >= max(2, len(keywords) // 2)
                for title in used_titles
            ):
                continue
        unused.append(q)

    if not unused:
        logger.warning("모든 질문이 소진됨! 전체 목록에서 랜덤 선택")
        unused = question_pool

    hot_unused = [q for q in unused if q in HIGH_HEAT_QUESTIONS]
    if hot_unused and random.random() < 0.8:
        return random.choice(hot_unused)
    return random.choice(unused)


async def analyze_youtube_trends() -> dict:
    """황금밸런스게임 질문을 선정한다."""
    global current_topic, current_topic_detail, current_keywords

    topic = await _select_balance_question()

    current_topic = topic["topic"]
    current_topic_detail = topic["detail"]
    current_keywords = topic.get("keywords", "")
    return topic


async def _select_balance_question() -> dict:
    """하드코딩된 목록에서 미사용 질문을 뽑는다."""
    from shorts.video_creator import _load_episode_history

    history = _load_episode_history()
    question = _pick_unused_question(history)

    logger.info(f"선정된 질문: {question}")

    return {
        "topic": "밸런스게임 결론내기",
        "detail": question,
        "keywords": question.replace(" vs ", ", ").replace(" ", ""),
        "reason": "하드코딩 목록에서 선정",
    }


async def pick_daily_question() -> dict:
    """매일 황금밸런스 질문을 하나 골라서 current_topic_detail을 업데이트한다."""
    global current_topic_detail, current_keywords

    result = await _select_balance_question()
    current_topic_detail = result["detail"]
    current_keywords = result.get("keywords", "")
    return result
