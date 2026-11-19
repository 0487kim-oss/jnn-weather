"""
휴대폰만으로 카카오 refresh token 발급 → GitHub Secret 자동 저장 → 테스트 메시지
GitHub Actions의 '카카오 알림 최초 연결' 워크플로에서 실행됩니다.
필요 Secrets: KAKAO_REST_KEY, KAKAO_CLIENT_SECRET(켜져 있으면), GH_PAT
"""
import os, sys, requests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from kakao_notify import save_github_secret

REDIRECT = "https://localhost"
code = os.environ.get("KAKAO_CODE", "").strip()
if "code=" in code:                       # 주소 전체를 붙여 넣어도 동작
    code = code.split("code=", 1)[1].split("&", 1)[0]
data = {"grant_type": "authorization_code", "client_id": os.environ["KAKAO_REST_KEY"],
        "redirect_uri": REDIRECT, "code": code}
if os.getenv("KAKAO_CLIENT_SECRET"):
    data["client_secret"] = os.environ["KAKAO_CLIENT_SECRET"]
r = requests.post("https://kauth.kakao.com/oauth/token", data=data, timeout=30)
if r.status_code != 200:
    print("❌ 토큰 발급 실패:", r.json().get("error_description", r.text))
    print("   코드는 1회용이며 약 10분 안에 써야 합니다. 동의 주소를 다시 열어 새 코드로 실행하세요.")
    sys.exit(1)
tok = r.json()
save_github_secret("KAKAO_REFRESH_TOKEN", tok["refresh_token"])
print("✅ KAKAO_REFRESH_TOKEN 을 GitHub Secrets에 저장했습니다.")
m = requests.post("https://kapi.kakao.com/v2/api/talk/memo/default/send",
                  headers={"Authorization": f"Bearer {tok['access_token']}"},
                  data={"template_object": '{"object_type":"text","text":"JNN 날씨 알림 연결 완료! ☀️",'
                        '"link":{"web_url":"https://www.youtube.com"}}'}, timeout=30)
print("✅ 카카오톡 '나와의 채팅'에 테스트 메시지 전송" if m.ok else f"⚠️ 테스트 메시지 실패: {m.text}")
