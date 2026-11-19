"""
JNN뉴스 전남광주 날씨 샘플 영상 한 번에 만들기 (4→5→6단계)

1) pip install -r requirements.txt   (ffmpeg 별도 설치)
2) .env.example 을 .env 로 복사하고 키 입력
3) python run_sample.py
   → output/JNN_전남광주날씨_YYYYMMDD.mp4
"""
import datetime as dt
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import caster_compose as cc
import caster_image as ci
import caster_video as cv

SHEET = "assets/kim_haneul_sheet.png"

# 1단계 fetch_weather() 연결 전까지 쓰는 예시 데이터
WEATHER = {
    "date": dt.date.today() + dt.timedelta(days=1),
    "region": "전남광주",
    "temp": 6, "tmin": 3, "tmax": 11,
    "sky": "흐림", "pty": "비", "pop": 70, "pm": "보통",
}


def build_script(w: dict) -> str:
    """3단계 LLM 대본 연결 전까지 쓰는 템플릿 대본"""
    d = w["date"]
    rain = w["pty"] not in ("", "없음")
    sky = {"맑음": "맑겠고", "구름많음": "구름이 많겠고", "흐림": "흐리겠고"}.get(w["sky"], "")
    lines = [
        f"안녕하세요, {d.month}월 {d.day}일 아침 8시 {w['region']} 날씨입니다.",
        f"현재 광주의 기온은 {w['temp']}℃로 출발하고 있습니다.",
        (f"오늘은 {sky} {w['pty']} 소식이 있겠습니다. 강수확률은 {w['pop']}%이니, 우산 꼭 챙기시기 바랍니다."
         if rain else f"오늘은 {sky}, 강수확률은 {w['pop']}%입니다."),
        f"낮 최고기온은 {w['tmax']}℃, 아침 최저기온은 {w['tmin']}℃로 예상됩니다.",
        f"미세먼지는 {w['pm']} 수준입니다.",
        "오늘 하루도 행복하게 보내세요.",
        "지금까지 JNN뉴스 기상캐스터 김하늘이었습니다.",
    ]
    return " ".join(lines)


def check_env():
    need = {
        "OPENAI_API_KEY": "OpenAI (의상 변환 이미지)",
        "GOOGLE_APPLICATION_CREDENTIALS": "Google Cloud TTS (아나운서 음성)",
        "DID_API_KEY": "D-ID (립싱크)",
    }
    missing = [f"  - {k}: {v}" for k, v in need.items() if not os.getenv(k)]
    if missing:
        sys.exit("다음 키가 .env 에 없습니다:\n" + "\n".join(missing))
    if not Path(os.environ["GOOGLE_APPLICATION_CREDENTIALS"]).exists():
        sys.exit("GOOGLE_APPLICATION_CREDENTIALS 경로의 json 파일이 없습니다.")


def main():
    check_env()
    stamp = WEATHER["date"].strftime("%Y%m%d")
    script = build_script(WEATHER)
    print("[대본]", script)

    # 4단계: 의상 변환 캐스터 이미지
    image = ci.make_caster_image(SHEET, WEATHER)

    # 5단계: 아나운서 음성 + 립싱크
    talk = cv.make_caster_video(image, script)

    # 6단계: 타이틀·카드·자막·로고·엔딩 합성
    bgm = next((p for p in [Path("assets/bgm.mp3"), Path("assets/bgm.wav")] if p.exists()), None)
    out = cc.compose(Path(talk), WEATHER, cv.normalize_ko(script),
                     Path("output") / f"JNN_전남광주날씨_{stamp}.mp4",
                     bgm)
    print("\n완성:", out)


if __name__ == "__main__":
    main()
