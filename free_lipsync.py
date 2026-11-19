"""
무료 엔진 ② 말하는 캐스터 영상 (오프라인 립싱크, API 비용 없음)
- assets/caster_hi.png : 캐릭터 시트 전신 컷을 4배 업스케일(EDSR) + 배경 제거한 고해상도 이미지
- 아래 얼굴 좌표(입·눈·턱)는 이 이미지 기준. 캐릭터 이미지를 바꾸면 좌표를 다시 측정해야 함
- 입: 음량(벌림) + 음색(오·우 둥글게 / 이·에 넓게), 영상이 음성보다 1프레임 먼저
- 머리·몸: 강세 끄덕임, 문장별 기울기, 흔들림, 호흡 / 눈: 문장 사이 + 무작위 깜빡임
"""
import math
import subprocess
import wave
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

import caster_compose as cc

W, H, FPS = 1080, 1920, 30
STYLE = "anchor"            # "anchor" 고개 반듯·정면 시선(기본) / "lively" 숏폼(고개 움직임 큼) / "calm" 차분한 뉴스
CASTER = Path("assets/caster_hi.png")
SCALE, TOP_Y = 0.5, 250

# ---------------- 얼굴 좌표 (caster_hi.png 기준 px) ----------------
FACE_OX = 272
MOUTH_CX, MOUTH_HW = FACE_OX + 252, 54          # 입 중심 x, 입 반폭
JAW_HW, CHIN_Y, NECK_Y = 125, 545, 610          # 턱 반폭, 턱끝, 변형 끝


def lip_line(x):                                 # 윗니 아래선(입이 벌어지는 선)
    return 451 + (x - MOUTH_CX) * 0.12


EYES = [(FACE_OX + 210, 283, 30, 15), (FACE_OX + 347, 302, 37, 13)]   # cx, cy, 반폭, 반높이
PATCH = (FACE_OX + 92, 220, FACE_OX + 456, 640)  # 매 프레임 다시 그리는 얼굴 영역 (4의 배수)

# 지도 위 도시 표시 위치 (화면 px) — weather.fetch_cities() 의 도시명과 일치
CITY_POS = {"광주": (870, 470), "목포": (150, 760), "순천": (930, 700), "여수": (880, 925), "완도": (190, 1000)}


def animate_face(src: np.ndarray, open_amt: float, round_amt: float, blink: float) -> np.ndarray:
    x0, y0, x1, y1 = PATCH
    p = src[y0:y1, x0:x1].astype(np.float32)
    h, w = p.shape[:2]
    out = p.copy()
    if open_amt > 0.02:
        D = 30 * open_amt                                    # 최대 턱 내림(px)
        xs = np.arange(w) + x0
        ys = np.arange(h) + y0
        X, Y = np.meshgrid(xs, ys)
        u = (X - MOUTH_CX) / JAW_HW
        wx = np.clip(1 - u ** 2, 0, 1) ** 1.2
        Lx = lip_line(X)
        dd = D * wx
        # 입선 아래를 매끄럽게 늘려 턱을 내림 (틈 없이 연속 변형)
        R = dd + 14
        ramp = np.clip((Y - Lx) / R, 0, 1)
        ramp = ramp * ramp * (3 - 2 * ramp)
        fade = np.where(Y <= CHIN_Y, 1.0, np.clip(1 - (Y - CHIN_Y) / (NECK_Y - CHIN_Y), 0, 1))
        shift = np.where(Y >= Lx, dd * ramp, 0.0)
        shift = np.where(Y > Lx + R, dd * fade, shift)
        srcY = Y - shift
        out = cv2.remap(p, (X - x0).astype(np.float32), (srcY - y0).astype(np.float32),
                        cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)

        # 입 안쪽: 양 끝이 뾰족하게 모이는 렌즈 모양
        hw = MOUTH_HW * (1 - 0.25 * round_amt)
        um = (X - MOUTH_CX) / hw
        lens = np.clip(1 - um ** 2, 0, 1) ** 0.75
        gap = dd * lens * 0.9
        t = (Y - Lx) / np.maximum(gap, 0.5)
        inside = np.clip(np.minimum(t * 4, (1 - t) * 3), 0, 1) * (gap > 0.6)
        mask = cv2.GaussianBlur(inside.astype(np.float32), (0, 0), 1.3)
        tc = np.clip(t, 0, 1)
        col = np.stack([95 - 50 * tc, 38 - 20 * tc, 45 - 20 * tc], -1)    # 위는 그늘, 아래로 어둡게
        tongue = np.clip((tc - 0.6) / 0.4, 0, 1)[..., None] * min(1, open_amt * 1.4)
        col = col * (1 - tongue * 0.5) + np.array([160, 75, 85]) * tongue * 0.5
        a = mask[..., None]
        out[..., :3] = out[..., :3] * (1 - a) + col * a

    if blink > 0.02:
        for cx, cy, ex, ey in EYES:
            bx0, bx1 = int(cx - ex - 8 - x0), int(cx + ex + 8 - x0)
            by0, by1 = int(cy - ey - 22 - y0), int(cy + ey + 6 - y0)
            region = out[by0:by1, bx0:bx1].copy()
            rh, rw = region.shape[:2]
            yy, xx = np.mgrid[0:rh, 0:rw].astype(np.float32)
            gx = xx + bx0 + x0; gy = yy + by0 + y0
            ux = np.clip(1 - ((gx - cx) / (ex + 3)) ** 2, 0, 1)
            sq = np.sqrt(ux)
            arc_top = cy - ey * sq
            z0 = arc_top - 7                                   # 원래 속눈썹 위부터 덮기
            lid_y = z0 + (7 + blink * 2 * ey * 0.95) * sq
            src_a, src_b = arc_top - 18, arc_top - 9           # 눈꺼풀 피부 띠
            k = np.clip((gy - (src_a)) / np.maximum(lid_y - src_a, 1), 0, 1)
            sy = src_a + k * (src_b - src_a)
            warped = cv2.remap(region, xx, (sy - by0 - y0).astype(np.float32), cv2.INTER_LINEAR,
                               borderMode=cv2.BORDER_REPLICATE)
            vin = np.clip((gy - (z0 - 3)) / 3, 0, 1) * np.clip((lid_y + 1.5 - gy) / 2, 0, 1)
            wgt = (vin * np.clip(ux * 3, 0, 1))[..., None] * min(1, blink * 2.5)
            region = region * (1 - wgt) + warped * wgt
            line = np.exp(-((gy - lid_y) / 1.6) ** 2) * np.clip(ux * 2.5, 0, 1) * min(1, blink * 1.6)
            region[..., :3] = region[..., :3] * (1 - 0.7 * line[..., None]) + np.array([45, 30, 32]) * 0.7 * line[..., None]
            out[by0:by1, bx0:bx1] = region
    return np.clip(out, 0, 255).astype(np.uint8)


def _studio_base(cities, icon) -> Image.Image:
    im = Image.new("RGB", (W, H))
    top, bot = np.array([196, 214, 244]), np.array([236, 241, 250])
    g = np.linspace(0, 1, H)[:, None]
    arr = (top * (1 - g) + bot * g).astype(np.uint8)
    im = Image.fromarray(np.repeat(arr[:, None, :], W, axis=1).reshape(H, W, 3))
    d = ImageDraw.Draw(im, "RGBA")
    # 대형 스크린
    d.rounded_rectangle((40, 380, 1040, 1150), 30, fill=(46, 92, 170, 255))
    sky = Image.new("RGBA", (1000, 770))
    sa = np.linspace(0, 1, 770)[:, None]
    c1, c2 = np.array([92, 150, 225, 255]), np.array([170, 205, 245, 255])
    sky = Image.fromarray(np.repeat(((c1 * (1 - sa) + c2 * sa).astype(np.uint8))[:, None, :], 1000, 1))
    mask = Image.new("L", (1000, 770), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, 999, 769), 30, fill=255)
    im.paste(sky.convert("RGB"), (40, 380), mask)
    # 육지 느낌의 부드러운 덩어리 (추상화된 전남 지형)
    land = Image.new("L", (W, H), 0)
    ld = ImageDraw.Draw(land)
    for (x, y, r) in [(420, 600, 230), (650, 640, 220), (260, 800, 180), (820, 760, 170),
                      (520, 860, 220), (300, 1000, 120), (700, 960, 160)]:
        ld.ellipse((x - r, y - r, x + r, y + r), fill=255)
    land = land.filter(ImageFilter.GaussianBlur(25)).point(lambda v: 255 if v > 128 else 0)
    land = land.filter(ImageFilter.GaussianBlur(3))
    clip = Image.new("L", (W, H), 0)
    ImageDraw.Draw(clip).rounded_rectangle((40, 380, 1040, 1150), 30, fill=255)
    land = Image.fromarray(np.minimum(np.array(land), np.array(clip)))
    im.paste((128, 190, 130), (0, 0), land)
    # 도시 라벨 + 아이콘
    f_city, f_t = cc.font("bold", 34), cc.font("bold", 44)
    for name, t, x, y in cities:
        im.paste(icon, (x - 45, y - 100), icon)
        d.rounded_rectangle((x - 75, y - 10, x + 75, y + 90), 18, fill=(255, 255, 255, 215))
        d.text((x, y + 18), name, font=f_city, fill=(40, 60, 110), anchor="mm")
        d.text((x, y + 62), f"{t}°", font=f_t, fill=(230, 110, 30), anchor="mm")
    # 스튜디오 바닥 + 조명
    d.rectangle((0, 1150, W, H), fill=(222, 230, 244, 255))
    for x in range(-200, W + 200, 180):
        d.polygon([(x, 1150), (x + 60, 1150), (x - 120, H), (x - 240, H)], fill=(255, 255, 255, 40))
    return im.filter(ImageFilter.GaussianBlur(2.2))


def animate_mouth(src: np.ndarray, jaw: float, width: float, close: float, blink: float,
                  teeth_amt: float = 0.0, tongue_amt: float = 0.0, press: float = 0.0) -> np.ndarray:
    """발음 입 모양: jaw(벌림) · width(-1 동그랗게 ~ +1 옆으로) · close(입술 붙임)
    teeth_amt(ㅅㅈㅊ 치아 맞물림) · tongue_amt(ㄴㄷㄹ 혀끝) · press(ㅁㅂㅍ 입술 압착)"""
    width = float(np.clip(width + 0.15 * press, -1, 1))
    x0, y0, x1, y1 = PATCH
    p = src[y0:y1, x0:x1].astype(np.float32)
    h, w = p.shape[:2]
    X, Y = np.meshgrid(np.arange(w, dtype=np.float32) + x0, np.arange(h, dtype=np.float32) + y0)
    Lx = lip_line(X)
    srcX, srcY = X.copy(), Y.copy()
    # 1) 입술 너비: 동그랗게(좁게) / 옆으로(넓게)
    if abs(width) > 0.02:
        sx = 1 + 0.08 * width if width > 0 else 1 + 0.18 * width
        wh = np.exp(-((X - MOUTH_CX) / (1.8 * MOUTH_HW)) ** 4) * np.exp(-((Y - (Lx + 2)) / 42) ** 4)
        srcX = X - (X - MOUTH_CX) * (1 - 1 / sx) * wh
    # 2) 턱 내림: 입 안쪽(렌즈 모양 틈)만큼 아랫입술이 통째로 내려가고, 턱까지 부드럽게 이어짐
    D = 25 * jaw
    u = (X - MOUTH_CX) / JAW_HW
    wx = np.clip(1 - u ** 2, 0, 1) ** 1.2
    dd = D * wx
    hw_in = MOUTH_HW * (1 - 0.3 * max(0.0, -width) + 0.07 * max(0.0, width))
    um_in = (X - MOUTH_CX) / hw_in
    lens = np.clip(1 - um_in ** 2, 0, 1) ** (0.75 if width > -0.3 else 0.55)
    g = dd * lens * 0.9                                   # 입 안쪽 틈 높이
    if jaw > 0.02:
        v = Y - Lx
        gs = cv2.GaussianBlur(g.astype(np.float32), (0, 0), sigmaX=7, sigmaY=0.1)   # 턱 이동용으로만 경계를 부드럽게
        r = np.clip((v - gs) / 40, 0, 1); r = r * r * (3 - 2 * r)
        shift = gs + (dd - gs) * r
        fade = np.where(Y <= CHIN_Y, 1.0, np.clip(1 - (Y - CHIN_Y) / (NECK_Y - CHIN_Y), 0, 1))
        shift = np.where(Y > CHIN_Y, dd * fade, shift)
        lens_s = cv2.GaussianBlur(np.clip(lens * 3, 0, 1).astype(np.float32), (0, 0), sigmaX=5, sigmaY=0.1)
        skip = 5.0 * lens_s * (1 - r)                     # 치아 끝 줄은 건너뜀 (입술 근처에서만)
        srcY = np.where(v >= 0, np.maximum(Y - shift + skip, Lx + skip), Y)
    # 2b) 크게 벌리는 모음(ㅏ·ㅐ)에서 윗입술이 살짝 들림
    lift = float(np.clip((jaw - 0.45) / 0.55, 0, 1)) * (1.0 if width > -0.3 else 0.4)
    if lift > 0.02:
        um_l = (X - MOUTH_CX) / (MOUTH_HW * 1.1)
        wl = np.clip(1 - um_l ** 2, 0, 1) ** 0.7
        wv = np.exp(-((Y - (Lx - 10)) / 14) ** 2)
        srcY = srcY + 2.5 * lift * wl * wv * (Y < Lx)
    # 2c) 동그란 모음(ㅗ·ㅜ)에서 입술이 앞으로 모이며 두꺼워짐
    if width < -0.1:
        r = min(1.0, -width)
        um_p = (X - MOUTH_CX) / (MOUTH_HW * 1.3)
        wp = np.exp(-1.6 * um_p ** 2) * np.exp(-((Y - Lx) / 30) ** 2)
        srcY = Lx + (srcY - Lx) / (1 + 0.08 * r * wp)
    # 3) 입술 닫힘: 윗입술을 아래로 늘려 치아를 덮고, 아랫입술을 살짝 올림
    if close > 0.02:
        um = (X - MOUTH_CX) / (MOUTH_HW * 1.05)
        lw = np.clip(1 - um ** 2, 0, 1) ** 0.6
        ul_top = Lx - 29
        k = 1 - (0.44 + 0.06 * press) * close * lw
        band = (Y >= ul_top) & (Y <= Lx + 3)
        srcY = np.where(band, ul_top + (Y - ul_top) * k, srcY)
        low = (Y > Lx + 3) & (Y < Lx + 16)
        srcY = np.where(low, Y + 3 * close * lw * np.clip((Lx + 16 - Y) / 13, 0, 1), srcY)
    out = cv2.remap(p, (srcX - x0).astype(np.float32), (srcY - y0).astype(np.float32), cv2.INTER_LINEAR,
                    borderMode=cv2.BORDER_REPLICATE)
    if close > 0.02:                                     # 입술이 맞닿는 선
        um = (X - MOUTH_CX) / (MOUTH_HW * 1.0)
        lw = np.clip(1 - um ** 2, 0, 1) ** 0.8
        seam = np.exp(-((Y - (Lx + 2)) / (1.4 + 0.4 * press)) ** 2) * lw * close
        a = 0.45 + 0.2 * press
        out[..., :3] = out[..., :3] * (1 - a * seam[..., None]) + np.array([140, 62, 72]) * a * seam[..., None]
    # 4) 입 안쪽 (틈 g 영역)
    if jaw > 0.04:
        t = (Y - Lx) / np.maximum(g, 0.5)
        inside = ((t >= 0) & (t <= 1) & (g > 0.6)).astype(np.float32)
        mask = cv2.GaussianBlur(inside.astype(np.float32), (0, 0), 1.3)
        tc = np.clip(t, 0, 1)
        col = np.stack([95 - 50 * tc, 38 - 20 * tc, 45 - 20 * tc], -1)
        tongue = np.clip((tc - 0.6) / 0.4, 0, 1)[..., None] * min(1.0, jaw * 1.4)
        col = col * (1 - tongue * 0.5) + np.array([160, 75, 85]) * tongue * 0.5
        teeth = (np.clip((0.2 - tc) / 0.08, 0, 1) * (g > 5) * np.clip(lens * 2, 0, 1))[..., None] * min(1.0, jaw * 1.6) * 0.8
        col = col * (1 - teeth) + np.array([228, 222, 218]) * teeth
        lowt = (np.clip((tc - 0.8) / 0.1, 0, 1) * np.clip(lens * 2, 0, 1))[..., None] * float(np.clip((jaw - 0.5) * 2.2, 0, 0.75))
        col = col * (1 - lowt) + np.array([214, 206, 202]) * lowt          # 아랫니
        if teeth_amt > 0.02:                                                 # ㅅㅈㅊ: 위아래 이가 거의 맞물림
            tz = float(teeth_amt) * 0.85
            line = np.exp(-((tc - 0.5) / 0.12) ** 2)[..., None]
            tcol = np.array([226, 220, 215]) * (1 - 0.6 * line) + np.array([90, 40, 48]) * 0.6 * line
            col = col * (1 - tz) + tcol * tz
        if tongue_amt > 0.02:                                                # ㄴㄷㄹ: 혀끝이 윗니 뒤에
            um_t = (X - MOUTH_CX) / (hw_in * 0.55)
            tw = (np.clip(1 - um_t ** 2, 0, 1) * np.clip((0.55 - tc) / 0.25, 0, 1) * (g > 3))[..., None] * float(tongue_amt) * 0.8
            col = col * (1 - tw) + np.array([196, 98, 108]) * tw
        out[..., :3] = out[..., :3] * (1 - mask[..., None]) + col * mask[..., None]
    patched = src.copy()
    patched[y0:y1, x0:x1] = np.clip(out, 0, 255).astype(np.uint8)
    return animate_face(patched, 0.0, 0.0, blink)       # 눈 깜빡임은 기존 처리 재사용


# ---------------- 스튜디오 배경 ----------------
def studio_bg(w: dict) -> Image.Image:
    cities = [(name, t, *CITY_POS[name]) for name, t in w.get("cities", {}).items() if name in CITY_POS]
    icon = cc.weather_icon(w["sky"], w["pty"], 90)
    bg = _studio_base(cities, icon)
    d = ImageDraw.Draw(bg)
    import re
    label = re.sub(r"\s*\(.*?\)", "", w.get("map_label", "오전 8시 기온"))
    f = cc.font("bold", 30)
    tw = f.getlength(label)
    d.rounded_rectangle((60, 398, 60 + tw + 60, 448), 25, fill=(38, 62, 120))
    d.text((60 + (tw + 60) / 2, 423), label, font=f, fill=(255, 255, 255), anchor="mm")
    return bg


# ---------------- 음성 분석 ----------------
def analyse(voice: Path, n: int):
    with wave.open(str(voice)) as wv:
        sr = wv.getframerate()
        x = np.frombuffer(wv.readframes(wv.getnframes()), np.int16).astype(np.float32) / 32768
    hop = sr // FPS; nfft = hop * 2
    win = np.hanning(nfft); freqs = np.fft.rfftfreq(nfft, 1 / sr)
    band = (freqs > 200) & (freqs < 4000)
    rms, cen, low = np.zeros(n), np.zeros(n), np.zeros(n)
    for i in range(n):
        seg = x[i * hop: i * hop + nfft]
        if len(seg) < nfft:
            seg = np.pad(seg, (0, nfft - len(seg)))
        rms[i] = np.sqrt(np.mean(seg ** 2))
        sp = np.abs(np.fft.rfft(seg * win)) + 1e-9
        cen[i] = (sp[band] * freqs[band]).sum() / sp[band].sum()
        low[i] = sp[(freqs > 250) & (freqs < 900)].sum() / sp[band].sum()
    speech = rms > 0.012
    ref = np.percentile(rms[speech], 92) if speech.any() else 1
    o = np.clip((rms - 0.012) / (ref - 0.012), 0, 1.15) ** 0.75
    sm = np.zeros(n); v = 0.0
    for i in range(n):
        v += (o[i] - v) * (0.8 if o[i] > v else 0.62)
        sm[i] = v
    sm = np.clip(np.roll(sm, -1), 0, 1)
    if speech.any():
        cz = (cen - np.median(cen[speech])) / (np.std(cen[speech]) + 1e-9)
        lz = (low - np.median(low[speech])) / (np.std(low[speech]) + 1e-9)
    else:
        cz = lz = np.zeros(n)
    shape = np.clip(0.45 * lz - 0.35 * cz, -0.6, 1.0) * (sm > 0.08)
    return sm, np.convolve(shape, np.ones(3) / 3, "same")


def head_motion(env, timing, n):
    rng = np.random.default_rng(11)
    t = np.arange(n) / FPS
    slow = np.convolve(env, np.ones(9) / 9, "same")
    accent = np.clip(env - slow, 0, None)
    nod = -np.convolve(accent, np.hanning(9) / np.hanning(9).sum(), "same") * 26
    starts = {int(s * FPS) for s, _ in timing}
    tilt = np.zeros(n); target = 0.0
    for i in range(n):
        if i in starts:
            target = rng.uniform(-1.1, 1.1)
        prev = tilt[i - 1] if i else 0.0
        tilt[i] = prev + (target - prev) * 0.04
    tilt += 0.25 * np.sin(2 * np.pi * t / 7.3)
    sway = 3.5 * np.sin(2 * np.pi * t / 6.1) + 1.5 * np.sin(2 * np.pi * t / 2.9 + 1)
    breath = 1 + 0.004 * np.sin(2 * np.pi * t / 3.9)
    return nod, tilt, sway, breath


def blinks(timing, n):
    b = np.zeros(n); rng = np.random.default_rng(5)
    shape = [0.5, 1.0, 1.0, 0.6, 0.2]
    times = [int((e + 0.12) * FPS) for _, e in timing[:-1]]
    t = int(2.0 * FPS)
    while t < n:
        times.append(t); t += int(rng.uniform(3.0, 5.5) * FPS)
    last = -99
    for s in sorted(times):
        if s - last < int(1.4 * FPS) or s + len(shape) >= n:
            continue
        for k, v in enumerate(shape):
            b[s + k] = max(b[s + k], v)
        last = s
    return b


# ---------------- 카메라 워크 (방송식 샷 구성) ----------------
VS = 1.5                                   # 가상 캔버스 배율: 줌인해도 선명하도록 크게 그린 뒤 잘라냄
VW, VH = int(W * VS), int(H * VS)
CSC = SCALE * VS                           # 가상 캔버스에서 캐스터 배율
VTOP = TOP_Y * VS
TIP_WORDS = ("챙기", "조심", "유의하", "주의하", "보내세요", "대비하", "출발하세요", "응원", "고생")


def _ease(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def plan_shots(sentences, timing, has_cities: bool):
    """문장 내용으로 샷 배치: wide / medium / close / map"""
    n = len(sentences)
    shots = ["medium"] * n
    shots[0] = "wide"
    shots[-1] = "wide"
    map_i = None
    if has_cities and n >= 5:
        def score(s):
            return (("아침" in s) + ("최고" in s or "최저" in s) + ("내일" in s) + ("기온" in s)
                    + any(c.isdigit() for c in s))
        cand = [(score(sentences[i]), -i, i) for i in range(2, n - 1)]
        best = max(cand)
        if best[0] >= 3:
            map_i = best[2]
            shots[map_i] = "map"
    for i in range(1, n - 1):
        if i == map_i:
            continue
        s = sentences[i]
        if any(k in s for k in TIP_WORDS):
            shots[i] = "close"
        elif i == 1 or any(c.isdigit() for c in s):
            shots[i] = "medium"
        else:
            shots[i] = "wide"
        if shots[i] == shots[i - 1] and shots[i] != "close":     # 같은 샷 반복 피하기
            shots[i] = "wide" if shots[i] == "medium" else "medium"
    return shots


def _cam(kind):
    """샷 종류 → (줌, 중심x, 중심y) 가상 캔버스 좌표"""
    fw = 1090 * CSC
    face_x = (VW - fw) / 2 + 524 * CSC
    eye_y = VTOP + 290 * CSC
    if kind == "wide":
        return 1.0, VW / 2, VH / 2
    z, eye_out = {"medium": (1.3, 560), "close": (1.62, 600)}[kind]
    vh = VH / z
    top = eye_y - eye_out * vh / H
    cy = min(max(top + vh / 2, vh / 2), VH - vh / 2)
    vw = VW / z
    cx = min(max(face_x, vw / 2), VW - vw / 2)
    return z, cx, cy


def camera_track(shots, timing, n, sentences=None, style="anchor"):
    """프레임별 카메라 (모드, 줌, cx, cy).
    calm: 샷 사이 부드러운 줌 / lively: 컷과 줌을 번갈아 쓰고, 숫자·감탄 문장은 빠른 펀치인"""
    track = []
    starts = [s for s, _ in timing] + [n / FPS + 1]
    for f in range(n):
        t = f / FPS
        k = max(0, sum(1 for s in starts[:-1] if t >= s - 0.12) - 1)
        kind = shots[k]
        if kind == "map":
            p = (t - starts[k]) / max(0.1, starts[k + 1] - starts[k])
            track.append(("map", 1.0 + 0.06 * _ease(p), 0, 0, t - starts[k]))
            continue
        z1, x1, y1 = _cam(kind)
        prev = shots[k - 1] if k > 0 else kind
        cut = style in ("lively", "anchor") and k % 2 == 1 and k != len(shots) - 1
        if prev == "map" or k == 0 or cut:              # 컷 전환
            z0, x0, y0 = z1, x1, y1
        else:
            z0, x0, y0 = _cam(prev)
        dur = 1.6 if k == len(shots) - 1 else (0.7 if style in ("lively", "anchor") else 1.0)
        e = _ease((t - (starts[k] - 0.12)) / dur)
        z = z0 + (z1 - z0) * e; cx = x0 + (x1 - x0) * e; cy = y0 + (y1 - y0) * e
        span = max(0.1, starts[k + 1] - starts[k])
        drift = _ease((t - starts[k]) / span)
        z *= 1 + (0.025 if kind != "wide" or k == 0 else 0.015) * drift
        sent = sentences[k] if sentences and k < len(sentences) else ""
        if style in ("lively", "anchor") and kind != "wide" and (any(c.isdigit() for c in sent) or "!" in sent):
            z *= 1 + 0.06 * _ease((t - starts[k] - 0.25) / 0.22)       # 펀치인
        track.append(("studio", z, cx, cy, 0))
    return track


def map_graphic(w: dict):
    """전체화면 지도 그래픽(방송 CG 컷). 반환: 바탕 이미지, 도시 카드 [(img, x, y)]"""
    im = Image.new("RGB", (W, H))
    g = np.linspace(0, 1, H)[:, None]
    top, bot = np.array([200, 216, 244]), np.array([232, 238, 250])
    im = Image.fromarray(np.repeat(((top * (1 - g) + bot * g).astype(np.uint8))[:, None, :], W, 1))
    d = ImageDraw.Draw(im, "RGBA")
    box = (50, 430, 1030, 1290)
    d.rounded_rectangle(box, 36, fill=(64, 118, 196, 255))
    land = Image.new("L", (W, H), 0)
    ld = ImageDraw.Draw(land)
    for (x, y, r) in [(420, 600, 230), (650, 640, 220), (260, 800, 180), (820, 760, 170),
                      (520, 860, 220), (300, 1000, 120), (700, 960, 160)]:
        y2 = 450 + (y - 380) * (1270 - 450) / (1150 - 380)
        ld.ellipse((x - r, y2 - r * 1.06, x + r, y2 + r * 1.06), fill=255)
    land = land.filter(ImageFilter.GaussianBlur(25)).point(lambda v: 255 if v > 128 else 0).filter(ImageFilter.GaussianBlur(2))
    clip = Image.new("L", (W, H), 0)
    ImageDraw.Draw(clip).rounded_rectangle(box, 36, fill=255)
    land = Image.fromarray(np.minimum(np.array(land), np.array(clip)))
    im.paste((112, 182, 118), (0, 0), land)
    f_t = cc.font("bold", 44)
    label = w.get("map_label", "오전 8시 기온")
    tw = f_t.getlength(label)
    d.rounded_rectangle((W / 2 - tw / 2 - 40, 350, W / 2 + tw / 2 + 40, 414), 32, fill=(38, 62, 120, 250))
    d.text((W / 2, 382), label, font=f_t, fill=(255, 255, 255), anchor="mm")
    icon = cc.weather_icon(w["sky"], w["pty"], 120)
    f_c, f_v = cc.font("bold", 40), cc.font("bold", 72)
    cards = []
    for name, temp in w.get("cities", {}).items():
        if name not in CITY_POS:
            continue
        x, y = CITY_POS[name]
        y = 450 + (y - 380) * (1270 - 450) / (1150 - 380)
        x = min(max(x, 160), 900)
        card = Image.new("RGBA", (230, 270), (0, 0, 0, 0))
        cd = ImageDraw.Draw(card)
        cd.rounded_rectangle((10, 60, 220, 262), 28, fill=(255, 255, 255, 235))
        card.alpha_composite(icon, (55, 0))
        cd.text((115, 150), name, font=f_c, fill=(38, 62, 120), anchor="mm")
        cd.text((115, 215), f"{temp}°", font=f_v, fill=(232, 108, 28), anchor="mm")
        cards.append((card, int(x - 115), int(y - 150)))
    return im, cards


def _map_frame(base, cards, z, t):
    fr = base.copy()
    for i, (card, x, y) in enumerate(cards):
        a = _ease((t - 0.15 - 0.22 * i) / 0.35)
        if a <= 0:
            continue
        sc = 0.7 + 0.3 * a + 0.06 * math.sin(math.pi * a)
        c = card.resize((max(1, int(card.width * sc)), max(1, int(card.height * sc))), Image.BILINEAR)
        alpha = c.split()[-1].point(lambda v, a=a: int(v * a))
        c.putalpha(alpha)
        fr.paste(c, (x + (card.width - c.width) // 2, y + (card.height - c.height) // 2), c)
    zw, zh = int(W / z), int(H / z)
    fx, fy = (W - zw) // 2, int((H - zh) * 0.4)
    return fr.crop((fx, fy, fx + zw, fy + zh)).resize((W, H), Image.BILINEAR)


# ---------------- 렌더링 ----------------
def render_talk(voice: Path, timing, w: dict, out: Path, caster: Path = CASTER,
                sentences: list[str] | None = None) -> Path:
    with wave.open(str(voice)) as wv:
        dur = wv.getnframes() / wv.getframerate()
    n = int(dur * FPS) + 1
    hi = np.array(Image.open(caster).convert("RGBA"))
    rgb, alpha = hi[..., :3].copy(), hi[..., 3]
    fw, fh = int(hi.shape[1] * CSC), int(hi.shape[0] * CSC)
    base = Image.fromarray(hi).resize((fw, fh), Image.LANCZOS)
    px0, py0, px1, py1 = PATCH
    psz = (int((px1 - px0) * CSC), int((py1 - py0) * CSC))
    pa = Image.fromarray(alpha[py0:py1, px0:px1]).resize(psz, Image.LANCZOS)
    op, shp = analyse(voice, n)
    nod, tilt, sway, breath = head_motion(op, timing, n)
    bl = blinks(timing, n)
    vis = None
    if sentences:
        try:
            from free_viseme import build_visemes
            vis = build_visemes(voice, sentences, timing, n, op)
            print("[입모양] 발음 기반 립싱크 사용")
        except Exception as e:
            print("[입모양] 발음 분석 실패, 음량 기반으로 대체:", e)
    bgv = studio_bg(w).resize((VW, VH), Image.LANCZOS)
    shots = plan_shots(sentences or [""] * len(timing), timing, bool(w.get("cities")))
    print("[카메라] 샷 구성:", " → ".join(shots))
    track = camera_track(shots, timing, n, sentences, STYLE)
    mbase, mcards = map_graphic(w)
    from free_pose import pose_track, warp_body
    POSE_PAD = 40
    poses = pose_track(n, timing, op, shots, style=STYLE)  # 전신 동작(체중이동·호흡·고개·손·목례)
    print("[동작] 전신 자연 동작 적용")
    shadow = Image.new("RGBA", (fw + 330, 190), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).ellipse((60, 30, fw + 270, 165), fill=(0, 0, 0, 55))
    shadow = shadow.filter(ImageFilter.GaussianBlur(30))
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                           "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-i", str(voice),
                           "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p",
                           "-c:a", "aac", "-b:a", "192k", "-shortest", str(out)], stdin=subprocess.PIPE)
    for i in range(n):
        mode, z, cx, cy, mt = track[i]
        if mode == "map":
            frame = _map_frame(mbase, mcards, z, mt)
            ff.stdin.write(frame.tobytes())
            continue
        if vis is not None:
            face = animate_mouth(rgb, vis[0][i], vis[1][i], vis[2][i], bl[i], vis[3][i], vis[4][i], vis[5][i])
        else:
            o = op[i] * (1 - 0.25 * max(0, -shp[i]))
            face = animate_face(rgb, o, shp[i], bl[i])
        fp = Image.fromarray(face).resize(psz, Image.LANCZOS).convert("RGBA"); fp.putalpha(pa)
        cast = base.copy(); cast.paste(fp, (int(px0 * CSC), int(py0 * CSC)))
        arr = np.pad(np.asarray(cast), ((POSE_PAD, POSE_PAD), (POSE_PAD, POSE_PAD), (0, 0)))
        c = Image.fromarray(warp_body(arr, poses[i], CSC, POSE_PAD))
        frame = bgv.copy()
        frame.paste(shadow, ((VW - shadow.width) // 2, int(VTOP + fh - 120)), shadow)
        frame.paste(c, ((VW - c.width) // 2, int(VTOP) - POSE_PAD), c)
        vw, vh = VW / z, VH / z
        x0 = int(round(cx - vw / 2)); y0 = int(round(cy - vh / 2))
        crop = np.asarray(frame)[y0:y0 + int(vh), x0:x0 + int(vw)]
        frame = cv2.resize(crop, (W, H), interpolation=cv2.INTER_AREA if z < VS else cv2.INTER_LINEAR)
        ff.stdin.write(np.ascontiguousarray(frame).tobytes())
        if i % 300 == 0:
            print(f"  [립싱크] {i}/{n} 프레임", flush=True)
    ff.stdin.close(); ff.wait()
    print(f"[립싱크] {out} {dur:.1f}초")
    return out
