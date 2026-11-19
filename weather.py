"""
1단계: 오늘 날씨 수집 (기상청 단기예보 + 에어코리아 미세먼지)
- 공공데이터포털(data.go.kr)에서 아래 두 API 활용신청 → 같은 인증키 사용
  · 기상청_단기예보 ((구)_동네예보) 조회서비스
  · 한국환경공단_에어코리아_대기오염정보
- 환경변수 DATA_GO_KR_KEY = 일반 인증키(Decoding)
"""
import datetime as dt
import os
from statistics import mean
from zoneinfo import ZoneInfo

import requests

KST = ZoneInfo("Asia/Seoul")
REGION = "전남광주"
NX, NY = 58, 74            # 광주 시청 격자. 통합청사 위치 확정 시 변경
SIDO = "광주"              # 에어코리아 시도명
TARGET_HOUR = "0800"       # 기준 시각: 오전 8시

KMA_URL = "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"
AIR_URL = "https://apis.data.go.kr/B552584/ArpltnInforInqireSvc/getCtprvnRltmMesureDnsty"

SKY = {"1": "맑음", "3": "구름많음", "4": "흐림"}
PTY = {"0": "없음", "1": "비", "2": "비/눈", "3": "눈", "4": "소나기"}


def _base_time(now: dt.datetime) -> tuple[str, str]:
    """가장 최근 발표 시각 (02,05,08,11,14,17,20,23시 + 10분 후 제공)"""
    slots = [2, 5, 8, 11, 14, 17, 20, 23]
    t = now - dt.timedelta(minutes=10)
    hours = [h for h in slots if h <= t.hour]
    if not hours:
        t -= dt.timedelta(days=1)
        return t.strftime("%Y%m%d"), "2300"
    return t.strftime("%Y%m%d"), f"{hours[-1]:02d}00"


def fetch_forecast(key: str, now: dt.datetime) -> dict:
    base_date, base_time = _base_time(now)
    r = requests.get(KMA_URL, params={
        "serviceKey": key, "pageNo": 1, "numOfRows": 1000, "dataType": "JSON",
        "base_date": base_date, "base_time": base_time, "nx": NX, "ny": NY,
    }, timeout=30)
    r.raise_for_status()
    items = r.json()["response"]["body"]["items"]["item"]
    return parse_forecast(items, now.strftime("%Y%m%d"))


def parse_forecast(items: list[dict], today: str) -> dict:
    day = [i for i in items if i["fcstDate"] == today]
    at = {i["category"]: i["fcstValue"] for i in day if i["fcstTime"] == TARGET_HOUR}
    if not at:   # 08시 예보가 지났으면 가장 가까운 시각 사용
        first = min(i["fcstTime"] for i in day)
        at = {i["category"]: i["fcstValue"] for i in day if i["fcstTime"] == first}
    temps = [float(i["fcstValue"]) for i in day if i["category"] == "TMP"]
    tmn = next((float(i["fcstValue"]) for i in day if i["category"] == "TMN"), min(temps))
    tmx = next((float(i["fcstValue"]) for i in day if i["category"] == "TMX"), max(temps))
    return {
        "temp": round(float(at["TMP"])),
        "tmin": round(tmn), "tmax": round(tmx),
        "sky": SKY.get(at.get("SKY"), "맑음"),
        "pty": PTY.get(at.get("PTY"), "없음"),
        "pop": int(at.get("POP", 0)),
        "wind": float(at.get("WSD", 0)),
        "humidity": int(at.get("REH", 0)),
    }


# ---------------- 지도용 도시별 기온 ----------------
CITIES = {"광주": (35.1595, 126.8526), "목포": (34.8118, 126.3922), "순천": (34.9507, 127.4872),
          "여수": (34.7604, 127.6622), "완도": (34.3110, 126.7550)}


def latlon_to_grid(lat: float, lon: float) -> tuple[int, int]:
    """위경도 → 기상청 격자(nx, ny) (기상청 LCC 변환식)"""
    import math
    RE, GRID, SLAT1, SLAT2, OLON, OLAT, XO, YO = 6371.00877, 5.0, 30.0, 60.0, 126.0, 38.0, 43, 136
    D = math.pi / 180.0
    re = RE / GRID
    s1, s2, olon, olat = SLAT1 * D, SLAT2 * D, OLON * D, OLAT * D
    sn = math.log(math.cos(s1) / math.cos(s2)) / math.log(math.tan(math.pi / 4 + s2 / 2) / math.tan(math.pi / 4 + s1 / 2))
    sf = math.tan(math.pi / 4 + s1 / 2) ** sn * math.cos(s1) / sn
    ro = re * sf / math.tan(math.pi / 4 + olat / 2) ** sn
    ra = re * sf / math.tan(math.pi / 4 + lat * D / 2) ** sn
    th = lon * D - olon
    th = th - 2 * math.pi if th > math.pi else th + 2 * math.pi if th < -math.pi else th
    th *= sn
    return int(ra * math.sin(th) + XO + 0.5), int(ro - ra * math.cos(th) + YO + 0.5)


def fetch_cities(key: str, now: dt.datetime) -> dict:
    base_date, base_time = _base_time(now)
    out = {}
    for name, (lat, lon) in CITIES.items():
        nx, ny = latlon_to_grid(lat, lon)
        try:
            r = requests.get(KMA_URL, params={
                "serviceKey": key, "pageNo": 1, "numOfRows": 300, "dataType": "JSON",
                "base_date": base_date, "base_time": base_time, "nx": nx, "ny": ny}, timeout=30)
            items = r.json()["response"]["body"]["items"]["item"]
            out[name] = round(parse_forecast(items, now.strftime("%Y%m%d"))["temp"])
        except Exception as e:
            print(f"[경고] {name} 기온 조회 실패:", e)
    return out


def pm_grade(pm25: float) -> str:
    return "좋음" if pm25 <= 15 else "보통" if pm25 <= 35 else "나쁨" if pm25 <= 75 else "매우나쁨"


def fetch_air(key: str) -> str:
    try:
        r = requests.get(AIR_URL, params={
            "serviceKey": key, "returnType": "json", "numOfRows": 100,
            "pageNo": 1, "sidoName": SIDO, "ver": "1.0",
        }, timeout=30)
        r.raise_for_status()
        vals = [float(i["pm25Value"]) for i in r.json()["response"]["body"]["items"]
                if str(i.get("pm25Value", "-")).replace(".", "").isdigit()]
        return pm_grade(mean(vals)) if vals else "보통"
    except Exception as e:                       # 미세먼지 실패해도 영상은 계속 제작
        print("[경고] 미세먼지 조회 실패:", e)
        return "보통"


def fetch_weather(now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now(KST)
    key = os.environ["DATA_GO_KR_KEY"]
    w = fetch_forecast(key, now)
    w.update({"date": now.date(), "region": REGION, "pm": fetch_air(key),
              "cities": fetch_cities(key, now)})
    print("[날씨]", w)
    return w


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    fetch_weather()
