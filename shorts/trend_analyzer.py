import os
import random
import logging

logger = logging.getLogger("shorts.trend_analyzer")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# 전역변수: 선정된 주제
current_topic = "역사 IF"
current_topic_detail = "What if dinosaurs never went extinct?"
current_keywords = ""

# 역사 IF 주제 목록 — "만약 ~했다면?" 시각적으로 충격적인 시나리오
HISTORY_IF_TOPICS = [
    # === 선사시대 / 자연 ===
    "What if dinosaurs never went extinct?",
    "What if humans could breathe underwater?",
    "What if the Moon was twice as close to Earth?",
    "What if gravity was half as strong?",
    "What if Earth had rings like Saturn?",
    "What if the ice age never ended?",
    "What if humans had wings?",
    "What if the sun was twice as big?",
    "What if oceans dried up overnight?",
    "What if trees could walk?",

    # === 역사 반전 ===
    "What if ancient Egypt had modern technology?",
    "What if the Roman Empire never fell?",
    "What if samurai had guns from the start?",
    "What if the Titanic never sank?",
    "What if the pyramids were built today?",
    "What if medieval knights had tanks?",
    "What if Vikings discovered America first and stayed?",
    "What if ancient Greeks had smartphones?",
    "What if the Great Wall of China was 10x bigger?",
    "What if Genghis Khan had nuclear weapons?",

    # === 동물 / 생물 ===
    "What if cats ruled the world?",
    "What if dogs were as big as elephants?",
    "What if insects were human-sized?",
    "What if sharks could walk on land?",
    "What if birds were the dominant species?",
    "What if animals could talk?",
    "What if spiders were the size of cars?",
    "What if whales could fly?",

    # === 현대 반전 ===
    "What if cars didn't exist and everyone rode horses?",
    "What if the internet was never invented?",
    "What if money didn't exist?",
    "What if humans lived to 500 years old?",
    "What if everyone could read minds?",
    "What if robots replaced all humans?",
    "What if there was no electricity for a year?",
    "What if food grew on every surface?",

    # === 판타지 / SF ===
    "What if portals to other dimensions appeared in cities?",
    "What if dragons were real and lived among us?",
    "What if giants walked the Earth?",
    "What if magic was real and taught in schools?",
    "What if aliens landed in ancient Rome?",
    "What if zombies appeared in medieval times?",
    "What if superheroes were real?",
    "What if time suddenly stopped for everyone except you?",
]

# 바이럴 가능성 높은 주제 (우선 선택)
HIGH_VIRAL_TOPICS = [
    "What if dinosaurs never went extinct?",
    "What if cats ruled the world?",
    "What if insects were human-sized?",
    "What if ancient Egypt had modern technology?",
    "What if dragons were real and lived among us?",
    "What if gravity was half as strong?",
    "What if sharks could walk on land?",
    "What if the Roman Empire never fell?",
    "What if giants walked the Earth?",
    "What if dogs were as big as elephants?",
    "What if Earth had rings like Saturn?",
    "What if humans had wings?",
    "What if portals to other dimensions appeared in cities?",
    "What if robots replaced all humans?",
    "What if aliens landed in ancient Rome?",
]


def _parse_json_response(response_text: str) -> dict:
    """Claude 응답에서 JSON을 안전하게 추출한다."""
    import re
    import json
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", response_text)
    if match:
        return json.loads(match.group(1).strip())
    return json.loads(response_text.strip())


def _pick_unused_topic(history: list[dict]) -> str:
    """히스토리에서 사용하지 않은 주제를 랜덤으로 뽑는다."""
    used_topics = {ep.get("topic", "") for ep in history}

    topic_pool = list(dict.fromkeys(HIGH_VIRAL_TOPICS + HISTORY_IF_TOPICS))
    unused = [t for t in topic_pool if t not in used_topics]

    if not unused:
        logger.warning("모든 주제가 소진됨! 전체 목록에서 랜덤 선택")
        unused = topic_pool

    hot_unused = [t for t in unused if t in HIGH_VIRAL_TOPICS]
    if hot_unused and random.random() < 0.8:
        return random.choice(hot_unused)
    return random.choice(unused)


async def analyze_youtube_trends() -> dict:
    """역사 IF 주제를 선정한다."""
    global current_topic, current_topic_detail, current_keywords

    topic = await _select_topic()

    current_topic = "역사 IF"
    current_topic_detail = topic["detail"]
    current_keywords = topic.get("keywords", "")
    return topic


async def _select_topic() -> dict:
    """목록에서 미사용 주제를 뽑는다."""
    from shorts.video_creator import _load_episode_history

    history = _load_episode_history()
    topic = _pick_unused_topic(history)

    logger.info(f"선정된 주제: {topic}")

    return {
        "topic": "역사 IF",
        "detail": topic,
        "keywords": topic.replace("What if ", "").replace("?", ""),
        "reason": "목록에서 선정",
    }


async def pick_daily_question() -> dict:
    """매일 주제를 하나 골라서 업데이트한다."""
    global current_topic_detail, current_keywords

    result = await _select_topic()
    current_topic_detail = result["detail"]
    current_keywords = result.get("keywords", "")
    return result
