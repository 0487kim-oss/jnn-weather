"""
전신 자연 동작 — 정지 이미지를 관절(스켈레톤) + MLS 메시 변형으로 움직임
실제 기상캐스터의 동작을 단순화해 반영:
- 체중 이동: 6~10초마다 한쪽 다리로 천천히 무게 이동 (골반 옆 이동 + 지지 쪽 골반 올라감,
  상체는 반대로 살짝 기울어 균형, 발은 바닥에 고정)
- 호흡: 약 4초 주기로 어깨·가슴이 오르내림
- 고개: 문장마다 각도 변화, 강세에서 끄덕임
- 손(모은 손): 말의 박자에 맞춰 들렸다 내려옴(비트 제스처), 팔꿈치가 따라 움직임
- 인사/마무리: "안녕하세요", 마지막 인사에서 가볍게 목례
- 카메라 연동: 카메라가 다가가는 순간 고개·손 제스처, 마지막 줌아웃에 목례
좌표: assets/caster_hi.png 기준(px). 캐릭터 이미지를 바꾸면 다시 측정 필요
"""
import math

import cv2
import numpy as np

FPS = 30

# 관절(핸들) 원래 위치 (caster_hi.png 기준)
J = {
    "head_top": (520, 150), "head_mid": (525, 420), "head_l": (350, 330), "head_r": (700, 340),
    "chin": (530, 560), "neck": (520, 640),
    "sh_l": (200, 720), "sh_r": (870, 730), "chest": (520, 1000),
    "el_l": (140, 1380), "el_r": (950, 1400),
    "wr_l": (320, 1590), "wr_r": (690, 1580), "hands": (480, 1665),
    "waist": (520, 1450), "hip_l": (240, 1950), "hip_r": (850, 1950), "pelvis": (520, 2080),
    "kn_l": (420, 3020), "kn_r": (550, 3040),
    "ft_l": (420, 4400), "ft_r": (610, 4200),
}
NAMES = list(J)
P0 = np.array([J[k] for k in NAMES], np.float32)
NECK_PIVOT = np.array([520, 620], np.float32)
HEAD_STRAIGHTEN = -7.4      # 원본 이미지의 고개 기울기(약 7.4°)를 바로 세우는 보정각


def _ease(x):
    x = np.clip(x, 0, 1)
    return x * x * (3 - 2 * x)


def _bump(t, t0, dur):
    """t0에서 시작해 dur 동안 올라갔다 내려오는 부드러운 곡선(0~1~0)"""
    x = np.clip((t - t0) / dur, 0, 1)
    return np.sin(np.pi * x) ** 2


STYLES = {
    # calm: 차분한 뉴스 / lively: 숏폼 캐스터처럼 밝고 동작이 큼
    "calm":   dict(shift_iv=(6.0, 10.0), hip=14, tilt=2.6, nod=55, hand=18, hand_x=7, beat_gap=1.1, beat_pct=85, sway=3.0),
    "lively": dict(shift_iv=(4.0, 7.0), hip=18, tilt=4.0, nod=85, hand=26, hand_x=11, beat_gap=0.75, beat_pct=72, sway=5.0),
    # anchor: 몸·손은 생동감 있게, 고개는 반듯하게 세우고 시선은 카메라 정면 고정(기울임·흔들림 없음, 미세한 끄덕임만)
    "anchor": dict(shift_iv=(4.5, 7.5), hip=16, tilt=0.0, nod=8, hand=24, hand_x=10, beat_gap=0.8, beat_pct=75, sway=0.0,
                   bow=0.2, camnod=0.15, straighten=True),
}


def pose_track(n: int, timing, energy: np.ndarray, shots=None, seed=3, style="lively"):
    """프레임별 관절 이동량 (n, K, 2) — caster_hi 좌표 단위(px)"""
    S = STYLES[style]
    rng = np.random.default_rng(seed)
    t = np.arange(n) / FPS
    dur = n / FPS
    D = np.zeros((n, len(NAMES), 2), np.float32)
    idx = {k: i for i, k in enumerate(NAMES)}

    def add(name, dx, dy):
        D[:, idx[name], 0] += dx
        D[:, idx[name], 1] += dy

    # --- 체중 이동 (골반·무릎·상체) ---
    wshift = np.zeros(n); cur = 0.0; tk = 1.5; side = rng.choice([-1, 1])
    keys = [(0, 0.0)]
    while tk < dur:
        side = -side
        keys.append((tk, side * rng.uniform(0.6, 1.0)))
        tk += rng.uniform(*S['shift_iv'])
    for (ta, va), (tb, vb) in zip(keys, keys[1:] + [(dur + 10, keys[-1][1])]):
        m = (t >= ta) & (t < tb)
        wshift[m] = va
    # 부드러운 전환(1.8초)
    ws = np.zeros(n)
    for i in range(n):
        ws[i] = ws[i - 1] + (wshift[i] - ws[i - 1]) * (1 / (1.8 * FPS / 3)) if i else 0.0
    hip_x = S['hip'] * ws                       # 골반 옆 이동
    add("pelvis", hip_x, 0); add("waist", hip_x * 0.8, 0)
    add("hip_l", hip_x, -6 * np.clip(-ws, 0, 1) + 3 * np.clip(ws, 0, 1))   # 지지 쪽 골반 올라감
    add("hip_r", hip_x, -6 * np.clip(ws, 0, 1) + 3 * np.clip(-ws, 0, 1))
    add("kn_l", hip_x * 0.45 + 5 * np.clip(ws, 0, 1), 4 * np.clip(ws, 0, 1))   # 반대 무릎 살짝 굽힘
    add("kn_r", hip_x * 0.45 - 5 * np.clip(-ws, 0, 1), 4 * np.clip(-ws, 0, 1))
    torso_x = -0.35 * hip_x               # 상체는 반대로 살짝(균형)
    for k in ("chest", "sh_l", "sh_r", "neck", "head_top", "head_mid", "head_l", "head_r", "chin",
              "el_l", "el_r", "wr_l", "wr_r", "hands"):
        add(k, torso_x + hip_x * 0.25, 0)
    sh_tilt = 4 * ws                      # 체중 반대쪽 어깨가 살짝 내려감
    add("sh_l", 0, -sh_tilt); add("sh_r", 0, sh_tilt)

    # --- 호흡 ---
    br = np.sin(2 * np.pi * t / 4.1)
    for k, a in (("sh_l", 3.0), ("sh_r", 3.0), ("chest", 2.5), ("neck", 2.5), ("head_top", 2.5), ("head_mid", 2.5),
                 ("head_l", 2.5), ("head_r", 2.5), ("chin", 2.5)):
        add(k, 0, -a * br)

    # --- 고개: 문장별 기울기 + 강세 끄덕임 ---
    starts = [s for s, _ in timing]
    tilt = np.zeros(n); target = 0.0; j = 0
    for i in range(n):
        while j < len(starts) and t[i] >= starts[j]:
            target = rng.uniform(-S['tilt'], S['tilt']); j += 1
        tilt[i] = (tilt[i - 1] + (target - tilt[i - 1]) * 0.05) if i else 0.0
    slow = np.convolve(energy, np.ones(9) / 9, "same")
    accent = np.clip(energy - slow, 0, None)
    nod = np.convolve(accent, np.hanning(21) / np.hanning(21).sum(), "same") * S["nod"]   # px 아래로

    # --- 인사·마무리 목례 ---
    bow = np.zeros(n)
    if timing:
        bow += 1.0 * _bump(t, timing[0][0] + 0.15, 1.1)          # 인사
        bow += 1.4 * _bump(t, timing[-1][1] - 0.6, 1.8)          # 마무리
    bow = bow * S.get("bow", 1.0)
    head_dy = nod + 16 * bow
    head_dx = S['sway'] * np.sin(2 * np.pi * t / 7.7)                  # 아주 작은 좌우 흔들림
    add("neck", 0, 3 * bow)
    for k in ("sh_l", "sh_r"):
        add(k, 0, 5 * bow)

    # 고개 회전(목 기준) + 이동
    straight = HEAD_STRAIGHTEN if S.get("straighten") else 0.0
    for k, f in (("head_top", 1.0), ("head_mid", 0.85), ("head_l", 0.9), ("head_r", 0.9), ("chin", 0.7)):
        base = P0[idx[k]] - NECK_PIVOT
        ang = np.deg2rad(tilt + straight)
        rx = base[0] * np.cos(ang) - base[1] * np.sin(ang)
        ry = base[0] * np.sin(ang) + base[1] * np.cos(ang)
        D[:, idx[k], 0] += (rx - base[0]) + head_dx * f
        D[:, idx[k], 1] += (ry - base[1]) + head_dy * f

    # --- 손 비트 제스처 (말의 박자) ---
    beats = []
    for s, e in timing:
        beats.append(s + 0.05)
        # 문장 안 강세 지점
        fr = np.arange(int(s * FPS), min(n - 1, int(e * FPS)))
        if len(fr) > 20:
            peaks = fr[1:-1][(accent[fr[1:-1]] > accent[fr[:-2]]) & (accent[fr[1:-1]] >= accent[fr[2:]])]
            peaks = [p for p in peaks if accent[p] > np.percentile(accent[fr], S['beat_pct'])]
            last = -99
            for p in peaks:
                if p / FPS - last > S['beat_gap']:
                    beats.append(p / FPS - 0.08); last = p / FPS
    hand_up = np.zeros(n); hand_x = np.zeros(n)
    for b in beats:
        amp = rng.uniform(0.6, 1.0)
        hand_up += amp * _bump(t, b, 0.55)
        hand_x += rng.uniform(-1, 1) * amp * _bump(t, b, 0.55)
    hand_up = np.clip(hand_up, 0, 1.3)
    hdy = -S['hand'] * hand_up + 6 * bow; hdx = S['hand_x'] * hand_x
    add("hands", hdx, hdy); add("wr_l", hdx * 0.9, hdy * 0.9); add("wr_r", hdx * 0.9, hdy * 0.9)
    add("el_l", hdx * 0.3 - 4 * hand_up, hdy * 0.35); add("el_r", hdx * 0.3 + 4 * hand_up, hdy * 0.35)

    # --- 카메라 연동: 다가오는 샷 시작에 고개 끄덕 + 손 제스처 ---
    if shots:
        for (s, _), kind in zip(timing, shots):
            if kind in ("medium", "close"):
                b = _bump(t, s - 0.05, 0.7)
                cn = S.get("camnod", 1.0)
                for hk in ("head_top", "head_mid", "head_l", "head_r", "chin"):
                    D[:, idx[hk], 1] += 6 * b * cn
                D[:, idx["hands"], 1] -= 8 * b
    return D


def mls_inverse_map(p_src, q_dst, shape, step=8, alpha=1.0):
    """MLS(rigid) 변형의 역방향 좌표맵: 출력 픽셀 → 원본 위치. p_src/q_dst: (K,2) 같은 좌표계"""
    h, w = shape
    gx, gy = np.meshgrid(np.arange(0, w + step, step, dtype=np.float32),
                         np.arange(0, h + step, step, dtype=np.float32))
    v = np.stack([gx.ravel(), gy.ravel()], 1)                    # (N,2)
    p, q = q_dst.astype(np.float32), p_src.astype(np.float32)    # 역방향: 변형 후 → 원래
    d2 = ((v[:, None, :] - p[None]) ** 2).sum(-1) + 1e-6
    wgt = 1.0 / d2 ** alpha                                       # (N,K)
    ws = wgt.sum(1, keepdims=True)
    pstar = (wgt @ p) / ws; qstar = (wgt @ q) / ws
    ph = p[None] - pstar[:, None]; qh = q[None] - qstar[:, None]  # (N,K,2)
    vp = v - pstar
    # rigid MLS
    a = (wgt[..., None] * (qh * ph).sum(-1, keepdims=True)).sum(1)              # Σ w (q̂·p̂)
    b = (wgt[..., None] * (qh[..., 0] * ph[..., 1] - qh[..., 1] * ph[..., 0])[..., None]).sum(1)
    mu = np.sqrt(a ** 2 + b ** 2) + 1e-6
    cos, sin = a / mu, b / mu
    fx = cos[:, 0] * vp[:, 0] + sin[:, 0] * vp[:, 1]
    fy = -sin[:, 0] * vp[:, 0] + cos[:, 0] * vp[:, 1]
    out = np.stack([fx, fy], 1) + qstar
    mx = out[:, 0].reshape(gx.shape); my = out[:, 1].reshape(gx.shape)
    mx = cv2.resize(mx, (gx.shape[1] * step, gx.shape[0] * step), interpolation=cv2.INTER_LINEAR)[:h, :w]
    my = cv2.resize(my, (gx.shape[1] * step, gx.shape[0] * step), interpolation=cv2.INTER_LINEAR)[:h, :w]
    return mx.astype(np.float32), my.astype(np.float32)


def warp_body(img_rgba: np.ndarray, disp_k: np.ndarray, scale: float, pad: int) -> np.ndarray:
    """img_rgba: 패딩된 캐스터 이미지(배율 scale), disp_k: (K,2) caster_hi 단위 이동량"""
    h, w = img_rgba.shape[:2]
    p = P0 * scale + pad
    q = (P0 + disp_k) * scale + pad
    # 이미지 네 모서리 고정(바깥 안정)
    corners = np.array([[0, 0], [w, 0], [0, h], [w, h]], np.float32)
    p = np.vstack([p, corners]); q = np.vstack([q, corners])
    mx, my = mls_inverse_map(p, q, (h, w), step=16)
    return cv2.remap(img_rgba, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
