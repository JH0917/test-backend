"""프로그래밍으로 생성하는 SFX/BGM 모듈.

외부 음원 파일 없이 numpy로 효과음과 배경음악을 생성한다.
assets/ 디렉토리에 실제 음원 파일이 있으면 그걸 우선 사용한다.
"""

from __future__ import annotations

import os
import struct
import tempfile
import wave
import math
import logging

import numpy as np

logger = logging.getLogger("shorts.audio_assets")

# 프로젝트 내 assets 경로 (실제 음원 번들용)
ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
BGM_DIR = os.path.join(ASSETS_DIR, "bgm")
SFX_DIR = os.path.join(ASSETS_DIR, "sfx")

SAMPLE_RATE = 44100


def _save_wav(filepath: str, samples: np.ndarray):
    """numpy 배열을 WAV 파일로 저장한다."""
    samples = np.clip(samples, -1.0, 1.0)
    int_samples = (samples * 32767).astype(np.int16)
    with wave.open(filepath, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(int_samples.tobytes())


def _envelope(length: int, attack: float = 0.01, decay: float = 0.1) -> np.ndarray:
    """ADSR 엔벨로프를 생성한다."""
    env = np.ones(length)
    attack_samples = int(SAMPLE_RATE * attack)
    decay_samples = int(SAMPLE_RATE * decay)
    if attack_samples > 0:
        env[:attack_samples] = np.linspace(0, 1, attack_samples)
    if decay_samples > 0:
        env[-decay_samples:] = np.linspace(1, 0, decay_samples)
    return env


def generate_ding(filepath: str | None = None) -> str:
    """밝은 '딩!' 효과음 (정답/결론 공개용)."""
    if filepath is None:
        filepath = os.path.join(tempfile.gettempdir(), "sfx_ding.wav")
    duration = 0.5
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), False)
    # 두 주파수 조합으로 밝은 벨 소리
    signal = 0.6 * np.sin(2 * np.pi * 1200 * t) + 0.4 * np.sin(2 * np.pi * 1800 * t)
    signal *= _envelope(len(signal), attack=0.005, decay=0.35)
    _save_wav(filepath, signal)
    return filepath


def generate_whoosh(filepath: str | None = None) -> str:
    """스윙 효과음 (장면 전환용)."""
    if filepath is None:
        filepath = os.path.join(tempfile.gettempdir(), "sfx_whoosh.wav")
    duration = 0.4
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), False)
    # 주파수가 올라가는 필터드 노이즈
    noise = np.random.uniform(-1, 1, len(t))
    freq_sweep = np.linspace(200, 2000, len(t))
    signal = noise * np.sin(2 * np.pi * freq_sweep * t / SAMPLE_RATE)
    signal *= _envelope(len(signal), attack=0.05, decay=0.2)
    signal *= 0.5
    _save_wav(filepath, signal)
    return filepath


def generate_tick(filepath: str | None = None) -> str:
    """째깍 효과음 (카운트다운용)."""
    if filepath is None:
        filepath = os.path.join(tempfile.gettempdir(), "sfx_tick.wav")
    duration = 0.08
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), False)
    signal = np.sin(2 * np.pi * 800 * t)
    signal *= _envelope(len(signal), attack=0.002, decay=0.06)
    signal *= 0.7
    _save_wav(filepath, signal)
    return filepath


def generate_impact(filepath: str | None = None) -> str:
    """임팩트 효과음 (후킹/강조용)."""
    if filepath is None:
        filepath = os.path.join(tempfile.gettempdir(), "sfx_impact.wav")
    duration = 0.6
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), False)
    # 낮은 주파수 펄스 + 노이즈 버스트
    low_pulse = np.sin(2 * np.pi * 60 * t) * np.exp(-t * 8)
    noise_burst = np.random.uniform(-1, 1, len(t)) * np.exp(-t * 15)
    signal = 0.6 * low_pulse + 0.4 * noise_burst
    signal *= _envelope(len(signal), attack=0.002, decay=0.3)
    _save_wav(filepath, signal)
    return filepath


def generate_drumroll(filepath: str | None = None) -> str:
    """드럼롤 효과음 (카운트다운 시작용, 3초)."""
    if filepath is None:
        filepath = os.path.join(tempfile.gettempdir(), "sfx_drumroll.wav")
    duration = 3.0
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), False)
    # 빠른 반복 클릭 + 볼륨 크레센도
    click_rate = np.linspace(10, 30, len(t))  # 점점 빨라지는 클릭
    clicks = np.sin(2 * np.pi * click_rate * t)
    noise = np.random.uniform(-0.3, 0.3, len(t))
    signal = (clicks * 0.5 + noise * 0.5) * np.linspace(0.2, 1.0, len(t))
    signal *= _envelope(len(signal), attack=0.1, decay=0.05)
    _save_wav(filepath, signal)
    return filepath


def generate_bgm_loop(filepath: str | None = None, duration: float = 60.0) -> str:
    """긴장감 있는 배경음악 루프.

    실제 음원 파일이 있으면 그걸 사용하고,
    없으면 프로그래밍으로 간단한 앰비언트 비트를 생성한다.
    """
    # 1. 번들된 BGM 파일이 있으면 사용
    if os.path.isdir(BGM_DIR):
        bgm_files = [f for f in os.listdir(BGM_DIR) if f.endswith((".mp3", ".wav"))]
        if bgm_files:
            import random
            chosen = random.choice(bgm_files)
            logger.info(f"번들 BGM 사용: {chosen}")
            return os.path.join(BGM_DIR, chosen)

    # 2. 프로그래밍 생성
    if filepath is None:
        filepath = os.path.join(tempfile.gettempdir(), "bgm_generated.wav")

    samples = int(SAMPLE_RATE * duration)
    t = np.linspace(0, duration, samples, False)

    # 저음 드론 (긴장감)
    drone = 0.15 * np.sin(2 * np.pi * 55 * t)
    drone += 0.1 * np.sin(2 * np.pi * 82.5 * t)

    # 리듬 펄스 (BPM 120 = 0.5초 간격)
    beat_interval = 0.5
    beat_samples = int(SAMPLE_RATE * beat_interval)
    pulse = np.zeros(samples)
    for i in range(0, samples, beat_samples):
        end = min(i + int(SAMPLE_RATE * 0.05), samples)
        pulse[i:end] = 0.2

    # 하이햇 패턴 (8분음표)
    hihat_interval = beat_samples // 2
    hihat = np.zeros(samples)
    for i in range(0, samples, hihat_interval):
        end = min(i + int(SAMPLE_RATE * 0.02), samples)
        hihat[i:end] = np.random.uniform(-0.08, 0.08, end - i)

    signal = drone + pulse + hihat
    # 페이드 인/아웃
    fade_samples = int(SAMPLE_RATE * 2)
    signal[:fade_samples] *= np.linspace(0, 1, fade_samples)
    signal[-fade_samples:] *= np.linspace(1, 0, fade_samples)

    _save_wav(filepath, signal)
    logger.info("프로그래밍 BGM 생성 완료")
    return filepath


def get_or_generate_sfx() -> dict[str, str]:
    """모든 SFX 파일을 확보한다. 캐싱하여 반복 생성 방지."""
    sfx = {}
    generators = {
        "ding": generate_ding,
        "whoosh": generate_whoosh,
        "tick": generate_tick,
        "impact": generate_impact,
        "drumroll": generate_drumroll,
    }

    for name, gen_func in generators.items():
        # 번들 파일 우선
        for ext in (".wav", ".mp3"):
            bundled = os.path.join(SFX_DIR, f"{name}{ext}")
            if os.path.exists(bundled):
                sfx[name] = bundled
                break
        else:
            # 캐시 확인
            cached = os.path.join(tempfile.gettempdir(), f"sfx_{name}.wav")
            if not os.path.exists(cached):
                gen_func(cached)
            sfx[name] = cached

    return sfx
