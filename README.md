# JNN뉴스 전남광주 아침 날씨 — 매일 자동 제작

JNN뉴스 오늘의 날씨 설명

## 엔진 선택 (자동)
| 엔진 | 음성 | 입 움직임 | 의상 | 비용 |
|---|---|---|---|---|
| **free** (기본) | Supertonic 2 한국어 여성 (오프라인) | 오프라인 립싱크 (입 모양·끄덕임·깜빡임) | OPENAI_API_KEY 있으면 날씨별 변환, 없으면 기본 의상 | 0원 (의상 변환 시 이미지 1장 비용) |
| **api** | Google TTS | D-ID 립싱크 | OpenAI 전신 재생성 | 유료 |

- `--engine` 을 주지 않으면 DID_API_KEY 와 OPENAI_API_KEY 가 모두 있을 때만 api, 아니면 free
- free 엔진 의상 변환은 머리·얼굴을 원본 그대로 두고 옷만 바꿈 → 립싱크 좌표 유지
- 최초 1회: `python tools/download_models.py` (음성 모델 85MB, GitHub Actions는 자동·캐시)
- API 없이 바로 테스트: `python main.py --weather-json sample_weather.json --no-upload`

매일 06:40 자동 실행 → 날씨 수집 → 의상 변환 캐스터 → 아나운서 음성·립싱크
→ 9:16 합성 → 유튜브 쇼츠 업로드 → 카카오톡 '나와의 채팅'으로 링크 알림

## 영상 구성 (무료 엔진 기본값)

| 항목 | 내용 | 바꾸는 곳 |
|---|---|---|
| 시그널 | 매일 영상 맨 앞에 `assets/jingle.wav`(1번 시그널) 자동 삽입 → 1.85초 뒤 인사 시작, 말이 시작되면 시그널 여운이 자동으로 작아짐 | GitHub 저장소 Settings → Variables: `JINGLE`(`off`=끄기, 다른 wav 경로=교체), `JINGLE_INTRO`(초) |
| 목소리 | Supertonic 2 여성 화자 1번, 밝고 경쾌한 톤, 속도 1.1, 방송용 음량(−16 LUFS) | `free_tts.py`의 `VOICE_SID`, `SPEED` |
| 배경음악 | 인사 시작 후 작게(9%) 깔림 | `assets/bgm.wav`, `caster_compose.py`의 `BGM_AFTER_INTRO` |
| 대본 | 밝은 대화체(~인데요/~고요), 6~8문장 30~40초. OpenAI 키가 없으면 템플릿 사용 | `script_writer.py` |
| 입모양 | 한글 발음(초·중·종성) 기반 립싱크, 입술 떨림 없는 근육 스무딩 | `free_viseme.py` |
| 동작 | 고개 반듯·시선 정면, 호흡·체중이동·끄덕임·손동작 | `free_pose.py`의 `STYLES["anchor"]` |
| 카메라 | 와이드/미디엄/클로즈업 자동 컷·줌, 지역별 기온 지도 CG | `free_lipsync.py`의 `plan_shots` |
| 화면 | 상단 날씨 정보, 기온 카드, 문장별 정확한 자막, JNN 로고, 2.5초 엔딩 | `caster_compose.py` |

## 파일 구성
| 파일 | 단계 |
|---|---|
| weather.py | 1 기상청 단기예보 + 에어코리아 미세먼지 + 지도용 5개 도시 기온 |
| free_tts.py | 5 (free) Supertonic 음성, 숫자 한국어 읽기, 문장별 타이밍 |
| free_lipsync.py | 5 (free) 입·눈 렌더링, 카메라 워크(와이드·미디엄·클로즈업·지도 CG), 스튜디오 배경 |
| free_viseme.py | 5 (free) 발음 기반 입 모양: 음절 정렬 → ㅁㅂㅍ 입술 닫힘, ㅏ 벌림, ㅗㅜ 동그랗게, ㅣㅔ 옆으로 |
| free_pose.py | 5 (free) 전신 자연 동작: 체중 이동, 호흡, 고개, 손 박자 제스처, 인사·마무리 목례 (관절 + MLS 변형) |
| outfit.py | 2·4 (free) OpenAI 이미지 편집으로 옷만 변환 |
| caster_image.py | 2·4 의상 결정 + 캐스터 이미지 (OpenAI) |
| script_writer.py | 3 대본 (OpenAI, 실패 시 템플릿) |
| caster_video.py | 5 Google TTS + D-ID 립싱크 |
| caster_compose.py | 6 타이틀·카드·자막·JNN 로고·엔딩 합성 |
| youtube_upload.py | 7 유튜브 쇼츠 업로드 |
| kakao_notify.py | 7 카카오톡 나에게 보내기 (+ 실패 알림) |
| main.py | 전체 실행 |
| .github/workflows/daily-weather.yml | 매일 자동 실행 |

## 설정 순서 (최초 1회)

### 1. 키 발급
- **공공데이터포털**: 기상청 단기예보, 에어코리아 대기오염정보 활용신청 → 일반 인증키(Decoding)
- **OpenAI**: API 키
- **Google Cloud**: Text-to-Speech API 사용 설정 → 서비스 계정 키(JSON)
- **D-ID**: API 키
- **유튜브**: `tools/get_youtube_token.py` 안내대로 (PC에서 1회)
- **카카오**: `tools/get_kakao_token.py` 안내대로 (PC 또는 Termux에서 1회)

### 2. GitHub 저장소 만들기
- github.com → New repository → **Private** 선택 → 이 폴더 전체 업로드
- (공개 저장소는 60일간 활동이 없으면 예약 실행이 멈춥니다)

### 3. Secrets 등록
저장소 → Settings → Secrets and variables → Actions → New repository secret

| 이름 | 값 |
|---|---|
| DATA_GO_KR_KEY | 공공데이터포털 인증키 |
| OPENAI_API_KEY | OpenAI 키 |
| GCP_KEY_JSON | 서비스 계정 JSON 파일 **내용 전체** |
| DID_API_KEY | D-ID 키 |
| YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN | 유튜브 토큰 도구 출력값 |
| KAKAO_REST_KEY | 카카오 REST API 키 |
| KAKAO_CLIENT_SECRET | 사용 시에만 |
| KAKAO_REFRESH_TOKEN | 카카오 토큰 도구 출력값 |
| GH_PAT | 카카오 토큰 자동 갱신용 (아래 참고) |

**GH_PAT 만들기**: GitHub → Settings → Developer settings → Fine-grained tokens
→ 이 저장소만 선택 → Repository permissions의 **Secrets: Read and write** → 생성

(선택) Variables 탭에 `YT_PRIVACY` = `unlisted` 또는 `public`

### 4. 테스트
저장소 → Actions → "JNN 전남광주 아침 날씨" → **Run workflow**
→ 5~10분 뒤 카카오톡 '나와의 채팅' 확인 (휴대폰 브라우저에서도 실행 가능)

## 알아둘 점
- 유튜브 API로 올린 영상은 Google 감사(audit)를 통과하기 전까지 **비공개로 고정**됩니다.
  본인 계정으로 로그인한 유튜브 앱에서는 재생되므로 카톡 링크로 확인 → 앱에서 공개 전환하면 됩니다.
  자동 공개가 필요하면 Google의 YouTube API 감사 신청을 하세요.
- 카카오 refresh token은 약 2개월 유효하며, 만료 1개월 전부터 새 토큰이 자동 발급·저장됩니다.
- 실패하면 카카오톡으로 오류 알림이 오고, 영상 파일은 Actions 실행 결과(Artifacts)에 7일간 보관됩니다.
- 로컬에서 영상만 만들기: `python main.py --no-upload`
