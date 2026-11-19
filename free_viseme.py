"""
발음 기반 입 모양(viseme) 생성 — 사람이 말하듯 자연스러운 입술 움직임
1) 음성 인식(오프라인 한국어 ASR)으로 음절별 발화 시각을 찾고 대본 음절과 정렬
2) 한글 음절을 초성·중성·종성으로 분해해 입 모양 키프레임 생성
   - ㅁ·ㅂ·ㅃ·ㅍ (초성/받침): 입술을 붙임
   - ㅏ 크게 벌림 / ㅓ 중간 / ㅗ·ㅜ 동그랗게 모음 / ㅣ·ㅡ·ㅔ·ㅐ 옆으로 넓게
   - ㅘ·ㅝ·ㅟ 등 이중모음은 동그란 입에서 목표 모양으로 이동
3) 동시조음: 앞뒤 음절이 섞이고, 입이 소리보다 약 50ms 먼저 움직임
결과: 프레임별 (jaw 벌림 0~1, width -1 동그랗게 ~ +1 옆으로, close 입술 닫힘 0~1)
"""
import difflib
import wave
from pathlib import Path

import numpy as np

from free_tts import to_speech

FPS = 30
ASR_DIR = Path("models/sherpa-onnx-zipformer-korean-2024-06-24")
LEAD = 0.04                 # 입이 소리보다 먼저 움직이는 시간(초)

# 중성 21자: (벌림, 너비)
JUNG = {
    0: (1.0, 0.15), 1: (0.65, 0.45), 2: (0.9, 0.15), 3: (0.6, 0.4), 4: (0.7, -0.2), 5: (0.55, 0.5),
    6: (0.65, -0.1), 7: (0.55, 0.5), 8: (0.5, -0.9), 9: (0.95, 0.0), 10: (0.65, 0.2), 11: (0.45, -0.4),
    12: (0.5, -0.8), 13: (0.35, -1.0), 14: (0.7, -0.3), 15: (0.55, 0.2), 16: (0.3, 0.3), 17: (0.35, -0.9),
    18: (0.25, 0.65), 19: (0.25, 0.7), 20: (0.25, 0.85),
}
GLIDE_W = {9, 10, 11, 14, 15, 16}          # ㅘ ㅙ ㅚ ㅝ ㅞ ㅟ : 동그란 입으로 시작
BILABIAL_CHO = {6, 7, 8, 17}               # ㅁ ㅂ ㅃ ㅍ
SIBILANT_CHO = {9, 10, 12, 13, 14}         # ㅅ ㅆ ㅈ ㅉ ㅊ : 이를 거의 다물고 살짝 보임
ALVEOLAR_CHO = {2, 3, 4, 5, 16}            # ㄴ ㄷ ㄸ ㄹ ㅌ : 혀끝이 윗니 뒤에
BILABIAL_JONG = {16, 17, 18, 26}           # 받침 ㅁ ㅂ ㅄ ㅍ
ALVEOLAR_JONG = {4, 5, 6, 7, 8, 19, 20, 22, 23, 25}   # 받침 ㄴ ㄷ ㄹ ㅅ ㅆ ㅈ ㅊ ㅌ 계열
VELAR_JONG = {1, 2, 3, 21, 24}             # 받침 ㄱ ㄲ ㄳ ㅇ ㅋ

_rec = None


def _recognizer():
    global _rec
    if _rec is None:
        import sherpa_onnx as s
        a = ASR_DIR
        _rec = s.OfflineRecognizer.from_transducer(
            encoder=str(a / "encoder-epoch-99-avg-1.int8.onnx"),
            decoder=str(a / "decoder-epoch-99-avg-1.int8.onnx"),
            joiner=str(a / "joiner-epoch-99-avg-1.int8.onnx"),
            tokens=str(a / "tokens.txt"), num_threads=2)
    return _rec


def _hangul(text: str) -> str:
    return "".join(c for c in text if "가" <= c <= "힣")


def syllable_onsets(voice: Path, sentences: list[str], timing) -> list[list[tuple[str, float]]]:
    """문장별 [(음절, 시작초)] — ASR 타임스탬프로 정렬, 실패 시 균등 배분"""
    with wave.open(str(voice)) as w:
        sr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
    out = []
    use_asr = ASR_DIR.exists()
    for sent, (s, e) in zip(sentences, timing):
        syl = _hangul(to_speech(sent))
        times = [None] * len(syl)
        if use_asr and syl:
            try:
                a, b = max(0, s - 0.1), e + 0.1
                st = _recognizer().create_stream()
                st.accept_waveform(sr, x[int(a * sr):int(b * sr)])
                _recognizer().decode_stream(st)
                r = st.result
                chars, ctimes = [], []
                toks = list(zip(r.tokens, r.timestamps)) + [("", b - a)]
                for (tk, t0), (_, t1) in zip(toks[:-1], toks[1:]):
                    h = _hangul(tk)
                    for k, c in enumerate(h):
                        chars.append(c); ctimes.append(a + t0 + (t1 - t0) * k / max(1, len(h)))
                sm = difflib.SequenceMatcher(None, syl, "".join(chars), autojunk=False)
                for blk in sm.get_matching_blocks():
                    for k in range(blk.size):
                        times[blk.a + k] = ctimes[blk.b + k]
            except Exception as ex:
                print("[입모양] 정렬 실패, 균등 배분:", ex)
        # 빈 곳은 앞뒤 값으로 보간 (양 끝은 문장 시작·끝)
        known = [(i, t) for i, t in enumerate(times) if t is not None]
        anchors = [(-1, s)] + known + [(len(syl), e)]
        for (i0, t0), (i1, t1) in zip(anchors[:-1], anchors[1:]):
            for i in range(i0 + 1, i1):
                times[i] = t0 + (t1 - t0) * (i - i0) / (i1 - i0)
        for i in range(1, len(times)):                     # 단조 증가 보정
            times[i] = max(times[i], times[i - 1] + 0.03)
        out.append(list(zip(syl, times)))
    return out


def build_visemes(voice: Path, sentences: list[str], timing, n: int, energy: np.ndarray):
    """프레임별 입 모양 6채널: jaw(벌림) width(-1 동그랗게~+1 옆으로) close(입술 붙임)
    teeth(치아 노출: ㅅㅈㅊ) tongue(혀끝: ㄴㄷㄹ) press(양순음 압착)"""
    keys = [(0.0, 0, 0, 0, 0, 0, 0)]
    for (s, e), syls in zip(timing, syllable_onsets(voice, sentences, timing)):
        for i, (c, t) in enumerate(syls):
            t2 = syls[i + 1][1] if i + 1 < len(syls) else e
            d = min(max(t2 - t, 0.08), 0.42)
            code = ord(c) - 0xAC00
            cho, jung, jong = code // 588, (code % 588) // 28, code % 28
            jaw, wid = JUNG[jung]
            f0, f1 = int(t * FPS), max(int(t * FPS) + 1, int(t2 * FPS))
            loud = float(np.clip(np.mean(energy[f0:f1]) * 1.3, 0, 1)) if f1 <= len(energy) else 0.7
            jaw = jaw * (0.62 + 0.38 * loud)                 # 음절 단위 크기(프레임별 흔들림 없음)
            if cho in BILABIAL_CHO:      # 입술 꾹 → 터지듯 열림
                keys += [(t - 0.07, 0.0, wid * 0.3, 1.0, 0, 0, 0.6), (t + 0.03, 0.0, wid * 0.3, 1.0, 0, 0, 1.0),
                         (t + 0.06, jaw * 0.55, wid, 0.0, 0, 0, 0)]
            elif cho in SIBILANT_CHO:    # 이를 거의 다물고 입술은 옆으로
                keys += [(t - 0.03, 0.12, max(wid, 0.45), 0.0, 1.0, 0, 0), (t + 0.04, 0.16, max(wid, 0.35), 0.0, 0.8, 0, 0)]
            elif cho in ALVEOLAR_CHO:    # 혀끝이 윗니 뒤에 닿음
                keys += [(t - 0.03, 0.22, wid * 0.6 + 0.15, 0.0, 0.2, 1.0, 0), (t + 0.04, 0.3, wid * 0.7, 0.0, 0, 0.6, 0)]
            # 모음 (이중모음은 동그란 입에서 출발)
            if jung in GLIDE_W:
                keys.append((t + 0.25 * d, 0.35, -0.8, 0.0, 0, 0, 0))
            keys.append((t + 0.45 * d, jaw, wid, 0.0, 0.0, 0.0, 0))
            keys.append((t + 0.7 * d, jaw * 0.92, wid, 0.0, 0.0, 0.0, 0))
            # 받침
            if jong in BILABIAL_JONG:
                keys.append((t + 0.92 * d, 0.0, wid * 0.4, 1.0, 0, 0, 0.7))
            elif jong in ALVEOLAR_JONG:
                keys.append((t + 0.88 * d, 0.22, wid * 0.6, 0.0, 0.3, 0.9, 0))
            elif jong in VELAR_JONG:
                keys.append((t + 0.88 * d, jaw * 0.5, wid * 0.5, 0.0, 0, 0, 0))
            if t2 - t > 0.45:                               # 단어 사이 쉼: 입을 가볍게 닫음
                keys.append((t + d + 0.06, 0.0, 0.0, 0.25, 0, 0, 0))
        keys.append((e + 0.07, 0.0, 0.0, 0.0, 0, 0, 0))
    keys.append((n / FPS + 1, 0, 0, 0, 0, 0, 0))
    keys.sort(key=lambda k: k[0])
    kt = np.array([k[0] for k in keys]) - LEAD
    tt = np.arange(n) / FPS
    ch = [np.interp(tt, kt, [k[c] for k in keys]) for c in range(1, 7)]
    jaw, wid, clo, teeth, tongue, press = (_muscle_smooth(v, tau, rate, sg)
                                           for v, tau, rate, sg in zip(ch, TAU, MAX_RATE, SIGMA))
    jaw = _muscle_smooth(jaw * (1 - np.clip(clo, 0, 1)), 0.03, 0.16, 0.8)   # 입술이 닫힐 때도 턱은 부드럽게
    return (np.clip(jaw, 0, 1), np.clip(wid, -1, 1), np.clip(clo, 0, 1),
            np.clip(teeth, 0, 1), np.clip(tongue, 0, 1), np.clip(press, 0, 1))


# 근육처럼 부드럽게: 채널별 반응 시간(초)과 1프레임 최대 변화량
TAU = (0.045, 0.06, 0.018, 0.05, 0.05, 0.02)       # jaw, width, close, teeth, tongue, press
MAX_RATE = (0.14, 0.12, 0.45, 0.2, 0.2, 0.45)
SIGMA = (1.1, 1.1, 0.5, 1.0, 1.0, 0.5)               # 입술 닫힘은 또렷하게 유지


def _muscle_smooth(x: np.ndarray, tau: float, max_rate: float, sigma: float = 1.1) -> np.ndarray:
    """앞뒤 양방향 1차 필터(위상 지연 없음) + 프레임당 변화량 제한 + 가벼운 가우시안"""
    a = 1 - np.exp(-1 / (FPS * tau))
    y = x.astype(np.float64).copy()
    for i in range(1, len(y)):                     # 정방향
        y[i] = y[i - 1] + a * (y[i] - y[i - 1])
    for i in range(len(y) - 2, -1, -1):            # 역방향
        y[i] = y[i + 1] + a * (y[i] - y[i + 1])
    for i in range(1, len(y)):                     # 변화량 제한
        d = np.clip(y[i] - y[i - 1], -max_rate, max_rate)
        y[i] = y[i - 1] + d
    g = np.exp(-0.5 * (np.arange(-3, 4) / sigma) ** 2); g /= g.sum()
    return np.convolve(np.pad(y, 3, mode="edge"), g, "valid")
