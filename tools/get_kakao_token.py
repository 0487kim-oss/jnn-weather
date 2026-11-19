"""
카카오 refresh token 최초 발급 (PC나 휴대폰 Termux에서 1회 실행)

사전 설정 (developers.kakao.com → 내 애플리케이션):
  1. 앱 만들기 → [앱 키]에서 REST API 키 복사
  2. [카카오 로그인] 활성화 ON, Redirect URI에 https://localhost 등록
  3. [동의항목] '카카오톡 메시지 전송(talk_message)' 선택 동의로 설정
  4. [플랫폼] Web 사이트 도메인에 https://youtube.com, https://www.youtube.com 등록
     (메시지 링크 도메인으로 쓰려면 등록 필수)
실행: python tools/get_kakao_token.py
"""
import requests

REDIRECT = "https://localhost"
key = input("REST API 키: ").strip()
secret = input("Client Secret (사용 안 하면 엔터): ").strip()

print("\n아래 주소를 브라우저에서 열고 동의하세요:")
print(f"https://kauth.kakao.com/oauth/authorize?client_id={key}"
      f"&redirect_uri={REDIRECT}&response_type=code&scope=talk_message\n")
print("이동된 주소(접속 오류 화면이어도 정상) 중 code= 뒤의 값을 복사하세요.")
code = input("code: ").strip()

data = {"grant_type": "authorization_code", "client_id": key,
        "redirect_uri": REDIRECT, "code": code}
if secret:
    data["client_secret"] = secret
r = requests.post("https://kauth.kakao.com/oauth/token", data=data, timeout=30)
r.raise_for_status()
tok = r.json()
print("\n✅ GitHub Secret 'KAKAO_REFRESH_TOKEN' 에 저장할 값:\n" + tok["refresh_token"])

# 테스트 메시지
requests.post("https://kapi.kakao.com/v2/api/talk/memo/default/send",
              headers={"Authorization": f"Bearer {tok['access_token']}"},
              data={"template_object": '{"object_type":"text","text":"JNN 날씨 알림 연결 완료!",'
                    '"link":{"web_url":"https://www.youtube.com"}}'}, timeout=30)
print("카카오톡 '나와의 채팅'에 테스트 메시지가 왔는지 확인하세요.")
