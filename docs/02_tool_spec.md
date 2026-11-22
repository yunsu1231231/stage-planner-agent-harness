# 02. Tool 정의서 (초안)

> 상태: **초안** — 실제 API 응답을 확인한 뒤 필드명·실패 코드를 확정한다.

## 1. 공통 응답 형식

모든 Tool은 예외를 밖으로 던지지 않고 아래 형식으로 반환한다.

```json
// 성공
{ "ok": true,  "data": { ... }, "meta": { "source": "KOPIS", "estimated": false, "note": null } }
// 실패
{ "ok": false, "error": { "code": "NO_RESULT", "message": "사용자용 짧은 설명", "retryable": true } }
```

- `meta.estimated`: 요청 기준과 실제 조회 기준이 다를 때 `true` + `note`에 사유 (F3002)
- `error.retryable`: 인자를 고치면 결과가 달라질 수 있는 실패인지 (F3021 Worker 판단 기준)

## 2. 실패 코드

| 코드 | 의미 | retryable | 처리 |
|---|---|---|---|
| `MISSING_API_KEY` | 환경변수 키 없음 | false | 재계획 없이 즉시 설정 안내 |
| `AUTH_FAILED` | 키 무효 | false | 즉시 안내 |
| `INVALID_INPUT` | 입력 스키마 위반 | true | Worker 인자 수정 가능 |
| `NO_RESULT` | 결과 0건 | true | 재계획/인자 수정 후보 |
| `NOT_FOUND` | ID 대상 없음 | true | 해당 후보 제외 |
| `NO_RUNTIME` | 러닝타임 비어 있음 | false | 판단하지 않고 제외 + 사유 |
| `NO_SCHEDULE` | 회차 시각 없음/파싱 불가 | false | 시각 지어내지 않음, 역산 기준만 제시 |
| `NO_PRICE` | 가격 정보 없음 | false | 예산 판단 "확인 불가" 표시 |
| `UPSTREAM_ERROR` | 외부 API 5xx/파싱 실패 | false | 사유 기록 후 진행 |
| `TIMEOUT` | 시간 초과 | false | 사유 기록 후 진행 |
| `RATE_LIMITED` | 호출 한도 초과 | false | 즉시 안내 |
| `UNKNOWN_TOOL` | 등록되지 않은 Tool 이름 | false | 계획 보정 (plan.corrected) |

## 3. Tool 목록

### 3.1 외부 API 툴 (필수)

#### `search_performances` — F3002 후보 조회
- **설명(LLM용)**: "사용자가 볼 공연을 아직 정하지 않았을 때, 날짜·지역·장르 조건으로 후보 공연 목록을 찾을 때 사용한다."
- **입력**: `start_date`(YYYY-MM-DD, 기본 오늘), `end_date`(기본 start_date), `region_code`(시도/구 코드, 선택), `genre`(연극/뮤지컬/클래식 등, 선택), `limit`(기본 20)
- **출력 data**: `{ "query": {...실제 조회 기준}, "items": [ { "performance_id", "title", "venue_name", "start_date", "end_date", "genre", "state" } ] }`
- **다음 Tool로 전달**: `performance_id` → `get_performance_detail`
- **실패**: `NO_RESULT`, `INVALID_INPUT`, `MISSING_API_KEY`, `UPSTREAM_ERROR`

#### `get_performance_detail` — F3003 상세정보 조회
- **설명(LLM용)**: "후보 공연의 러닝타임·공연 시각·가격을 확인해 시간과 예산 조건을 판단해야 할 때 사용한다."
- **입력**: `performance_id`
- **출력 data**: `{ "performance_id", "title", "runtime_min"(int|null), "schedule_raw", "schedule": [ {"weekday", "times": ["HH:MM"]} ], "price_raw", "min_price"(int|null), "age_limit", "venue_id", "venue_name" }`
- **원칙**: 파싱 못 한 값은 `null` + 해당 실패 코드. 값을 추정해 채우지 않는다.
- **다음 Tool로 전달**: `venue_id` → 시설 좌표 조회 (Tool 아님, 실행 흐름 내부 호출 여부 검증 시 결정)

#### `search_nearby_places` — F3004 보조 정보 검색
- **설명(LLM용)**: "추천할 공연장 주변에서 식사·카페·주차할 곳을 함께 안내해야 할 때 사용한다."
- **입력**: `venue_name` 또는 `x`,`y`(경도·위도), `category`(restaurant|cafe|parking), `radius_m`(기본 500)
- **출력 data**: `{ "places": [ { "name", "address", "distance_m", "url", "phone" } ] }`
- **원칙**: 장소와 공연을 임의로 엮지 않는다(어느 공연장 기준인지만 명시).
- **실패**: `NO_RESULT`, `MISSING_API_KEY`, `UPSTREAM_ERROR`

### 3.2 로컬 서버 API 툴
- 이번 범위에서 선택한 심화(F3020, F3021)는 Tool 추가가 필요 없음 → 로컬 서버 API 툴은 **구분 구조만 정의**하고 구현 대상 없음.
- 계획 저장은 사용자가 정한 값을 다루므로 Tool로 두지 않는다 (명세 2.3).

## 4. Tool로 두지 않는 작업 (실행 흐름이 직접 수행)
- 종료 시각 계산, 제약 비교, 겹침 검사 → 결정적 계산
- 계획 저장/수정/삭제 → 사용자 확정 값
- 회차 시각·가격 텍스트 파싱 → Tool 내부 정규화

## 5. 등록 및 확장 방법 (M1 확정)

```python
registry = ToolRegistry()
registry.register(ToolSpec(
    name="search_performances", kind="external",            # external | local
    description="…언제 쓰는지…", input_model=SearchInput,    # Pydantic 입력 스키마
    func=kopis.search_performances,                          # (input) -> ToolResult
))
registry.list_specs()          # [{name, kind, description, input_schema}]  ← Agent·/api/tools 에 노출
registry.call(name, args)      # 스키마 검증 → 실행 → ToolResult. 어떤 경우에도 예외를 던지지 않음
registry.as_langchain_tools()  # LLM bind_tools 용 (이름·설명·입력 스키마만 전달)
```
- 새 Tool 추가 = 입력 모델 + `(input) -> ToolResult` 함수 + `register()` 한 줄. 외부 의존(HTTP 세션, 키, 시계)은 생성자 주입 → 테스트에서 FakeSession 으로 교체.
- 레지스트리 단계 실패 코드: 없는 Tool → `UNKNOWN_TOOL`, 입력 검증 실패 → `INVALID_INPUT`, Tool 내부 예외 → `UPSTREAM_ERROR` (예외 메시지는 사용자에게 노출하지 않고 로그용 `detail`에만).

### 5.1 Tool별 확정 규칙
**`search_performances`**
- `date` 생략 → **오늘(KST)**, `meta.defaults = ["date"]`
- `date`가 과거 → 오늘로 보정하고 `meta.estimated = true`, `meta.note`에 "요청 2026-11-01 → 조회 2026-11-22" (F3002 추정 명시)
- 공연 상태 필터(`prfstate`)는 쓰지 않는다. 미래 날짜에 개막하는 `공연예정`이 빠지기 때문. 응답에서 `공연완료`만 제외
- `region`은 이름으로 받는다 ("대학로", "종로구", "서울", "강남") → 시도/구 코드 매핑. 모르는 이름 → `INVALID_INPUT` (임의 추정 금지)
- `genre`도 이름 ("연극", "뮤지컬", "클래식" …) → KOPIS 장르 코드. 모르는 이름 → `INVALID_INPUT`
- `limit` 기본 20, 최대 50

**`get_performance_detail`**
- 러닝타임 해석 불가 → `ok=false, NO_RUNTIME` (판단에서 제외, `error.partial`에 제목·공연장만)
- 회차·가격 해석 불가 → `ok=true`, 해당 필드 `null` + `meta.missing = ["schedule" | "price"]` (판단 단계에서 `unjudgeable`/"확인 불가" 처리)
- 출력 `schedule`: `{"월요일": ["19:30"], …, "HOL": [...]}`

**`search_nearby_places`**
- 입력은 `venue_id`(KOPIS 공연장 ID) **또는** `x`,`y`(경도·위도) 중 하나. `venue_id`면 KOPIS 공연시설상세로 좌표를 구한 뒤 카카오 검색 (상세 Tool의 `venue_id`가 그대로 입력이 됨)
- `category`: `restaurant`(FD6) | `cafe`(CE7) | `parking`(PK6), `radius_m` 기본 500(최대 2000), `size` 기본 5
- 좌표 없음 → `NOT_FOUND`, 결과 0건 → `NO_RESULT`
- 출력에 `basis`(어느 공연장·좌표 기준인지) 포함 — 장소와 공연을 임의로 엮지 않음

## 6. 외부 API 호출 규약 (기획 검증 결과 반영, `03_planning_validation.md` 5절)

### 6.1 KOPIS
- Base URL: `https://www.kopis.or.kr/openApi/restful` — 목록 `pblprfr`, 상세 `pblprfr/{mt20id}`, 시설 `prfplc/{mt10id}`, 키는 `service` 파라미터
- **User-Agent 필수**: `ai-planner/0.1 (SSAFY AI core project)` (기본 UA는 WAF가 400 차단, 브라우저 위장 금지)
- **연결 재사용 필수**: `requests.Session` 하나를 공유 (매 호출 새 연결이면 연결 끊김·3~9초 지연)
- **재시도**: 연결 오류·타임아웃·`400 Request Blocked`(HTML)·XML 파싱 실패 → 최대 3회, 2s/4s 백오프. 끝내 실패하면 `UPSTREAM_ERROR`
- **파서**: 러닝타임 "N시간 M분"→분, 가격은 등급별 금액 중 **최솟값**("무료"→0), 회차는 `요일 ~ 요일(HH:MM,...)` / `요일(...)` / `HOL(...)` 구간 단위로 해석. 해석 못 한 구간은 버리고 전체가 비면 `NO_SCHEDULE`
- **XML 전용 응답** → Tool 내부에서 dict로 변환, 본문은 **UTF-8로 강제 디코딩** (헤더 charset 없음)
- 날짜 입력 `YYYYMMDD`, 응답 `YYYY.MM.DD` → Tool 출력은 `YYYY-MM-DD`
- **오류도 HTTP 200**: `returncode`로 판별

| KOPIS 응답 | 실패 코드 |
|---|---|
| `returncode 02` (SERVICE KEY IS NOT REGISTERED) | `AUTH_FAILED` |
| `returncode 04` (NODATA) | `NOT_FOUND` (상세/시설), `NO_RESULT` (목록) |
| 빈 `<dbs/>` | `NO_RESULT` |
| HTTP 4xx/5xx, XML 파싱 실패 | `UPSTREAM_ERROR` |

### 6.2 카카오 로컬
- `https://dapi.kakao.com/v2/local/search/{category|keyword}.json`, 헤더 `Authorization: KakaoAK {key}`
- 카테고리 코드: 식당 `FD6`, 카페 `CE7`, 주차장 `PK6`

| 카카오 응답 | 실패 코드 |
|---|---|
| HTTP 401 | `AUTH_FAILED` |
| HTTP 400 (`Invalid Parameter`) | `INVALID_INPUT` |
| HTTP 200 + `meta.total_count == 0` | `NO_RESULT` |
| HTTP 429 | `RATE_LIMITED` |

### 6.3 미확정
- [ ] 호출 한도·약관 (T4, NF3007)
- [x] 지역 코드·장르 코드 표 → `backend/app/tools/codes.py`. 실호출 확인: 서울 11, 부산 26, 종로 1111, 마포 1144, 서초 1165, 강남 1168, 연극 AAAA, 뮤지컬 GGGA, 클래식 CCCA
- [ ] `dtguidance` 패턴 다양성 (예: "화요일 ~ 금요일(19:30), 토요일(14:00,18:00)", "HOL(...)") — 파서 테스트 fixture 수집
