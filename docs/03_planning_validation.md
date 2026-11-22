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
| T4 | 출처별 호출 한도·약관 | ☐ | KOPIS·카카오 이용약관/쿼터 페이지 확인 필요 (NF3007) |

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
| D1 | S1을 단계·Tool 순서대로 따라가며 모든 Tool 입력이 채워지는지 | ☐ | Agent 설계 후 수행 |
| D2 | S2/S3로 재계획 조건·상한 동작 가능성 | ☐ | |

## 5. 검증에 따른 설계 변경

| 일시 | 발견 | 변경 내용 | 반영 문서 |
|---|---|---|---|
| 11-22 | KOPIS WAF가 python-requests 기본 User-Agent 차단 (400 Request Blocked) | 모든 KOPIS 호출에 **자체 식별 UA** `ai-planner/0.1 (SSAFY AI core project)` 지정 (브라우저 위장 안 함) | 02 Tool 정의서 |
| 11-22 | KOPIS 응답 헤더에 charset 없음 → 한글 깨짐 | 본문을 UTF-8로 강제 디코딩 | 02 |
| 11-22 | KOPIS는 XML만 응답, 오류도 HTTP 200 + `returncode` | Tool 내부에서 XML→dict 변환, `returncode` 로 실패 판별. Tool 출력은 JSON 공통 형식 | 02 |
| 11-22 | 날짜 형식 `YYYY.MM.DD` | Tool 출력에서 `YYYY-MM-DD` 로 정규화 | 02 |
| 11-22 | 개인 OpenAI 키 사용 결정 (GMS → OpenAI) | `.env` 의 `LLM_BASE_URL` 비움. 코드 변경 없음 | 00 결정 로그 |
