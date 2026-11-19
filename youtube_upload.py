"""
7단계-1: 유튜브 쇼츠 업로드 (YouTube Data API v3)
환경변수: YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN
          YT_PRIVACY = private(기본) | unlisted | public
최초 1회 tools/get_youtube_token.py 로 YT_REFRESH_TOKEN 발급
"""
import os

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def _client():
    creds = Credentials(
        None,
        refresh_token=os.environ["YT_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["YT_CLIENT_ID"],
        client_secret=os.environ["YT_CLIENT_SECRET"],
        scopes=SCOPES,
    )
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def upload_short(path: str, w: dict, script: str) -> str:
    d = w["date"]
    title = f"[JNN뉴스] {d.month}월 {d.day}일 {w['region']} 아침 날씨 | {w['temp']}° {w['sky']} #Shorts"
    body = {
        "snippet": {
            "title": title[:100],
            "description": f"{script}\n\n#전남광주날씨 #광주날씨 #오늘날씨 #JNN뉴스 #Shorts",
            "tags": ["전남광주날씨", "광주날씨", "오늘날씨", "JNN뉴스", "기상캐스터"],
            "categoryId": "25",                  # News & Politics
            "defaultLanguage": "ko",
        },
        "status": {
            "privacyStatus": os.getenv("YT_PRIVACY", "private"),
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": True,      # AI 생성 영상 표시
        },
    }
    req = _client().videos().insert(
        part="snippet,status", body=body,
        media_body=MediaFileUpload(path, mimetype="video/mp4", chunksize=-1, resumable=True))
    res = None
    while res is None:
        _, res = req.next_chunk()
    url = f"https://youtube.com/shorts/{res['id']}"
    print("[유튜브]", url, f"({body['status']['privacyStatus']})")
    return url
