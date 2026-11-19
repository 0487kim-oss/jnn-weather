"""
무료 엔진 ① 음성: Supertonic 2 한국어 TTS (오프라인, API 비용 없음)
- 모델: python tools/download_models.py 로 models/ 에 1회 다운로드 (~85MB)
- 숫자·단위를 한국어 읽기로 바꿔서 정확히 발음 (11시 → 열한 시, -3℃ → 영하 삼 도)
- 문장별로 생성해 각 문장의 실제 시작/끝 시간을 돌려줌 (자막·입 움직임 동기화용)
"""
import re
import subprocess
import wave
from pathlib import Path

import numpy as np

MODEL_DIR = Path("models/sherpa-onnx-supertonic-tts-int8-2026-03-06")
VOICE_SID = 1          # 0~4 여성, 5~9 남성. 1 = 밝고 경쾌한 톤(기본) / 0 = 여성 아나운서 톤 / 3 = 차분한 톤
SPEED = 1.1            # 말 속도 (또박또박: 0.97~1.0 / 경쾌하게: 1.1~1.15)
STEPS = 24             # 품질(높을수록 좋음, 느려짐)
LEAD, TAIL = 0.35, 0.6
GAP = 0.42             # 문장 사이 쉼 (문장 길이에 따라 자동 가감)

# ---------------------------------------------------------------
# 숫자 → 한국어 읽기
# ---------------------------------------------------------------
_D = "영일이삼사오육칠팔구"
_NATIVE_H = {1: "한", 2: "두", 3: "세", 4: "네", 5: "다섯", 6: "여섯", 7: "일곱",
             8: "여덟", 9: "아홉", 10: "열", 11: "열한", 12: "열두"}


def sino(n: int) -> str:
    if n == 0:
        return "영"
    out, units = "", [(10000, "만"), (1000, "천"), (100, "백"), (10, "십")]
    for u, name in units:
        q, n = divmod(n, u)
        if q:
            out += (sino(q) if u == 10000 else ("" if q == 1 else _D[q])) + name
    return out + (_D[n] if n else "")


def num_read(s: str) -> str:
    neg = s.startswith("-")
    s = s.lstrip("-")
    if "." in s:
        a, b = s.split(".")
        r = sino(int(a)) + " 점 " + "".join(_D[int(c)] for c in b)
    else:
        r = sino(int(s))
    return ("영하 " if neg else "") + r


def to_speech(text: str) -> str:
    t = text.replace("JNN", "제이엔엔 ").replace("KBS", "케이비에스")
    t = re.sub(r"(\d+)\s*시", lambda m: _NATIVE_H.get(int(m.group(1)), sino(int(m.group(1)))) + " 시", t)
    t = re.sub(r"(\d+)\s*월", lambda m: {6: "유", 10: "시"}.get(int(m.group(1)), sino(int(m.group(1)))) + "월", t)
    t = re.sub(r"(\d+)\s*일", lambda m: sino(int(m.group(1))) + "일", t)
    t = re.sub(r"(-?\d+(?:\.\d+)?)\s*[~∼]\s*(-?\d+(?:\.\d+)?)",
               lambda m: f"{m.group(1)}에서 {m.group(2)}", t)
    t = re.sub(r"(?:초속\s*)?(\d+(?:\.\d+)?)\s*m/s", lambda m: f"초속 {num_read(m.group(1))} 미터", t)
    units = [(r"℃|°C|°", " 도"), (r"%", " 퍼센트"), (r"mm|㎜", " 밀리미터"), (r"cm|㎝", " 센티미터"),
             (r"㎍/㎥", " 마이크로그램"), (r"km/h|㎞/h", " 킬로미터")]
    for pat, word in units:
        t = re.sub(rf"(-?\d+(?:\.\d+)?)\s*(?:{pat})", lambda m, w=word: num_read(m.group(1)) + w, t)
    t = re.sub(r"(?<![\w])(-?\d+(?:\.\d+)?)", lambda m: num_read(m.group(1)), t)
    return re.sub(r"\s+", " ", t).strip()


def split_sentences(script: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", script) if s.strip()]


# ---------------------------------------------------------------
# 합성
# ---------------------------------------------------------------
_tts = None


def _engine():
    global _tts
    if _tts is None:
        import sherpa_onnx as s
        m = MODEL_DIR
        if not m.exists():
            raise FileNotFoundError("TTS 모델이 없습니다. python tools/download_models.py 를 먼저 실행하세요.")
        cfg = s.OfflineTtsConfig(model=s.OfflineTtsModelConfig(
            supertonic=s.OfflineTtsSupertonicModelConfig(
                duration_predictor=str(m / "duration_predictor.int8.onnx"),
                text_encoder=str(m / "text_encoder.int8.onnx"),
                vector_estimator=str(m / "vector_estimator.int8.onnx"),
                vocoder=str(m / "vocoder.int8.onnx"),
                tts_json=str(m / "tts.json"),
                unicode_indexer=str(m / "unicode_indexer.bin"),
                voice_style=str(m / "voice.bin")),
            num_threads=2))
        _tts = s.OfflineTts(cfg)
    return _tts


def synth(sentences: list[str], out_wav: Path, gaps: list[float] | None = None) -> list[tuple[float, float]]:
    """문장 목록(화면용 원문) → 방송 음질 wav + 문장별 (시작, 끝) 초"""
    import sherpa_onnx as s
    tts = _engine()
    sr = tts.sample_rate
    parts, timing, cur = [np.zeros(int(sr * LEAD), np.float32)], [], LEAD
    for i, sent in enumerate(sentences):
        g = s.GenerationConfig()
        g.sid, g.speed, g.num_steps, g.extra = VOICE_SID, SPEED, STEPS, {"lang": "ko"}
        x = np.array(tts.generate(to_speech(sent), g).samples, np.float32)
        idx = np.where(np.abs(x) > 0.01)[0]
        if len(idx):
            x = x[max(0, idx[0] - int(0.02 * sr)): idx[-1] + int(0.06 * sr)]
        timing.append((cur, cur + len(x) / sr))
        parts.append(x)
        cur += len(x) / sr
        if gaps and i < len(sentences) - 1:
            gap = gaps[i]
        elif i < len(sentences) - 1:
            gap = GAP + (0.1 if len(sent) > 40 else 0) - (0.1 if len(sent) < 20 else 0)
        else:
            gap = TAIL
        parts.append(np.zeros(int(sr * gap), np.float32))
        cur += gap
    y = np.concatenate(parts)
    y = y / (np.abs(y).max() + 1e-9) * 0.89
    out_wav = Path(out_wav)
    raw = out_wav.with_name(out_wav.stem + "_raw.wav")
    with wave.open(str(raw), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((y * 32767).astype(np.int16).tobytes())
    # 방송용 음성 처리: 저역 정리, 명료도, 부드러운 압축, -16 LUFS
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-af",
                    "highpass=f=75,equalizer=f=3200:t=q:w=1.2:g=2,"
                    "acompressor=threshold=-20dB:ratio=2.5:attack=8:release=120:makeup=2,"
                    "loudnorm=I=-16:TP=-1.5:LRA=9",
                    "-ar", "44100", "-ac", "1", str(out_wav)], check=True)
    print(f"[음성] {out_wav} {cur:.1f}초 (Supertonic, 화자 {VOICE_SID})")
    return timing


def add_intro(voice: Path, timing, intro: float):
    """시그널이 울리는 동안(intro초) 앞에 무음을 붙이고 문장 타이밍을 뒤로 이동"""
    with wave.open(str(voice)) as w:
        sr = w.getframerate(); x = w.readframes(w.getnframes())
    pad = b"\x00\x00" * int(intro * sr)
    with wave.open(str(voice), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(pad + x)
    return [(a + intro, b + intro) for a, b in timing]
