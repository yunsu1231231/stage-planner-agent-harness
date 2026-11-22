# 03. 기획 검증 (명세 2.7)

> 각 항목을 실제로 실행하고 결과를 기록한다. 통과하지 못한 항목은 기획 문서로 돌아가 수정하고, 변경 내역을 5절에 남긴다.
> 실행 스크립트: `scripts/validation/` · 원본 결과: `docs/validation/results.json` · 실제 응답: `docs/validation/samples/` (키 마스킹)

## 1. 도메인 조건 확인 — ✅ 통과 (2026-11-22)

| # | 항목 | 결과 | 비고 |
|---|---|---|---|
| V1 | KOPIS 공연목록 호출 | ✅ | 서울·공연중·7일 → 20건. **응답은 XML** (`application/xml`) |
| V2 | KOPIS 공연상세 호출 | ✅ | `prfruntime`, `dtguidance`, `pcseguidance`, `prfage`, `mt10id` 확인 |
| V3 | KOPIS 공연시설상세 호출 | ✅ | `la`/`lo` 좌표, 주소 (예: 종로구 대학로8가길 52) |
| V4 | 카카오 로컬 호출 | ✅ | V3 좌표 반경 500m 식당 5건 (이름·도로명주소·거리·place_url) |
| V5 | LLM만으로 답하면 틀리는 지점 | ✅ | 아래 표 |

| 대표 요청 | Tool 없이 LLM만 답하면 틀리는 것 |
|---|---|
| S1 | 해당 날짜에 실제로 공연 중인 작품·회차 시각·가격을 알 수 없어 지어낸다 |
| S2 | 실제 후보가 조건을 만족하는지 알 수 없어 재계획이 성립하지 않는다 |
| S7 | 실제 뮤지컬 목록이 없어 장르 변경 결과를 확인할 수 없다 |

## 2. Tool 설계 확인

| # | 항목 | 결과 | 비고 |
|---|---|---|---|
| T1 | 실제 응답 → Tool 출력 구조 매핑 | ✅ | 아래 2.1 대조표 |
| T2 | 판단 속성 존재·파싱 가능 비율 (샘플 20건) | ✅ | 러닝타임·회차 시각·가격 모두 20/20 채움, 정규식 1차 파싱 20/20 |
| T3 | 실패 케이스 실제 응답 | ✅ | 아래 2.2 |
| T4 | 출처별 호출 한도·약관 | △ | **카카오**: 키워드·카테고리 장소 검색 각 일 100,000건, 전체 월 3,000,000건 ([쿼터 문서](https://developers.kakao.com/docs/latest/ko/getting-started/quota)). **KOPIS**: 공개 페이지에서 약관·한도 미확인 → 마이페이지/OpenAPI 안내 확인 필요 (NF3007) |

### 2.1 필드 대조표

| Tool 출력 | 원본 필드 | 예시 |
|---|---|---|
| `performance_id` | KOPIS `mt20id` | PF307123 |
| `title` / `venue_name` / `genre` | `prfnm` / `fcltynm` / `genrenm` | |
| `start_date`/`end_date` | `prfpdfrom`/`prfpdto` | `2027.01.09` (점 구분) |
| `runtime_min` | `prfruntime` | "1시간 10분" → 70 |
| `schedule` | `dtguidance` | "토요일 ~ 일요일(15:00)" |
| `min_price` | `pcseguidance` | "전석 30,000원" → 30000 |
| `age_limit` | `prfage` | |
| `venue_id` | `mt10id` | FC001091 |
| 좌표 | 시설 `la`/`lo` | 37.5829 / 127.0026 |
| `places[]` | 카카오 `place_name`, `road_address_name`, `distance`, `place_url`, `phone` | |

### 2.2 실패 응답 → 실패 코드 매핑

| 상황 | 실제 응답 | 실패 코드 |
|---|---|---|
| KOPIS 잘못된 키 | **HTTP 200** + `<returncode>02</returncode><errmsg>SERVICE KEY IS NOT REGISTERED ERROR` | `AUTH_FAILED` |
| KOPIS 없는 공연 ID | **HTTP 200** + `returncode 04` `NODATA ERROR` | `NOT_FOUND` |
| KOPIS 결과 0건 | HTTP 200 + 빈 `<dbs/>` | `NO_RESULT` |
| KOPIS 기본 UA | HTTP 400 HTML "Request Blocked" | `UPSTREAM_ERROR` (UA 지정으로 예방) |
| KOPIS 120일 범위 | 정상 응답 (기간 제한 오류 없음) | — |
| 카카오 잘못된 키 | HTTP 401 `AccessDeniedError` | `AUTH_FAILED` |
| 카카오 잘못된 입력 | HTTP 400 `Invalid Parameter (x)` | `INVALID_INPUT` |
| 카카오 결과 0건 | HTTP 200 `total_count: 0` | `NO_RESULT` |

## 3. 도구 연결 확인

| # | 항목 | 결과 | 비고 |
|---|---|---|---|
| C1 | LLM 1회 호출 | ✅ | **개인 OpenAI 키**, `gpt-4.1-mini`, base_url 기본값 |
| C2 | Tool 명세 전달 시 Tool 호출 선택 | ✅ | 공연 요청 → `search_performances` 선택, 인사 → Tool 미선택 |
| C3 | 고정 버전 라이브러리 설치 | ✅ | Python 3.13.7 venv, 17종 명세 버전 일치, `pip check` 통과 (기본 python 3.9는 사용 불가) |

## 4. 설계 시험

| # | 항목 | 결과 | 비고 |
|---|---|---|---|
| D1 | S1을 단계·Tool 순서대로 따라가며 모든 Tool 입력이 채워지는지 | ✅ | 목록 `mt20id` → 상세 → `mt10id` → 시설 좌표 → 카카오 주변 식당까지 끊김 없이 연결. 15건 중 11건 충족 |
| D2 | S2/S3로 재계획 조건·상한 동작 가능성 | ✅ | 아래 4.1 |
| P1 | 파서 설계용 텍스트 패턴 수집 | ✅ | 상세 73건: 회차·러닝타임·가격 해석 실패 0/73. fixture `samples/kopis_detail_pool.json` |

### 4.1 설계 시험 결과 (`scripts/validation/design_trial.py`, LLM 없이 규칙만으로 재현)

| 시나리오 | 조건 | 재계획 경과 (전략: 후보/충족) | 결과 | 상세 호출 / 캐시 재사용 |
|---|---|---|---|---|
| S1 | 토 14시 이후, 18시 전 종료, 5만원↓, 종로 연극 | initial 15/11 | `ok`, 재계획 0 | 15 / 0 |
| S2 | 일 19시 이후, 21시 전 종료, 3만원↓, 종로 뮤지컬 | initial 15/0 → expand_pool 15/0 → **drop_genre 15/1** | `ok`, 재계획 2 | 32 / 13 |
| S3 | 수 9시 이후, 11시 전 종료, 종로 연극 | initial 15/0 → expand_pool 15/0 → drop_genre 7/0 → widen_region 9/0 | **`limit_reached`**, 재계획 3 | 26 / 20 |
| S1 재실행 | S1과 동일 | initial 15/11 | `ok` | **0 / 15** |

- S2 제외 사유는 대부분 `OVER_BUDGET` (뮤지컬 4~7만원), S3은 `TIME_MISMATCH`·`NO_SHOW_ON_DAY` → 제외 사유 코드가 실제로 구분되어 나온다.
- 전체 87회 KOPIS 호출, 세션 재사용 시 응답 p50 0.11초 / p90 0.14초 / 최대 3.9초, 시나리오 3종 + 재실행 합계 23초.

## 5. 검증에 따른 설계 변경

| 일시 | 발견 | 변경 내용 | 반영 문서 |
|---|---|---|---|
| 11-22 | KOPIS WAF가 python-requests 기본 User-Agent 차단 (400 Request Blocked) | 모든 KOPIS 호출에 **자체 식별 UA** `ai-planner/0.1 (SSAFY AI core project)` 지정 (브라우저 위장 안 함) | 02 Tool 정의서 |
| 11-22 | KOPIS 응답 헤더에 charset 없음 → 한글 깨짐 | 본문을 UTF-8로 강제 디코딩 | 02 |
| 11-22 | KOPIS는 XML만 응답, 오류도 HTTP 200 + `returncode` | Tool 내부에서 XML→dict 변환, `returncode` 로 실패 판별. Tool 출력은 JSON 공통 형식 | 02 |
| 11-22 | 날짜 형식 `YYYY.MM.DD` | Tool 출력에서 `YYYY-MM-DD` 로 정규화 | 02 |
| 11-22 | 개인 OpenAI 키 사용 결정 (GMS → OpenAI) | `.env` 의 `LLM_BASE_URL` 비움. 코드 변경 없음 | 00 결정 로그 |
| 11-22 | 연속 호출 시 KOPIS가 연결 끊음(ConnectionReset), 매 호출 새 연결이면 3~9초/건 | **`requests.Session` 연결 재사용** (p50 0.11초로 단축) | 02, 04 |
| 11-22 | 정상 UA로도 간헐적 `400 Request Blocked`(87회 중 3회) | KOPIS 호출 **최대 3회 백오프 재시도**(2s, 4s), 끝내 실패하면 `UPSTREAM_ERROR` | 02 |
| 11-22 | 부하 시 XML이 아닌 응답 → 파싱 예외로 스크립트 중단 | Tool 내부에서 파싱 예외도 실패 코드로 변환 (Tool은 예외를 던지지 않음 원칙 재확인) | 02 |
| 11-22 | S2 재계획이 `drop_genre`로 성공 → 사용자가 원한 뮤지컬이 아닌 공연 추천 | 응답에 **완화한 선호 조건을 반드시 명시** ("뮤지컬 조건을 풀어 찾았어요") | 04 |
| 11-22 | 회차 표기에 `HOL(...)`(공휴일), `00:00`(자정) 존재, 가격은 등급별 다수 | 파서: `HOL`은 공휴일 키로 분리, 최소 가격 사용. `00:00` 등 경계값은 L1 테스트 케이스로 | 02, 06 |
