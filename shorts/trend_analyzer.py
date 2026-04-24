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

# 실제 바이럴된 극한 밸런스게임 질문 (SNS/유튜브/예능/커뮤니티 출처)
BALANCE_QUESTIONS = [
    # === 병맛/말장난 ===
    "팔만대장경 다 읽기 vs 대장내시경 팔만번 하기",
    "송강이랑 결혼해서 송강호 낳기 vs 송강호랑 결혼해서 송강 낳기",
    "토맛 토마토 vs 토마토맛 토",
    "카레맛 똥 vs 똥맛 카레",
    "10억 받고 '코딱지'로 개명하기 vs 500만원 내고 지금 이름 유지하기",
    "머리카락 맛 라면 vs 라면 맛 머리카락",
    "눈에서 레이저 나가는데 제어 불가 vs 손에서 거미줄 나가는데 제어 불가",
    "방구 소리가 '사랑해'로 나옴 vs 재채기 소리가 '바보'로 나옴",
    "모기가 말을 걸어옴 vs 바퀴벌레가 편지를 씀",
    "웃을 때마다 방귀 나옴 vs 방귀 뀔 때마다 웃음 나옴",
    # === 돈 관련 극한 ===
    "내가 1억 받는 대신 내가 싫어하는 사람이 100억 받기 vs 둘 다 한 푼도 안 받기",
    "5조 부자 유병재 vs 빚 5억 차은우",
    "빚 100억 있는데 나만 바라보는 차은우 vs 지금 내 애인",
    "10억 받고 얼굴 랜덤 돌리기 vs 지금 내 얼굴로 살기",
    "100억 받고 평생 한국 못 나가기 vs 10억 받고 자유롭게 살기",
    "100% 확률로 1억 받기 vs 50% 확률로 100억 받기",
    "월급 1억인데 주 7일 근무 vs 월급 300인데 주 3일 근무",
    "10억 받고 평생 삼겹살 못 먹기 vs 그냥 삼겹살 먹고 살기",
    "100억 부자인데 평생 혼자 살기 vs 가난하지만 사랑하는 사람과 살기",
    "1억 받는 대신 키 10cm 줄어들기 vs 안 받기",
    "다시 태어난다면 100억 부자 vs 차은우 외모",
    "50억 받고 평생 대중교통만 타기 vs 안 받고 차 타기",
    "30억 받고 평생 겨울만 살기 vs 안 받고 사계절 살기",
    "10억 받고 평생 핸드폰 못 쓰기 vs 그냥 살기",
    "1억 받는 대신 1년간 매일 풀코스 마라톤 뛰기 vs 안 받기",
    # === 외모/연예인 ===
    "똥냄새 나는 강동원 vs 향기나는 미미미누",
    "160cm 바퀴벌레랑 같이 살기 vs 1cm 강동원이랑 같이 살기",
    "차은우 얼굴 + 150cm vs 내 얼굴 + 190cm",
    "얼굴은 완벽한데 목소리가 도널드덕 vs 목소리 완벽한데 얼굴이 못생김",
    "세상에서 가장 잘생긴 얼굴인데 키 155cm vs 평범한 얼굴에 키 185cm",
    "얼굴은 내 이상형인데 발냄새 극심 vs 얼굴은 별로인데 항상 좋은 향기",
    "이상형이 나한테 고백하는데 코에서 코털이 삐져나옴 vs 이상형이 아닌 사람이 완벽하게 고백",
    # === 생존/극한 상황 ===
    "좀비 아포칼립스에서 무기 없이 살아남기 vs 무인도에서 3년 버티기",
    "평생 두통 vs 평생 치통",
    "평생 가려운 등 vs 평생 시린 이",
    "하루 2시간만 잘 수 있는데 피곤 안 느낌 vs 하루 12시간 자야 함",
    "평생 앉지 못하기 vs 평생 서지 못하기",
    "영원히 씻지 않기 vs 영원히 화장실 못 가기",
    "평생 물만 마시기 vs 모든 음료에 소변 한 방울 섞어 마시기",
    "평생 신발 속에 작은 돌 하나 vs 평생 속옷 태그 찝찝함",
    # === 인간관계/우정 ===
    "친구 전 애인과 사귀기 vs 친구가 내 전 애인과 사귀기",
    "차은우랑 사귀고 절친과 절교하기 vs 차은우랑 안 사귀고 절친과 평생 친구하기",
    "내 비밀 다 아는 친구 1명 vs 나에 대해 아무것도 모르는 친구 100명",
    "5살이 된 절친이랑 놀기 vs 절친이 5명으로 분열",
    "절친이 내 뒷담 까는 걸 들음 vs 내가 모르는 사이 절친이 이사 감",
    "친구가 내 험담을 하는 영상이 SNS에 퍼짐 vs 내가 친구 험담하는 영상이 퍼짐",
    "베프가 내 짝사랑 고백을 대신 해줌 vs 베프가 내 짝사랑한테 고백함",
    "불편한 직장 상사와 매일 점심에 한우 먹기 vs 혼자 컵라면 먹기",
    # === 초능력/판타지 ===
    "투명인간 되기 (해제 불가) vs 날 수 있는데 속도가 걸어가는 속도",
    "과거로 갈 수 있는데 돌아올 수 없음 vs 미래로 갈 수 있는데 바꿀 수 없음",
    "다른 사람 생각을 읽을 수 있는데 끌 수 없음 vs 거짓말만 할 수 있는 능력",
    "10년 전으로 돌아가서 다시 살기 vs 10년 후를 미리 보기",
    "하늘을 날 수 있는데 항상 벌거벗어야 함 vs 순간이동 가능한데 도착하면 항상 옷이 바뀜",
    "시간을 멈출 수 있는데 1분만 vs 시간을 10배속으로 감을 수 있는데 자기도 늙음",
    "동물과 대화 가능한데 사람과 대화 불가 vs 사람과만 대화 가능한데 동물이 항상 공격",
    "먹어도 살 안 찌는 체질 but 맛을 못 느낌 vs 한 입만 먹어도 살 찜 but 맛은 10배",
    "기억력이 완벽한데 나쁜 기억도 안 잊혀짐 vs 기억력 금붕어인데 항상 행복함",
    # === 연애/커플 ===
    "매일 싸우는데 화해 잘 하는 커플 vs 안 싸우는데 대화가 없는 커플",
    "애인이 전 애인 꿈꿈 vs 내가 전 애인 꿈꿈",
    "애인이 이성 친구 100명 vs 애인에게 친구가 0명",
    "애인이 나보다 친구를 더 좋아함 vs 애인이 나를 너무 좋아해서 친구가 없음",
    "1년에 한 번 만나는 완벽한 연인 vs 매일 만나는 평범한 연인",
    "애인이 내 핸드폰을 매일 확인 vs 애인이 자기 핸드폰을 절대 안 보여줌",
    "첫사랑이랑 재회했는데 기억을 못 함 vs 내가 기억하는데 첫사랑이 나를 싫어함",
    "연인이 나 몰래 성형함 vs 연인이 나 몰래 빚을 짐",
    "애인 부모님이 날 극혐 vs 내 부모님이 애인을 극혐",
    "바람 피고 평생 숨기는 애인 vs 자백하고 용서 구하는 애인",
    "연인보다 하루 빨리 죽기 vs 하루 늦게 죽기",
    # === 일상/직장 ===
    "평생 월요일만 반복 vs 평생 일요일 밤만 반복",
    "회사에서 방귀를 참을 수 없는 체질 vs 회사에서 하품을 참을 수 없는 체질",
    "평생 집에서만 살기 (인터넷 가능) vs 평생 밖에서만 살기 (집 없음)",
    "택시비 공짜인데 항상 합승 vs 혼자 타는데 항상 2배 요금",
    "지하철에서 항상 자리 있는데 옆에 항상 진상 vs 항상 서서 가는데 조용함",
    "평생 알람 없이 살기 vs 평생 5분마다 알람 울림",
    "머리에서 항상 치토스 치즈 냄새 vs 몸에서 항상 라면 냄새",
    # === 음식/감각 극한 ===
    "평생 밥에 설탕 뿌려 먹기 vs 평생 과일에 간장 찍어 먹기",
    "김치찌개에 초콜릿 넣어 먹기 vs 아이스크림에 고추장 찍어 먹기",
    "코가 개처럼 예민해지기 vs 귀가 박쥐처럼 예민해지기",
    "평생 젓가락으로만 국 먹기 vs 평생 숟가락으로만 면 먹기",
    "모든 음식이 닭가슴살 맛 vs 모든 음료가 미지근한 보리차 맛",
    "1년간 같은 메뉴만 먹기 vs 1년간 매끼 랜덤 (벌레요리 포함)",
    "평생 혀에 화상 입은 느낌 vs 평생 뇌가 얼어붙는 아이스크림 두통",
    # === 공포/혐오 ===
    "요란한 모기랑 살기 vs 점잖은 바퀴벌레랑 살기",
    "바퀴벌레랑 같이 사는 대신 10억 받기 vs 돈 안 받고 바퀴벌레 없는 삶",
    "귀신 보이는 눈 vs 귀신 소리 들리는 귀",
    "매일 밤 귀신이 나오는 꿈 vs 매일 밤 전 애인이 나오는 꿈",
    "화장실에 항상 바퀴벌레 1마리 vs 침대에 일주일에 한 번 거미",
    "좀비 1마리가 나를 평생 쫓아옴 (느림) vs 아무도 모르는데 나만 아는 운석 충돌 D-30",
    "나보다 빨리 자고 시끄럽게 코 고는 배우자 vs 일주일에 한 번만 씻는 배우자",
    # === SNS/바이럴 ===
    "내 인생 전체가 유튜브 라이브 스트리밍 vs 내 생각이 자막으로 뜸",
    "내 검색 기록 전체 공개 vs 내 카톡 전체 공개",
    "틱톡에 내 흑역사 영상 1000만뷰 vs 유튜브에 내 방 공개 영상 100만뷰",
    "SNS에 올린 글 전부 부모님이 봄 vs SNS에 올린 글 전부 직장 상사가 봄",
    "유튜브 구독자 100만인데 악플만 달림 vs 구독자 100명인데 극찬만",
    "인스타 팔로워 100만인데 실제 친구 0명 vs 팔로워 0명인데 진짜 친구 10명",
    # === 황당/상상 초월 ===
    "평생 뒤로만 걷기 vs 평생 옆으로만 걷기 (게처럼)",
    "웃을 때 돼지 소리 남 vs 울 때 닭 소리 남",
    "말할 때마다 자막이 뜸 vs 걸을 때마다 배경음악이 나옴",
    "손가락이 10개 더 생김 vs 발가락이 10개 더 생김",
    "머리카락이 뱀 vs 손톱이 다이아몬드 (아프지만 부자)",
    "매일 1시간씩 미래의 내가 전화함 vs 매일 1시간씩 과거의 내가 전화함",
    "내가 고양이가 되는데 기억은 남아있음 vs 고양이가 사람이 되는데 우리 집에 옴",
    "매일 아침 랜덤으로 다른 나라에서 깨어남 vs 평생 같은 방에서만 살기",
    "내 그림자가 5초 늦게 따라옴 vs 내 메아리가 다른 말을 함",
]


def _parse_json_response(response_text: str) -> dict:
    """Claude 응답에서 JSON을 안전하게 추출한다."""
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", response_text)
    if match:
        return json.loads(match.group(1).strip())
    return json.loads(response_text.strip())


def _pick_unused_question(history: list[dict]) -> str:
    """히스토리에서 사용하지 않은 질문을 랜덤으로 뽑는다."""
    used_titles = {ep["title"].lower() for ep in history}
    # 히스토리 제목에 질문의 핵심 키워드가 포함되어 있는지로 판단
    unused = []
    for q in BALANCE_QUESTIONS:
        # "A vs B"에서 A, B 추출
        parts = [p.strip().lower() for p in q.replace("vs", " ").split() if len(p.strip()) >= 2]
        already_used = False
        for title in used_titles:
            # 핵심 단어 2개 이상이 기존 제목에 포함되면 사용된 것으로 판단
            match_count = sum(1 for p in parts if p in title)
            if match_count >= 2:
                already_used = True
                break
        if not already_used:
            unused.append(q)

    if not unused:
        logger.warning("모든 질문이 소진됨! 전체 목록에서 랜덤 선택")
        unused = BALANCE_QUESTIONS

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
