"""
3단계: 날씨 대본 작성 (OpenAI) — 실패하면 템플릿 대본으로 대체
"""
import os

from openai import OpenAI

SCRIPT_MODEL = os.getenv("SCRIPT_MODEL", "gpt-4.1-mini")

SYSTEM = """너는 JNN뉴스 아침 날씨 숏폼(9:16) 코너의 기상캐스터 '김하늘'의 대본 작가다.
목표: 밝고 경쾌하지만 신뢰감 있는 말투, 사람이 말하듯 자연스러운 대본.
규칙:
- 6~8문장, 소리 내어 읽으면 30~40초. 한 문장은 짧게(25자 안팎)
- 첫 문장: "안녕하세요! {M}월 {D}일 아침 8시, {지역} 날씨입니다."
- 마지막 문장: "지금까지 JNN뉴스 기상캐스터 김하늘이었습니다."
- 말끝은 "~인데요", "~고요", "~니까요", "~겠습니다"를 섞어 대화하듯
- 숫자는 주어진 값만 사용(지어내지 말 것). 기온 ℃, 확률 %
- 날씨에 맞는 생활 조언 1개 + 밝은 응원 한마디
- 빠르게 읽으면 다른 말로 들릴 수 있는 표현은 피함(예: "춥겠습니다" 대신 "쌀쌀하겠습니다", "추위가 매섭겠습니다")
- 이모지, 괄호, 따옴표 금지"""


def template_script(w: dict) -> str:
    d = w["date"]
    sky = {"맑음": "맑겠고요", "구름많음": "구름이 많겠고요", "흐림": "흐리겠고요"}.get(w["sky"], "")
    rain = w["pty"] not in ("", "없음")
    pty = w["pty"].replace("/", " 또는 ")
    if rain:
        tip = "외출하실 때 우산 꼭 챙기세요."
    elif w["pm"] in ("나쁨", "매우나쁨"):
        tip = "마스크 꼭 챙기세요."
    elif w["tmax"] - w["tmin"] >= 10:
        tip = "일교차가 크니까요, 가벼운 겉옷 챙기세요."
    elif w["temp"] <= 5:
        tip = "꽤 쌀쌀하니까요, 따뜻하게 입고 나가세요."
    else:
        tip = "나들이하기 좋은 날씨가 이어지겠습니다."
    return " ".join([
        f"안녕하세요! {d.month}월 {d.day}일 아침 8시, {w['region']} 날씨입니다.",
        f"지금 광주는 {w['temp']}℃인데요.",
        f"오늘 하늘은 {sky}, {pty} 소식이 있겠습니다." if rain else f"오늘 하늘은 {sky}, 비 소식은 없겠습니다.",
        f"낮 최고기온은 {w['tmax']}℃, 강수확률은 {w['pop']}%입니다.",
        f"미세먼지는 {w['pm']} 수준이고요.",
        tip,
        "오늘 하루도 힘차게 보내세요!",
        "지금까지 JNN뉴스 기상캐스터 김하늘이었습니다.",
    ])


def write_script(w: dict) -> str:
    try:
        d = w["date"]
        facts = (f"날짜 {d.month}월 {d.day}일, 지역 {w['region']}, 오전8시 기온 {w['temp']}℃, "
                 f"최저 {w['tmin']}℃, 최고 {w['tmax']}℃, 하늘 {w['sky']}, 강수형태 {w['pty']}, "
                 f"강수확률 {w['pop']}%, 풍속 {w.get('wind', 0)}m/s, 습도 {w.get('humidity', 0)}%, "
                 f"미세먼지 {w['pm']}")
        res = OpenAI().chat.completions.create(
            model=SCRIPT_MODEL, temperature=0.7,
            messages=[{"role": "system", "content": SYSTEM},
                      {"role": "user", "content": f"오늘 날씨 데이터: {facts}\n대본만 출력해."}])
        text = " ".join(res.choices[0].message.content.split())
        if "김하늘" not in text or len(text) < 80:
            raise ValueError("대본 형식 불일치")
        return text
    except Exception as e:
        print("[경고] LLM 대본 실패, 템플릿 사용:", e)
        return template_script(w)
