import os
"""
6단계: 9:16 화면 합성 (상단 타이틀 + 날씨 카드 + 자막 + 배경음악)
- 입력: 5단계 영상(output/caster_YYYYMMDD_talk.mp4) + 날씨 dict + 대본
- 출력: output/weather_YYYYMMDD_final.mp4 (1080x1920)

설치:  pip install pillow   (ffmpeg 필요)
로고:  assets/jnn_logo_h.png(가로형), assets/jnn_logo_v.png(세로형)
폰트:  fonts/Pretendard-Bold.otf, fonts/Pretendard-Regular.otf 를 넣어두면 우선 사용
       (https://github.com/orioncactus/pretendard 무료 폰트)
실행:  python caster_compose.py --video output/caster_20261119_talk.mp4
       python caster_compose.py --video ... --bgm bgm/morning.mp3
"""
import argparse
import datetime as dt
import re
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1080, 1920
WORK_DIR = Path("output")
LAYER_DIR = WORK_DIR / "layers"

# ---------------------------------------------------------------
# 디자인 설정 (캐릭터 시트 컬러 팔레트 기반)
# ---------------------------------------------------------------
NAVY = (38, 62, 120)
LAVENDER = (168, 174, 222)
IVORY = (250, 244, 234)
PINK = (244, 186, 196)
WHITE = (255, 255, 255)
SUB_BG = (20, 28, 52, 190)

# 방송사 로고 (투명 배경 PNG)
LOGO_H = Path("assets/jnn_logo_h.png")   # 가로형: 화면 우측 상단
LOGO_V = Path("assets/jnn_logo_v.png")   # 세로형: 엔딩 카드
ORANGE = (240, 120, 30)
ENDING_SEC = 2.5                          # 엔딩 카드 길이

BGM_VOLUME = 0.12        # 목소리 대비 배경음악 크기
LEAD_IN = 0.3            # 5단계 SSML 시작 쉼 (자막 타이밍 계산용)
TAIL = 0.5               # 끝 쉼
SENT_GAP = 0.35          # 문장 사이 쉼

# ---------------------------------------------------------------
# 폰트 찾기 (Pretendard → 맑은고딕 → 애플고딕 → Noto)
# ---------------------------------------------------------------
FONT_CANDIDATES = {
    "bold": [
        ("fonts/Pretendard-Bold.otf", 0),
        ("C:/Windows/Fonts/malgunbd.ttf", 0),
        ("/System/Library/Fonts/AppleSDGothicNeo.ttc", 6),
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 1),
    ],
    "regular": [
        ("fonts/Pretendard-Regular.otf", 0),
        ("C:/Windows/Fonts/malgun.ttf", 0),
        ("/System/Library/Fonts/AppleSDGothicNeo.ttc", 0),
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 1),
    ],
}


def font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    for path, idx in FONT_CANDIDATES[kind]:
        if Path(path).exists():
            return ImageFont.truetype(path, size, index=idx)
    raise FileNotFoundError("한글 폰트를 찾을 수 없습니다. fonts/ 폴더에 Pretendard를 넣어주세요.")


def rounded_box(size, radius, fill, shadow=True):
    w, h = size
    pad = 30 if shadow else 0
    im = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
    if shadow:
        sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
        ImageDraw.Draw(sh).rounded_rectangle(
            (pad, pad + 8, pad + w, pad + h + 8), radius, fill=(0, 0, 0, 70))
        im = Image.alpha_composite(im, sh.filter(ImageFilter.GaussianBlur(14)))
    ImageDraw.Draw(im).rounded_rectangle((pad, pad, pad + w, pad + h), radius, fill=fill)
    return im, pad


# ---------------------------------------------------------------
# 날씨 아이콘 (외부 파일 없이 직접 그림)
# ---------------------------------------------------------------
def weather_icon(sky: str, pty: str, size=200) -> Image.Image:
    s = size * 4  # 4배로 그린 뒤 축소 → 부드러운 외곽선
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    sun_c = (255, 196, 61)
    cloud_c = (236, 240, 248) if pty in ("", "없음") else (196, 204, 222)

    def sun(cx, cy, r):
        import math
        for i in range(8):
            a = math.pi / 4 * i
            d.line((cx + math.cos(a) * r * 1.35, cy + math.sin(a) * r * 1.35,
                    cx + math.cos(a) * r * 1.75, cy + math.sin(a) * r * 1.75),
                   fill=sun_c, width=int(r * 0.22))
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=sun_c)

    def cloud(x, y, k=1.0):
        for ex in [(0.10, 0.35, 0.55, 0.75), (0.30, 0.18, 0.75, 0.68),
                   (0.52, 0.32, 0.92, 0.75)]:
            d.ellipse((x + ex[0] * s * k, y + ex[1] * s * k,
                       x + ex[2] * s * k, y + ex[3] * s * k), fill=cloud_c,
                      outline=(150, 160, 190), width=int(s * 0.012))
        d.rounded_rectangle((x + 0.12 * s * k, y + 0.52 * s * k,
                             x + 0.90 * s * k, y + 0.75 * s * k),
                            int(0.1 * s * k), fill=cloud_c)

    rainy = pty in ("비", "소나기", "비/눈")
    snowy = pty in ("눈", "비/눈")

    if sky == "맑음" and not (rainy or snowy):
        sun(s / 2, s / 2, s * 0.22)
    elif sky == "구름많음" and not (rainy or snowy):
        sun(s * 0.36, s * 0.34, s * 0.16)
        cloud(s * 0.02, s * 0.12, 0.95)
    else:
        cloud(0, -s * 0.08, 1.0)

    if rainy:
        for i, x in enumerate([0.28, 0.48, 0.68]):
            y0 = 0.72 + (i % 2) * 0.05
            d.line((x * s, y0 * s, (x - 0.06) * s, (y0 + 0.16) * s),
                   fill=(70, 130, 230), width=int(s * 0.04))
    if snowy:
        for x, y in [(0.32, 0.80), (0.52, 0.88), (0.72, 0.80)]:
            r = s * 0.035
            d.ellipse((x * s - r, y * s - r, x * s + r, y * s + r), fill=(120, 170, 240))
    return im.resize((size, size), Image.LANCZOS)


# ---------------------------------------------------------------
# 1) 상단 타이틀
# ---------------------------------------------------------------
def make_header(w: dict) -> Path:
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    date = w["date"]
    wd = "월화수목금토일"[date.weekday()]
    date_txt = f"{date.month}월 {date.day}일 ({wd}) {w.get('time_label', '오전 8시')}"

    pill, pad = rounded_box((360, 64), 32, NAVY + (235,))
    im.alpha_composite(pill, (60 - pad, 90 - pad))
    f_pill = font("bold", 32)
    d.text((60 + 180, 90 + 32), w.get("pill_text", "TODAY WEATHER"), font=f_pill, fill=WHITE, anchor="mm")

    f_big = font("bold", 76)
    f_mid = font("regular", 40)
    for dx, dy in [(-2, 0), (2, 0), (0, -2), (0, 2), (0, 4)]:   # 외곽선 효과
        d.text((60 + dx, 175 + dy), f"{w['region']} 날씨", font=f_big, fill=(255, 255, 255, 230))
    d.text((60, 175), f"{w['region']} 날씨", font=f_big, fill=NAVY)
    d.text((64, 275), date_txt, font=f_mid, fill=NAVY,
           stroke_width=3, stroke_fill=(255, 255, 255, 220))

    if LOGO_H.exists():
        logo = Image.open(LOGO_H).convert("RGBA")
        lh = 64
        logo = logo.resize((int(logo.width * lh / logo.height), lh), Image.LANCZOS)
        bw, bh = logo.width + 44, lh + 26
        bg, pad = rounded_box((bw, bh), bh // 2, (255, 255, 255, 235))
        bx, by = W - 60 - bw, 77
        im.alpha_composite(bg, (bx - pad, by - pad))
        im.alpha_composite(logo, (bx + 22, by + 13))

    p = LAYER_DIR / "header.png"
    im.save(p)
    return p


# ---------------------------------------------------------------
# 2) 날씨 카드
# ---------------------------------------------------------------
def make_card(w: dict) -> Path:
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    cw, ch, x0, y0 = 960, 290, 60, 1330
    box, pad = rounded_box((cw, ch), 40, IVORY + (238,))
    im.alpha_composite(box, (x0 - pad, y0 - pad))
    d = ImageDraw.Draw(im)

    # 왼쪽: 아이콘 + 현재기온 + 상태
    im.alpha_composite(weather_icon(w["sky"], w["pty"], 190), (x0 + 30, y0 + 30))
    d.text((x0 + 235, y0 + 120), f"{w['temp']:g}°", font=font("bold", 120),
           fill=NAVY, anchor="lm")
    status = w["sky"] if w["pty"] in ("", "없음") else f"{w['sky']} · {w['pty']}"
    d.text((x0 + 240, y0 + 225), status, font=font("bold", 40), fill=NAVY, anchor="lm")

    # 오른쪽: 상세 정보
    d.line((x0 + 560, y0 + 40, x0 + 560, y0 + ch - 40), fill=LAVENDER, width=3)
    rows = w.get("card_rows") or [
        (w.get("minmax_label", "최저 / 최고"), f"{w['tmin']:g}° / {w['tmax']:g}°"),
        (w.get("pop_label", "강수확률"), f"{w['pop']}%"),
        ("미세먼지", w["pm"]),
    ]
    pm_color = {"좋음": (60, 140, 230), "보통": (60, 170, 110),
                "나쁨": (240, 150, 40), "매우나쁨": (220, 60, 60)}
    f_l, f_v = font("regular", 32), font("bold", 38)
    for i, (k, v) in enumerate(rows):
        y = y0 + 70 + i * 78
        d.text((x0 + 595, y), k, font=f_l, fill=(110, 118, 150), anchor="lm")
        color = pm_color.get(v, NAVY) if k == "미세먼지" else NAVY
        d.text((x0 + cw - 35, y), v, font=f_v, fill=color, anchor="rm")

    p = LAYER_DIR / "card.png"
    im.save(p)
    return p


# ---------------------------------------------------------------
# 3) 자막: 문장 단위로 나누고 음성 길이에 맞춰 시간 배분
# ---------------------------------------------------------------
def split_sentences(script: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", script) if s.strip()]


def wrap(text: str, f, max_w: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for wd in words:
        test = f"{cur} {wd}".strip()
        if f.getlength(test) <= max_w:
            cur = test
        else:
            lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)
    return lines


def subtitle_chunks(script: str, f, max_w=880) -> list[str]:
    """문장을 쉼표(호흡) 단위로 나눈 뒤, 2줄을 넘지 않게 묶어 자막 덩어리로 만듦.
    두 구절이 각각 한 줄에 들어가면 구절 단위로 줄을 바꿈"""
    def fmt(group):
        if len(group) == 2 and all(f.getlength(g) <= max_w for g in group):
            return "\n".join(group)
        return "\n".join(wrap(" ".join(group), f, max_w))

    chunks = []
    for s in split_sentences(script):
        phrases = [p.strip() for p in re.split(r"(?<=,)\s+", s) if p.strip()]
        group = []
        for ph in phrases:
            if group and len(fmt(group + [ph]).split("\n")) > 2:
                chunks.append(fmt(group))
                group = [ph]
            else:
                group.append(ph)
        if group:
            lines = fmt(group).split("\n")
            for k in range(0, len(lines), 2):
                chunks.append("\n".join(lines[k:k + 2]))
    return chunks

def time_subtitles(script: str, duration: float, f) -> list[tuple]:
    sents = split_sentences(script)
    speech = duration - LEAD_IN - TAIL - SENT_GAP * (len(sents) - 1)
    total_chars = sum(len(s.replace(" ", "")) for s in sents)
    t, out = LEAD_IN, []
    for s in sents:
        s_dur = speech * len(s.replace(" ", "")) / total_chars
        parts = subtitle_chunks(s, f)
        p_chars = [len(p.replace(" ", "").replace("\n", "")) for p in parts]
        for p, c in zip(parts, p_chars):
            d = s_dur * c / sum(p_chars)
            out.append((p, t, t + d))
            t += d
        t += SENT_GAP
    return out


def make_subtitle_png(text: str, idx: int) -> Path:
    f = font("bold", 46)
    lines = text.split("\n")
    lh = 64
    tw = max(f.getlength(l) for l in lines)
    bw, bh = int(tw + 70), lh * len(lines) + 40
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    box, pad = rounded_box((bw, bh), 26, SUB_BG, shadow=False)
    bx, by = (W - bw) // 2, 1665
    im.alpha_composite(box, (bx, by))
    d = ImageDraw.Draw(im)
    for i, l in enumerate(lines):
        d.text((W // 2, by + 20 + lh * i + lh // 2), l, font=f, fill=WHITE, anchor="mm")
    p = LAYER_DIR / f"sub_{idx:02d}.png"
    im.save(p)
    return p


def make_ending(w: dict) -> Path:
    im = Image.new("RGBA", (W, H), IVORY + (255,))
    d = ImageDraw.Draw(im)
    if LOGO_V.exists():
        logo = Image.open(LOGO_V).convert("RGBA")
        lw = 560
        logo = logo.resize((lw, int(logo.height * lw / logo.width)), Image.LANCZOS)
        im.alpha_composite(logo, ((W - lw) // 2, 620))
        y = 620 + logo.height + 90
    else:
        y = 900
    d.text((W // 2, y), "매일 아침 8시", font=font("bold", 54), fill=NAVY, anchor="mm")
    d.text((W // 2, y + 80), f"{w['region']} 날씨를 전해드립니다",
           font=font("regular", 44), fill=NAVY, anchor="mm")
    d.line((W // 2 - 60, y + 150, W // 2 + 60, y + 150), fill=ORANGE, width=6)
    p = LAYER_DIR / "ending.png"
    im.save(p)
    return p


# ---------------------------------------------------------------
# 4) FFmpeg 합성
# ---------------------------------------------------------------
def duration_of(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", str(path)],
                       capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def exact_subtitles(sentences: list[str], timing, f) -> list[tuple]:
    """문장별 실제 음성 구간(timing)에 맞춘 자막"""
    out = []
    for (s, e), sent in zip(timing, sentences):
        parts = subtitle_chunks(sent, f)
        chars = [max(1, len(p.replace(" ", "").replace("\n", ""))) for p in parts]
        t = s
        for k, (p, c) in enumerate(zip(parts, chars)):
            d = (e - s) * c / sum(chars)
            out.append((p, t, t + d + (0.25 if k == len(parts) - 1 else 0)))
            t += d
    return out


def compose(video: Path, weather: dict, script: str, out: Path,
            bgm: Path | None = None, timing=None, sentences: list[str] | None = None) -> Path:
    LAYER_DIR.mkdir(parents=True, exist_ok=True)
    dur = duration_of(video)
    header, card = make_header(weather), make_card(weather)
    if timing and sentences:
        subs = exact_subtitles(sentences, timing, font("bold", 46))
    else:
        subs = time_subtitles(script, dur, font("bold", 46))

    ending = make_ending(weather)
    total = dur + ENDING_SEC

    inputs = ["-i", str(video), "-loop", "1", "-i", str(header),
              "-loop", "1", "-i", str(card)]
    for i, (txt, _, _) in enumerate(subs):
        inputs += ["-loop", "1", "-i", str(make_subtitle_png(txt, i))]

    # 타이틀·카드는 페이드인 + 살짝 위로 올라오는 등장 효과
    fc = [
        f"[0:v]scale=1080:1920,setsar=1,fps=30,"
        f"tpad=stop_mode=clone:stop_duration={ENDING_SEC}[base]",
        "[1:v]format=rgba,fade=in:st=0.2:d=0.5:alpha=1[hd]",
        "[2:v]format=rgba,fade=in:st=0.6:d=0.5:alpha=1[cd]",
        "[base][hd]overlay=0:0:shortest=1[v1]",
        "[v1][cd]overlay=0:'if(lt(t,0.6),40,if(lt(t,1.1),40-80*(t-0.6),0))':shortest=1[v2]",
    ]
    last = "v2"
    for i, (_, s, e) in enumerate(subs):
        fc.append(f"[{last}][{i + 3}:v]overlay=0:0:shortest=1:"
                  f"enable='between(t,{s:.2f},{e:.2f})'[s{i}]")
        last = f"s{i}"

    # 엔딩 카드: 영상이 끝난 뒤 페이드인
    ei = 3 + len(subs)
    inputs += ["-loop", "1", "-i", str(ending)]
    fc.append(f"[{ei}:v]format=rgba,fade=in:st={dur:.2f}:d=0.4:alpha=1[ed]")
    fc.append(f"[{last}][ed]overlay=0:0:enable='gte(t,{dur:.2f})'[vend]")
    last = "vend"

    fc.append(f"[0:a]apad=pad_dur={ENDING_SEC}[voice]")
    audio_map = "[voice]"
    if bgm:
        bi = ei + 1
        inputs += ["-stream_loop", "-1", "-i", str(bgm)]
        fc.append(f"[{bi}:a]volume={BGM_VOLUME},afade=t=in:d=1,"
                  f"afade=t=out:st={max(total - 2, 0):.2f}:d=2[bg]")
        fc.append("[voice][bg]amix=inputs=2:duration=first:normalize=0[aout]")
        audio_map = "[aout]"

    cmd = ["ffmpeg", "-y", "-loglevel", "error", *inputs,
           "-filter_complex", ";".join(fc),
           "-map", f"[{last}]", "-map", audio_map,
           "-t", f"{total:.2f}", "-r", "30",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)]
    subprocess.run(cmd, check=True)
    print("[완료]", out)
    return out


# ---------------------------------------------------------------
# 실행 (1단계 날씨 + 3단계 대본이 들어올 자리)
# ---------------------------------------------------------------
SAMPLE_WEATHER = {
    "date": dt.date.today() + dt.timedelta(days=1),
    "region": "전남광주",
    "temp": 6, "tmin": 3, "tmax": 11,
    "sky": "흐림", "pty": "비", "pop": 70, "pm": "보통",
}
SAMPLE_SCRIPT = (
    "안녕하세요, 11월 19일 아침 8시 전남광주 날씨입니다. "
    "현재 광주의 기온은 6도로, 어제보다 쌀쌀하게 출발하고 있습니다. "
    "오전 중 흐리다가 낮부터 비가 내리겠고, 강수확률은 70퍼센트입니다. "
    "외출하실 때 우산 꼭 챙기시기 바랍니다. "
    "낮 최고기온은 11도에 머물겠습니다. "
    "따뜻하게 입으시고, 오늘 하루도 행복하게 보내세요. "
    "지금까지 기상캐스터 김하늘이었습니다."
)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True, help="5단계 립싱크 영상")
    ap.add_argument("--bgm", help="배경음악 mp3 (선택)")
    ap.add_argument("--script", help="대본 txt (없으면 예시)")
    args = ap.parse_args()

    script = Path(args.script).read_text(encoding="utf-8") if args.script else SAMPLE_SCRIPT
    stamp = SAMPLE_WEATHER["date"].strftime("%Y%m%d")
    compose(Path(args.video), SAMPLE_WEATHER, script,
            WORK_DIR / f"weather_{stamp}_final.mp4",
            Path(args.bgm) if args.bgm else None)


# ---------------------------------------------------------------
# 시그널 + 배경음악 최종 믹스
# ---------------------------------------------------------------
# 시그널: 매일 영상 맨 앞에 자동으로 붙음.
#   JINGLE=off            → 시그널 없이 바로 인사
#   JINGLE=assets/xx.wav  → 다른 시그널 파일로 교체
#   JINGLE_INTRO=2.2      → 시그널이 울린 뒤 인사 시작까지(초)
_j = os.getenv("JINGLE", "assets/jingle.wav").strip()
JINGLE = None if _j.lower() in ("off", "none", "0", "") or not Path(_j).exists() else Path(_j)
INTRO_SEC = float(os.getenv("JINGLE_INTRO", "1.85")) if JINGLE else 0.0
JINGLE_DUCK = 0.28          # 말이 시작되면 시그널 여운을 줄이는 정도
BGM_AFTER_INTRO = 0.09      # 인사 이후 배경음악 크기


def finalize_audio(video: Path, out: Path, jingle: Path | None = JINGLE, bgm: Path | None = None,
                   intro: float = INTRO_SEC) -> Path:
    """목소리(영상 오디오) + 시그널(인사 시작 시 자동으로 작아짐) + 배경음악(인사 후부터)"""
    inputs = ["-i", str(video)]
    fc, mix, n_in = ["[0:a]aresample=44100[vo]"], ["[vo]"], 1
    if jingle and Path(jingle).exists():
        inputs += ["-i", str(jingle)]
        fc.append(f"[{n_in}:a]aresample=44100,volume='if(lt(t,{intro}),1.0,"
                  f"max({JINGLE_DUCK},1-(t-{intro})*1.4))':eval=frame[jg]")
        mix.append("[jg]"); n_in += 1
    if bgm and Path(bgm).exists():
        inputs += ["-stream_loop", "-1", "-i", str(bgm)]
        ms = int((intro + 0.35) * 1000)
        fc.append(f"[{n_in}:a]aresample=44100,volume={BGM_AFTER_INTRO},afade=t=in:st=0:d=0.8,"
                  f"adelay={ms}|{ms}[bg]")
        mix.append("[bg]"); n_in += 1
    fc.append(f"{''.join(mix)}amix=inputs={len(mix)}:duration=first:normalize=0,alimiter=limit=0.95[a]")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(fc),
                    "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-movflags", "+faststart", str(out)], check=True)
    print("[음악] 시그널·배경음악 믹스 완료:", out)
    return out


def prepend_intro(video: Path, out: Path, intro: float = INTRO_SEC) -> Path:
    """(api 엔진용) 첫 화면을 intro초 동안 멈춰 두고 음성을 그만큼 늦춤"""
    ms = int(intro * 1000)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-vf",
                    f"tpad=start_mode=clone:start_duration={intro}", "-af", f"adelay={ms}|{ms}",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac", str(out)], check=True)
    return out
