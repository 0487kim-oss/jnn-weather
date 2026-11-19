"""
4단계: 날씨에 맞춰 의상을 바꾼 기상캐스터(김하늘) 이미지 생성
- 입력: 캐릭터 시트 이미지 + 오늘 날씨(dict)
- 출력: 1080x1920 (9:16) PNG

설치:  pip install openai pillow
실행:  export OPENAI_API_KEY="sk-..."
       python caster_image.py --sheet character_sheet.png
"""
import argparse
import base64
import datetime as dt
from pathlib import Path

from PIL import Image
from openai import OpenAI

# ---------------------------------------------------------------
# 설정
# ---------------------------------------------------------------
IMAGE_MODEL = "gpt-image-1"     # 얼굴 참조 편집을 지원하는 OpenAI 이미지 모델
OUT_W, OUT_H = 1080, 1920       # 9:16 최종 크기
WORK_DIR = Path("output")
REF_DIR = WORK_DIR / "refs"

# 캐릭터 시트(1312x1199)에서 참조로 쓸 영역 (left, top, right, bottom)
CROPS = {
    "face": (367, 0, 803, 572),     # 얼굴 클로즈업
    "body": (0, 0, 360, 1199),      # 전신(체형·비율)
}

CASTER_DESC = (
    "the same Korean female TV weather caster shown in the reference images: "
    "short dark brown bob haircut with see-through bangs, clear bright eyes, "
    "gentle smile, small pearl drop earrings, slim build, height 168cm"
)


# ---------------------------------------------------------------
# 1) 캐릭터 시트에서 참조 이미지 잘라내기 (최초 1회)
# ---------------------------------------------------------------
def prepare_refs(sheet_path: str) -> list[Path]:
    REF_DIR.mkdir(parents=True, exist_ok=True)
    sheet = Image.open(sheet_path).convert("RGB")
    paths = []
    for name, box in CROPS.items():
        p = REF_DIR / f"ref_{name}.png"
        if not p.exists():
            sheet.crop(box).save(p)
        paths.append(p)
    return paths


# ---------------------------------------------------------------
# 2) 날씨 → 의상 규칙
# ---------------------------------------------------------------
def pick_outfit(w: dict) -> dict:
    t = w["temp"]
    if t >= 28:
        top = "sleeveless light linen A-line dress in pastel mint"
        shoes = "white low-heel sandals"
    elif t >= 20:
        top = "short-sleeve ivory chiffon blouse with a lavender pencil skirt"
        shoes = "nude pumps"
    elif t >= 12:
        top = "beige trench coat over a light knit top and knee-length skirt"
        shoes = "beige ankle boots"
    elif t >= 5:
        top = "camel wool coat over a cream turtleneck knit and midi skirt"
        shoes = "black ankle boots"
    else:
        top = "long white padded down coat, cream knit scarf, and wool gloves"
        shoes = "warm winter boots"

    props = []
    if w.get("pty") in ("비", "비/눈", "소나기"):
        props.append("holding a clear transparent umbrella")
        shoes = "glossy rain boots"
    elif w.get("pty") == "눈":
        props.append("light snowflakes on her coat, knitted beanie")
    if w.get("pm") in ("나쁨", "매우나쁨"):
        props.append("holding a white KF94 face mask in one hand")
    if w.get("sky") == "맑음" and t >= 25:
        props.append("sunglasses tucked into her outfit")

    bg = {
        "맑음": "bright clear blue sky",
        "구름많음": "partly cloudy sky",
        "흐림": "soft overcast grey sky",
    }.get(w.get("sky"), "sky")
    if w.get("pty") in ("비", "소나기", "비/눈"):
        bg = "rainy grey sky with raindrops"
    elif w.get("pty") == "눈":
        bg = "gently snowing winter sky"

    return {"outfit": f"{top}, {shoes}", "props": ", ".join(props), "bg": bg}


# ---------------------------------------------------------------
# 3) 프롬프트 생성
# ---------------------------------------------------------------
def build_prompt(w: dict, o: dict) -> str:
    return f"""
Create a photorealistic vertical broadcast image (portrait orientation).
Subject: {CASTER_DESC}.
Keep her face, hairstyle and body proportions IDENTICAL to the reference images.
Change ONLY the clothing.
Outfit: {o['outfit']}. {o['props']}
Pose: standing full body, centered, facing camera, one hand gesturing to the side
as if presenting the weather, small lapel microphone clipped on her outfit.
Background: TV weather studio with a large screen showing a map of
Gwangju and South Jeolla province (Korea) under a {o['bg']}.
Leave empty space at the top and bottom for captions.
Studio lighting, sharp focus, natural skin texture.
Do not include any text, letters, logos or watermarks.
Today: {w['temp']}°C, {w.get('sky','')}, {w.get('pty','없음')}.
""".strip()


# ---------------------------------------------------------------
# 4) 이미지 생성 (참조 이미지 2장 + 프롬프트)
# ---------------------------------------------------------------
def generate(prompt: str, refs: list[Path], out_path: Path) -> Path:
    client = OpenAI()
    files = [open(p, "rb") for p in refs]
    try:
        res = client.images.edit(
            model=IMAGE_MODEL,
            image=files,
            prompt=prompt,
            size="1024x1536",          # 지원 세로 비율(2:3) → 아래에서 9:16로 변환
            quality="high",
            input_fidelity="high",     # 얼굴 보존 강화
        )
    finally:
        for f in files:
            f.close()
    out_path.write_bytes(base64.b64decode(res.data[0].b64_json))
    return out_path


# ---------------------------------------------------------------
# 5) 2:3 → 9:16 (1080x1920) 변환
# ---------------------------------------------------------------
def to_916(src: Path, dst: Path) -> Path:
    im = Image.open(src).convert("RGB")
    w, h = im.size
    target_w = int(h * 9 / 16)             # 1536 → 864
    left = (w - target_w) // 2
    im = im.crop((left, 0, left + target_w, h))
    im.resize((OUT_W, OUT_H), Image.LANCZOS).save(dst)
    return dst


# ---------------------------------------------------------------
# 실행
# ---------------------------------------------------------------
def make_caster_image(sheet: str, weather: dict) -> Path:
    WORK_DIR.mkdir(exist_ok=True)
    refs = prepare_refs(sheet)
    outfit = pick_outfit(weather)
    prompt = build_prompt(weather, outfit)
    print("[의상]", outfit["outfit"], "|", outfit["props"] or "-")

    stamp = dt.date.today().strftime("%Y%m%d")
    raw = generate(prompt, refs, WORK_DIR / f"caster_{stamp}_raw.png")
    final = to_916(raw, WORK_DIR / f"caster_{stamp}_916.png")
    print("[완료]", final)
    return final


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", required=True, help="캐릭터 시트 이미지 경로")
    ap.add_argument("--dry-run", action="store_true", help="API 호출 없이 프롬프트만 출력")
    args = ap.parse_args()

    # 1단계 fetch_weather() 결과가 들어올 자리 (예시 값)
    today = {"temp": 6, "sky": "흐림", "pty": "비", "pm": "보통"}

    if args.dry_run:
        prepare_refs(args.sheet)
        print(build_prompt(today, pick_outfit(today)))
    else:
        make_caster_image(args.sheet, today)
