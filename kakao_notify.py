"""
7단계-2: 카카오톡 '나에게 보내기' 알림
환경변수: KAKAO_REST_KEY, KAKAO_REFRESH_TOKEN, (선택) KAKAO_CLIENT_SECRET
          GH_PAT, GITHUB_REPOSITORY  ← 갱신된 refresh token을 GitHub Secret에 자동 저장
최초 1회 tools/get_kakao_token.py 로 KAKAO_REFRESH_TOKEN 발급
"""
import base64
import json
import os

import requests

TOKEN_URL = "https://kauth.kakao.com/oauth/token"
MEMO_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"


def refresh_access_token() -> str:
    data = {
        "grant_type": "refresh_token",
        "client_id": os.environ["KAKAO_REST_KEY"],
        "refresh_token": os.environ["KAKAO_REFRESH_TOKEN"],
    }
    if os.getenv("KAKAO_CLIENT_SECRET"):
        data["client_secret"] = os.environ["KAKAO_CLIENT_SECRET"]
    r = requests.post(TOKEN_URL, data=data, timeout=30)
    r.raise_for_status()
    tok = r.json()
    # 만료 1개월 전부터 새 refresh token이 함께 내려옴 → 저장해 두어야 계속 동작
    if tok.get("refresh_token"):
        save_github_secret("KAKAO_REFRESH_TOKEN", tok["refresh_token"])
    return tok["access_token"]


def save_github_secret(name: str, value: str):
    pat, repo = os.getenv("GH_PAT"), os.getenv("GITHUB_REPOSITORY")
    if not (pat and repo):
        print(f"[주의] 새 {name} 발급됨. GitHub Secret을 직접 갱신하세요:\n{value}")
        return
    from nacl import encoding, public
    h = {"Authorization": f"Bearer {pat}", "Accept": "application/vnd.github+json"}
    k = requests.get(f"https://api.github.com/repos/{repo}/actions/secrets/public-key",
                     headers=h, timeout=30).json()
    box = public.SealedBox(public.PublicKey(k["key"].encode(), encoding.Base64Encoder()))
    enc = base64.b64encode(box.encrypt(value.encode())).decode()
    r = requests.put(f"https://api.github.com/repos/{repo}/actions/secrets/{name}", headers=h,
                     json={"encrypted_value": enc, "key_id": k["key_id"]}, timeout=30)
    r.raise_for_status()
    print(f"[카카오] {name} 자동 갱신 완료")


def build_message(w: dict, url: str) -> dict:
    d = w["date"]
    wd = "월화수목금토일"[d.weekday()]
    rain = w["pty"] not in ("", "없음")
    icon = ("❄️" if "눈" in w["pty"] else "☔" if rain else
            {"맑음": "☀️", "구름많음": "🌤", "흐림": "☁️"}.get(w["sky"], "🌤"))
    lines = [
        f"{icon} JNN뉴스 {w['region']} 날씨",
        f"{d.month}월 {d.day}일 ({wd}) 오전 8시",
        "",
        f"현재 {w['temp']}° · {w['sky']}" + (f" · {w['pty']}" if rain else ""),
        f"최저 {w['tmin']}° / 최고 {w['tmax']}°",
        f"강수확률 {w['pop']}% · 미세먼지 {w['pm']}",
        "",
        "오늘의 날씨 영상이 준비되었습니다.",
    ]
    return {
        "object_type": "text",
        "text": "\n".join(lines)[:200],
        "link": {"web_url": url, "mobile_web_url": url},
        "button_title": "영상 보기",
    }


def send_to_me(w: dict, url: str):
    token = refresh_access_token()
    r = requests.post(MEMO_URL, headers={"Authorization": f"Bearer {token}"},
                      data={"template_object": json.dumps(build_message(w, url), ensure_ascii=False)},
                      timeout=30)
    if r.status_code != 200 or r.json().get("result_code") != 0:
        raise RuntimeError(f"카카오 전송 실패: {r.status_code} {r.text}")
    print("[카카오] 나에게 보내기 완료")


def send_error(msg: str):
    """제작 실패 시에도 카톡으로 알림"""
    try:
        token = refresh_access_token()
        tmpl = {"object_type": "text", "text": f"⚠️ JNN 날씨 영상 제작 실패\n{msg}"[:200],
                "link": {"web_url": "https://github.com", "mobile_web_url": "https://github.com"}}
        requests.post(MEMO_URL, headers={"Authorization": f"Bearer {token}"},
                      data={"template_object": json.dumps(tmpl, ensure_ascii=False)}, timeout=30)
    except Exception as e:
        print("[카카오] 오류 알림도 실패:", e)
