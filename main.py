"""
JNN뉴스 전남광주 아침 날씨 — 매일 자동 제작 (1~7단계 통합)

엔진 2가지
  free (기본) : Supertonic 오프라인 음성 + 오프라인 립싱크. API 비용 0원
                OPENAI_API_KEY 가 있으면 날씨별 의상 변환까지 (이미지 편집 1회 비용만)
  api         : OpenAI 의상 변환 + Google TTS + D-ID 립싱크 (유료)
  → --engine 미지정 시 DID_API_KEY 와 OPENAI_API_KEY 가 모두 있으면 api, 아니면 free

실행:  python main.py                       (자동 엔진, 업로드·카톡까지)
       python main.py --no-upload           (영상만)
       python main.py --engine free --weather-json sample_weather.json --no-upload  (API 없이 테스트)
"""
import argparse
import datetime as dt
import json
import os
import sys
import traceback
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import caster_compose as cc
from script_writer import write_script

SHEET = "assets/kim_haneul_sheet.png"
OUT = Path("output")


def load_weather(path: str | None) -> dict:
    if path:
        w = json.loads(Path(path).read_text(encoding="utf-8"))
        w["date"] = dt.date.fromisoformat(w["date"]) if "date" in w else dt.date.today()
        return w
    from weather import fetch_weather
    return fetch_weather()


def pick_engine(arg: str | None) -> str:
    if arg:
        return arg
    return "api" if os.getenv("DID_API_KEY") and os.getenv("OPENAI_API_KEY") else "free"


def bgm_path():
    return next((p for p in [Path("assets/bgm.mp3"), Path("assets/bgm.wav")] if p.exists()), None)


def run(engine: str, upload: bool, weather_json: str | None, outfit: bool = True) -> Path:
    OUT.mkdir(exist_ok=True)
    w = load_weather(weather_json)                         # 1 날씨
    script = write_script(w)                                # 3 대본
    print(f"[엔진] {engine}\n[대본] {script}")
    stamp = f"{w['date']:%Y%m%d}"
    final = OUT / f"JNN_weather_{stamp}.mp4"

    if engine == "free":
        from free_lipsync import render_talk
        from free_tts import split_sentences, synth
        sentences = split_sentences(script)
        voice = OUT / f"voice_{stamp}.wav"
        caster = Path("assets/caster_hi.png")
        if outfit and os.getenv("OPENAI_API_KEY"):          # 2·4 의상 변환 (머리 보존)
            try:
                from outfit import dress_caster
                caster = dress_caster(w, OUT / f"caster_outfit_{stamp}.png")
            except Exception as e:
                print("[경고] 의상 변환 실패, 기본 의상 사용:", e)
        from free_tts import add_intro
        timing = synth(sentences, voice)                    # 5 음성 (오프라인, 밝은 여성 톤)
        if cc.INTRO_SEC:
            timing = add_intro(voice, timing, cc.INTRO_SEC) # 시그널이 울리는 동안 비워 둠
        talk = render_talk(voice, timing, w, OUT / f"talk_{stamp}.mp4", caster, sentences)  # 5 발음 립싱크·전신 동작·카메라
        nomusic = OUT / f"nomusic_{stamp}.mp4"
        cc.compose(talk, w, script, nomusic, None, timing=timing, sentences=sentences)  # 6 그래픽·자막·엔딩
        cc.finalize_audio(nomusic, final, cc.JINGLE, bgm_path())                        # 6 시그널·배경음악
    else:
        import caster_image as ci
        import caster_video as cv
        image = ci.make_caster_image(SHEET, w)              # 2·4 의상 변환
        talk = cv.make_caster_video(image, script)          # 5 Google TTS + D-ID
        if cc.INTRO_SEC:
            talk = cc.prepend_intro(Path(talk), OUT / f"talk_intro_{stamp}.mp4")
        nomusic = OUT / f"nomusic_{stamp}.mp4"
        cc.compose(Path(talk), w, cv.normalize_ko(script), nomusic, None)       # 6
        cc.finalize_audio(nomusic, final, cc.JINGLE, bgm_path())

    if upload:                                              # 7
        from kakao_notify import send_to_me
        from youtube_upload import upload_short
        url = upload_short(str(final), w, script)
        send_to_me(w, url)
    return final


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", choices=["free", "api"])
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--weather-json", help="날씨 API 대신 JSON 파일 사용 (테스트용)")
    ap.add_argument("--no-outfit", action="store_true", help="의상 변환 끄기")
    args = ap.parse_args()
    try:
        print("\n완성:", run(pick_engine(args.engine), not args.no_upload, args.weather_json, not args.no_outfit))
    except Exception as e:
        traceback.print_exc()
        if not args.no_upload and os.getenv("KAKAO_REFRESH_TOKEN"):
            from kakao_notify import send_error
            send_error(f"{type(e).__name__}: {e}"[:150])
        sys.exit(1)
