"""
5단계: 한국어 여성 아나운서 음성(TTS) + 립싱크 말하는 영상 생성
- 입력: 4단계 이미지(output/caster_YYYYMMDD_916.png) + 대본 텍스트
- 출력: output/caster_YYYYMMDD_talk.mp4 (1080x1920, 9:16)

설치:  pip install google-cloud-texttospeech requests
       (ffmpeg 필요: sudo apt install ffmpeg / brew install ffmpeg)
환경변수:
  GOOGLE_APPLICATION_CREDENTIALS=/path/to/gcp-key.json   # Google Cloud TTS
  DID_API_KEY=xxxxxxxx                                    # D-ID 립싱크 API

실행:  python caster_video.py --image output/caster_20261119_916.png
       python caster_video.py --image ... --tts-only     # 음성만 먼저 확인
"""
import argparse
import datetime as dt
import html
import os
import re
import subprocess
import time
from pathlib import Path

import requests

WORK_DIR = Path("output")
OUT_W, OUT_H = 1080, 1920

# ---------------------------------------------------------------
# 아나운서 톤 설정 (Google Cloud TTS)
# ---------------------------------------------------------------
VOICE_NAME = "ko-KR-Neural2-A"   # 한국어 여성 Neural 음성 (B도 여성, 비교해보고 선택)
SPEAKING_RATE = 1.05             # 뉴스 리딩 속도: 1.0~1.1
PITCH = 1.0                      # 반음 단위. 밝은 톤 +1, 차분한 톤 -1
SENTENCE_PAUSE_MS = 350          # 문장 사이 쉼
BREATH_PAUSE_MS = 150            # 쉼표 쉼


# ---------------------------------------------------------------
# 1) 대본 정리: 기호를 읽기 좋은 한국어로 바꾸고 SSML로 변환
# ---------------------------------------------------------------
def normalize_ko(text: str) -> str:
    rules = [
        (r"(-?\d+(?:\.\d+)?)\s*℃", r"\1도"),
        (r"(-?\d+(?:\.\d+)?)\s*°C", r"\1도"),
        (r"(\d+)\s*%", r"\1퍼센트"),
        (r"(\d+(?:\.\d+)?)\s*mm", r"\1밀리미터"),
        (r"(?:초속\s*)?(\d+(?:\.\d+)?)\s*m/s", r"초속 \1미터"),
        (r"(\d+(?:\.\d+)?)\s*㎍/㎥", r"\1마이크로그램"),
        (r"(?<![\d\w])-(\d)", r"영하 \1"),
        (r"(\d)\s*~\s*", r"\1에서 "),
    ]
    for pat, rep in rules:
        text = re.sub(pat, rep, text)
    return re.sub(r"\s+", " ", text).strip()


def to_ssml(text: str) -> str:
    text = normalize_ko(text)
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    parts = []
    for s in sentences:
        s = html.escape(s)
        s = s.replace(",", f',<break time="{BREATH_PAUSE_MS}ms"/>')
        parts.append(f"<s>{s}</s>")
    body = f'<break time="{SENTENCE_PAUSE_MS}ms"/>'.join(parts)
    return f'<speak><break time="300ms"/>{body}<break time="500ms"/></speak>'


# ---------------------------------------------------------------
# 2) TTS: 여성 아나운서 톤 음성 생성
# ---------------------------------------------------------------
def make_voice(script: str, out_path: Path) -> Path:
    from google.cloud import texttospeech as tts

    client = tts.TextToSpeechClient()
    res = client.synthesize_speech(
        input=tts.SynthesisInput(ssml=to_ssml(script)),
        voice=tts.VoiceSelectionParams(language_code="ko-KR", name=VOICE_NAME),
        audio_config=tts.AudioConfig(
            audio_encoding=tts.AudioEncoding.MP3,
            speaking_rate=SPEAKING_RATE,
            pitch=PITCH,
            sample_rate_hertz=44100,
            effects_profile_id=["headphone-class-device"],
        ),
    )
    out_path.write_bytes(res.audio_content)
    print("[음성]", out_path, f"{audio_seconds(out_path):.1f}초")
    return out_path


def audio_seconds(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


# ---------------------------------------------------------------
# 3) 립싱크: D-ID API (이미지 + 음성 → 말하는 영상)
# ---------------------------------------------------------------
DID_BASE = "https://api.d-id.com"


def _did_headers() -> dict:
    # D-ID 스튜디오에서 발급한 키를 그대로 사용
    return {"Authorization": f"Basic {os.environ['DID_API_KEY']}",
            "accept": "application/json"}


def _did_upload(endpoint: str, field: str, path: Path, mime: str) -> str:
    with open(path, "rb") as f:
        r = requests.post(f"{DID_BASE}/{endpoint}", headers=_did_headers(),
                          files={field: (path.name, f, mime)}, timeout=120)
    r.raise_for_status()
    return r.json()["url"]


def make_talking(image: Path, audio: Path, out_path: Path,
                 timeout_sec: int = 600) -> Path:
    img_url = _did_upload("images", "image", image, "image/png")
    aud_url = _did_upload("audios", "audio", audio, "audio/mpeg")

    payload = {
        "source_url": img_url,
        "script": {"type": "audio", "audio_url": aud_url},
        "config": {
            "stitch": True,          # 전신 이미지에 얼굴 움직임을 다시 합성
            "fluent": True,
            "pad_audio": 0.0,
        },
    }
    r = requests.post(f"{DID_BASE}/talks", json=payload,
                      headers=_did_headers(), timeout=60)
    r.raise_for_status()
    talk_id = r.json()["id"]
    print("[립싱크] 요청됨:", talk_id)

    start = time.time()
    while True:
        s = requests.get(f"{DID_BASE}/talks/{talk_id}",
                         headers=_did_headers(), timeout=30).json()
        status = s.get("status")
        if status == "done":
            video = requests.get(s["result_url"], timeout=300)
            out_path.write_bytes(video.content)
            print("[립싱크] 완료:", out_path)
            return out_path
        if status in ("error", "rejected"):
            raise RuntimeError(f"D-ID 실패: {s}")
        if time.time() - start > timeout_sec:
            raise TimeoutError("D-ID 처리 시간 초과")
        time.sleep(5)


# ---------------------------------------------------------------
# 4) 최종 규격 맞추기: 1080x1920, 30fps, H.264/AAC
# ---------------------------------------------------------------
def normalize_916(src: Path, dst: Path) -> Path:
    vf = (f"scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=decrease,"
          f"pad={OUT_W}:{OUT_H}:(ow-iw)/2:(oh-ih)/2:color=white,"
          f"fps=30,format=yuv420p")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-vf", vf,
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
         "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(dst)],
        check=True)
    print("[완료]", dst)
    return dst


# ---------------------------------------------------------------
# 전체 실행
# ---------------------------------------------------------------
def make_caster_video(image: Path, script: str) -> Path:
    WORK_DIR.mkdir(exist_ok=True)
    stamp = dt.date.today().strftime("%Y%m%d")
    voice = make_voice(script, WORK_DIR / f"voice_{stamp}.mp3")
    raw = make_talking(image, voice, WORK_DIR / f"caster_{stamp}_talk_raw.mp4")
    return normalize_916(raw, WORK_DIR / f"caster_{stamp}_talk.mp4")


# 3단계 write_script() 결과가 들어올 자리 (예시 대본)
SAMPLE_SCRIPT = (
    "안녕하세요, 11월 19일 아침 8시 전남광주 날씨입니다. "
    "현재 광주의 기온은 6℃로, 어제보다 쌀쌀하게 출발하고 있습니다. "
    "오전 중 흐리다가 낮부터 비가 내리겠고, 강수확률은 70%입니다. "
    "예상 강수량은 5~10mm 정도로, 외출하실 때 우산 꼭 챙기시기 바랍니다. "
    "낮 최고기온은 11℃, 바람은 초속 3m/s 내외로 불겠습니다. "
    "따뜻하게 입으시고, 오늘 하루도 행복하게 보내세요. "
    "지금까지 기상캐스터 김하늘이었습니다."
)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True, help="4단계에서 만든 9:16 이미지")
    ap.add_argument("--script", help="대본 txt 파일 (없으면 예시 대본)")
    ap.add_argument("--tts-only", action="store_true", help="음성만 생성")
    ap.add_argument("--ssml", action="store_true", help="SSML만 출력")
    args = ap.parse_args()

    script = Path(args.script).read_text(encoding="utf-8") if args.script else SAMPLE_SCRIPT

    if args.ssml:
        print(to_ssml(script))
    elif args.tts_only:
        WORK_DIR.mkdir(exist_ok=True)
        make_voice(script, WORK_DIR / "voice_test.mp3")
    else:
        make_caster_video(Path(args.image), script)
