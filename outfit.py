"""
의상 변환 (OpenAI 이미지 편집 API) — 무료 립싱크 엔진과 함께 쓰는 하이브리드 방식
- 머리·얼굴은 원본 그대로 두고 목 아래 옷만 날씨에 맞게 바꿈
  → 입·눈 좌표가 그대로 유지되어 오프라인 립싱크를 계속 사용할 수 있음
- 필요: OPENAI_API_KEY (하루 1장, 이미지 편집 1회 비용만 발생)

흐름: caster_hi.png(머리~허벅지 영역) → 1024x1536 캔버스 → 옷 영역 마스크 편집
     → 원래 크기로 복원 → 머리는 원본으로 합성 → 배경 제거로 새 실루엣 alpha 생성
"""
import base64
import io
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from caster_image import pick_outfit

CASTER = Path("assets/caster_hi.png")
IMAGE_MODEL = os.getenv("IMAGE_MODEL", "gpt-image-1")
EDIT_BOTTOM = 3000          # 편집할 세로 범위(머리~허벅지 아래). 그 아래 다리·구두는 원본 유지
NECK_KEEP = 600             # 이 위(머리·얼굴)는 항상 원본
NECK_BLEND = 60             # 머리/옷 경계 부드럽게 섞는 높이
CANVAS = (1024, 1536)
BG = (222, 230, 242)


def _prepare(hi: Image.Image):
    """편집용 캔버스·마스크 생성. 반환: canvas, mask, 배치정보"""
    region = hi.crop((0, 0, hi.width, EDIT_BOTTOM))
    s = CANVAS[1] / region.height
    rw = int(region.width * s)
    small = region.resize((rw, CANVAS[1]), Image.LANCZOS)
    ox = (CANVAS[0] - rw) // 2
    canvas = Image.new("RGB", CANVAS, BG)
    canvas.paste(small, (ox, 0), small)
    # 마스크: 투명(alpha=0) = 편집 허용. 목 아래 사람 영역을 넉넉히 넓혀 허용
    a = np.array(small.split()[-1]) > 20
    person = Image.fromarray((a * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(41))
    edit = np.zeros((CANVAS[1], CANVAS[0]), np.uint8)
    edit[:, ox:ox + rw] = np.array(person)
    edit[: int((NECK_KEEP - 20) * s)] = 0                  # 머리는 편집 금지
    mask = Image.new("RGBA", CANVAS, (0, 0, 0, 255))
    m = np.array(mask); m[..., 3] = np.where(edit > 0, 0, 255); mask = Image.fromarray(m)
    return canvas, mask, (s, ox, rw)


def _prompt(w: dict) -> str:
    o = pick_outfit(w)
    return (
        "Photorealistic edit. Keep the woman's head, face, hair, earrings, pose, arm and hand position, "
        "body proportions and camera framing exactly the same. Change ONLY her clothing to: "
        f"{o['outfit'].split(', ')[0]}. {o['props'] or ''} "
        "A small black lapel microphone clipped near the collar. "
        "The outfit must end at mid-thigh so the legs below stay as they are. "
        "Plain light grey-blue studio background, soft even TV studio lighting, no text."
    )


def _restore(edited: Image.Image, hi: Image.Image, place) -> Image.Image:
    s, ox, rw = place
    body = edited.convert("RGB").crop((ox, 0, ox + rw, CANVAS[1])).resize((hi.width, EDIT_BOTTOM), Image.LANCZOS)
    orig = np.array(hi.convert("RGBA")).astype(np.float32)
    new = orig.copy()
    nb = np.array(body).astype(np.float32)
    # 머리(위)는 원본, 목 경계에서 부드럽게 전환, 아래 다리는 원본
    ys = np.arange(EDIT_BOTTOM)[:, None]
    wgt = np.clip((ys - NECK_KEEP) / NECK_BLEND, 0, 1)
    wgt = np.minimum(wgt, np.clip((EDIT_BOTTOM - 40 - ys) / 40, 0, 1))[..., None]
    bgfill = orig[:EDIT_BOTTOM, :, :3] * (orig[:EDIT_BOTTOM, :, 3:4] / 255) + np.array(BG) * (1 - orig[:EDIT_BOTTOM, :, 3:4] / 255)
    new[:EDIT_BOTTOM, :, :3] = bgfill * (1 - wgt) + nb * wgt
    rgb = Image.fromarray(np.clip(new[..., :3], 0, 255).astype(np.uint8))
    # 새 실루엣(코트 등으로 넓어진 몸) 배경 제거
    from rembg import new_session, remove
    half = rgb.resize((rgb.width // 2, rgb.height // 2))
    m = remove(half, session=new_session("u2net_human_seg"), only_mask=True, post_process_mask=True)
    alpha = np.array(m.resize(rgb.size, Image.LANCZOS)).astype(np.float32)
    head = np.clip((NECK_KEEP - np.arange(rgb.height)) / NECK_BLEND, 0, 1)[:, None]
    alpha = alpha * (1 - head) + orig[..., 3] * head        # 머리 윤곽은 원본 alpha
    out = rgb.convert("RGBA"); out.putalpha(Image.fromarray(np.clip(alpha, 0, 255).astype(np.uint8)))
    return out


def dress_caster(w: dict, out_path: Path, edit_fn=None) -> Path:
    """날씨에 맞는 옷으로 갈아입힌 caster 이미지 생성. edit_fn은 테스트용 대체 함수"""
    hi = Image.open(CASTER).convert("RGBA")
    canvas, mask, place = _prepare(hi)
    prompt = _prompt(w)
    print("[의상]", pick_outfit(w)["outfit"])
    if edit_fn:
        edited = edit_fn(canvas, mask, prompt)
    else:
        from openai import OpenAI
        cb, mb = io.BytesIO(), io.BytesIO()
        canvas.save(cb, "PNG"); mask.save(mb, "PNG")
        cb.name, mb.name = "caster.png", "mask.png"
        cb.seek(0); mb.seek(0)
        res = OpenAI().images.edit(model=IMAGE_MODEL, image=cb, mask=mb, prompt=prompt,
                                   size="1024x1536", quality="high", input_fidelity="high")
        edited = Image.open(io.BytesIO(base64.b64decode(res.data[0].b64_json)))
    out = _restore(edited, hi, place)
    out.save(out_path)
    print("[의상] 저장:", out_path)
    return out_path
