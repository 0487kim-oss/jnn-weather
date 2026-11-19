"""
유튜브 업로드용 refresh token 최초 발급 (PC에서 1회 실행 — 브라우저 로그인 필요)

사전 설정 (console.cloud.google.com):
  1. TTS와 같은 프로젝트에서 'YouTube Data API v3' 사용 설정
  2. [OAuth 동의 화면] 외부 → 앱 이름 입력 → 게시 상태를 '프로덕션'으로 변경
     (테스트 상태로 두면 refresh token이 7일 뒤 만료됨)
  3. [사용자 인증 정보] OAuth 클라이언트 ID → 데스크톱 앱 → JSON 다운로드
     → 이 폴더에 client_secret.json 으로 저장
실행: pip install google-auth-oauthlib && python tools/get_youtube_token.py
"""
import json
from google_auth_oauthlib.flow import InstalledAppFlow

flow = InstalledAppFlow.from_client_secrets_file(
    "client_secret.json", scopes=["https://www.googleapis.com/auth/youtube.upload"])
creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
info = json.load(open("client_secret.json"))["installed"]
print("\n✅ GitHub Secrets 에 저장할 값")
print("YT_CLIENT_ID     =", info["client_id"])
print("YT_CLIENT_SECRET =", info["client_secret"])
print("YT_REFRESH_TOKEN =", creds.refresh_token)
