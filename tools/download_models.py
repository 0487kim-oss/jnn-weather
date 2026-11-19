"""무료 엔진용 모델을 models/ 에 내려받기 (1회)
- Supertonic 2 한국어 음성 (~85MB)
- 한국어 음성인식 zipformer (발음 기반 립싱크용, int8만 보관 ~80MB)"""
import tarfile
import urllib.request
from pathlib import Path

BASE = "https://github.com/k2-fsa/sherpa-onnx/releases/download"
MODELS = [
    ("tts-models", "sherpa-onnx-supertonic-tts-int8-2026-03-06", "voice.bin"),
    ("asr-models", "sherpa-onnx-zipformer-korean-2024-06-24", "tokens.txt"),
]
dst = Path("models"); dst.mkdir(exist_ok=True)
for tag, name, check in MODELS:
    if (dst / name / check).exists():
        print("이미 있음:", name); continue
    tmp = dst / f"{name}.tar.bz2"
    print("다운로드:", name)
    urllib.request.urlretrieve(f"{BASE}/{tag}/{name}.tar.bz2", tmp)
    with tarfile.open(tmp) as t:
        t.extractall(dst)
    tmp.unlink()
    for f in (dst / name).glob("*.onnx"):          # 용량 절약: int8 모델만 남김
        if ".int8." not in f.name:
            f.unlink()
    print("완료:", dst / name)
