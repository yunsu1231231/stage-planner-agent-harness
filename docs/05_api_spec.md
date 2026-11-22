# 05. API 명세서 (초안)

> 상태: **초안** — 구현 시 Pydantic 모델과 함께 확정하고, FastAPI 문서 화면(`/docs`)과 일치시킨다.
> Base: `http://localhost:8000` · 형식: JSON (UTF-8) · 시간대: Asia/Seoul

## 0. 공통

### 오류 응답
```json
{ "error": { "code": "PLAN_NOT_FOUND", "message": "계획을 찾을 수 없습니다." } }
```
- `message`는 사용자에게 보여도 되는 문장만. **API 키·스택트레이스·외부 API 원문은 넣지 않는다** (NF3002). 상세는 서버 로그에만.

| HTTP | 용도 |
|---|---|
| 200 / 201 / 204 | 성공 / 생성 / 삭제 |
| 400 | 형식은 맞지만 값이 잘못됨 (예: 종료 < 시작) |
| 404 | 대상 없음 |
| 405 | 허용하지 않는 메서드 (실행 로그 수정 시도 등) |
| 422 | 스키마 검증 실패 (FastAPI 기본) |
| 503 | 필수 설정 누락 (`CONFIG_MISSING`) |

## 1. 상태 / 설정

### `GET /api/health`
키 값은 절대 반환하지 않고 **설정 여부만** 반환한다. 프론트는 이것으로 키 누락 안내를 띄운다 (F3019).
```json
{ "status": "ok", "config": { "llm": true, "kopis": true, "kakao": false } }
```

### `GET /api/tools`
등록된 Tool 목록 (명세 4.1 검증용).
```json
{ "tools": [ { "name": "search_performances", "kind": "external", "description": "…", "input_schema": { } } ] }
```

## 2. 대화 (F3017, F3005~F3011, F3019)

### `POST /api/chat`
**Request**
```json
{ "session_id": "s-3f2a…", "message": "토요일 2시 이후 대학로에서 5만원 이하 연극, 6시 전에 끝나야 해" }
```
- `session_id` 생략 시 서버가 새로 발급하여 응답에 포함.

**Response 200**
```json
{
  "session_id": "s-3f2a…",
  "run_id": "r-91c0…",
  "status": "ok",
  "reply": "조건에 맞는 연극 2편을 찾았어요 …",
  "intent": { "value": "plan_performance", "reason": "날짜·시간·지역 조건과 함께 공연 추천을 요청" },
  "conditions": {
    "date": { "value": "2026-11-28", "source": "user" },
    "earliest_start": { "value": "14:00", "source": "user" },
    "region": { "value": "종로구", "source": "user" },
    "genre": { "value": "연극", "source": "user" },
    "end_by": { "value": "18:00", "source": "user" },
    "budget_max": { "value": 50000, "source": "user" },
    "age": null
  },
  "recommendations": [
    {
      "rank": 1, "performance_id": "PF307123", "title": "…", "venue_name": "…",
      "date": "2026-11-28", "start_time": "15:00", "end_time": "16:10",
      "runtime_min": 70, "min_price": 30000, "age_limit": "만 12세 이상",
      "criteria": "15:00 시작 + 70분 = 16:10 종료 ≤ 18:00, 30,000원 ≤ 50,000원",
      "evidence": ["t2:get_performance_detail(PF307123)"],
      "places": [ { "name": "…", "address": "…", "distance_m": 40, "url": "http://place.map.kakao.com/…" } ]
    }
  ],
  "excluded": [
    { "performance_id": "PF300001", "title": "…", "reason_code": "END_TOO_LATE", "reason": "17:00 시작 + 100분 = 18:40 종료 > 18:00" },
    { "performance_id": "PF300002", "title": "…", "reason_code": "NO_RUNTIME", "reason": "러닝타임 정보가 없어 판단하지 않았습니다" }
  ],
  "notices": [ { "type": "estimated", "message": "…" } ],
  "replan_count": 0,
  "timeline": [
    { "seq": 1, "type": "node.enter", "node": "analyze", "ts": "…" },
    { "seq": 4, "type": "tool.response", "node": "execute", "tool": "search_performances", "ok": true, "duration_ms": 412 },
    { "seq": 20, "type": "replan", "count": 1, "strategy": "expand_pool" }
  ],
  "error": null
}
```

| `status` | 의미 | 화면 |
|---|---|---|
| `ok` | 추천 1건 이상 | 추천 카드 + 타임라인 |
| `clarify` | 조건 부족으로 되묻기 | 질문 강조 |
| `no_match` | 재계획 후에도 0건 (상한 미도달 종료) | 제외 사유 |
| `limit_reached` | 재계획 상한 도달 | 사유 + 조건 조정 제안 |
| `saved` | `confirm_plan`으로 계획 저장 | 저장 결과 + 겹침 알림 |
| `config_missing` | API 키 누락 | 설정 안내 (어떤 키인지만) |
| `partial` | 일부 Tool 실패했지만 응답 생성 | 실패 Tool 안내 |
| `chat` | Tool 불필요 대화 | 일반 답변 |

- 에이전트 내부 오류도 **HTTP 200 + `status`/`error`** 로 돌려준다 (서비스 중단 금지, NF3003).
- `timeline`은 이번 run의 이벤트 요약. 전체 원본은 `/api/logs`.

### `DELETE /api/chat/sessions/{session_id}`
대화 맥락 초기화. **204**. (실행 로그는 지우지 않는다)

## 3. 계획 관리 (F3015, F3016)

### Plan 객체
```json
{
  "id": 7,
  "performance_id": "PF307123",
  "title": "…",
  "venue_name": "…",
  "date": "2026-11-28",
  "start_time": "15:00",
  "end_time": "16:10",
  "price": 30000,
  "memo": "끝나고 근처 식당",
  "source_session_id": "s-3f2a…",
  "created_at": "2026-11-22T18:10:00+09:00",
  "updated_at": "2026-11-22T18:10:00+09:00"
}
```
- 필수: `title`, `date`, `start_time`, `end_time`. 검증: `end_time > start_time`.

### `POST /api/plans` → **201**
**Request**: Plan 객체에서 `id`, `created_at`, `updated_at` 제외
**Response**
```json
{ "plan": { "...": "Plan" }, "overlaps": [ { "id": 3, "title": "…", "start_time": "15:30", "end_time": "17:00" } ] }
```
- **겹침 규칙**: 같은 `date`이고 `[start, end)` 구간이 교차하면 겹침. **저장은 막지 않고** `overlaps`로 알린다.

### `GET /api/plans?date=YYYY-MM-DD`
```json
{ "plans": [ { "...": "Plan" } ], "total": 3 }
```
정렬: `date`, `start_time` 오름차순. `date` 생략 시 전체.

### `GET /api/plans/{id}` → Plan · 없으면 404 `PLAN_NOT_FOUND`

### `PATCH /api/plans/{id}`
변경할 필드만 전송 (`date`, `start_time`, `end_time`, `memo`, `title`, `price`).
```json
{ "plan": { "...": "Plan" }, "overlaps": [ ] }
```
수정 후에도 겹침을 다시 검사하여 알린다 (자기 자신 제외).

### `DELETE /api/plans/{id}` → **204**

## 4. 실행 로그 (F3014) — 조회·삭제만, 수정 API 없음

### `GET /api/logs`
세션 단위 목록 (최근 순).
```json
{
  "sessions": [
    {
      "session_id": "s-3f2a…",
      "first_at": "…", "last_at": "…",
      "run_count": 3, "event_count": 84,
      "replan_total": 1, "error_count": 0, "tool_failure_count": 1
    }
  ]
}
```

### `GET /api/logs/{session_id}?run_id=`
실행 순서(`seq`)대로 원본 이벤트.
```json
{ "session_id": "s-3f2a…", "events": [ { "event_id": "…", "run_id": "…", "seq": 1, "ts": "…", "type": "run.start", "node": null, "payload": { } } ] }
```

### `DELETE /api/logs/{session_id}` → **204**

- `PUT` / `PATCH /api/logs/...` 는 **정의하지 않는다** → 405 (명세 4.3 검증 항목).

## 5. 저장 구조 (SQLite)

```sql
CREATE TABLE plans (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  performance_id TEXT,
  title TEXT NOT NULL,
  venue_name TEXT,
  date TEXT NOT NULL,          -- YYYY-MM-DD
  start_time TEXT NOT NULL,    -- HH:MM
  end_time TEXT NOT NULL,
  price INTEGER,
  memo TEXT,
  source_session_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX idx_plans_date ON plans(date);

CREATE TABLE execution_events (      -- append-only (UPDATE 경로 없음)
  event_id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  ts TEXT NOT NULL,
  type TEXT NOT NULL,
  node TEXT,
  payload TEXT NOT NULL            -- JSON
);
CREATE INDEX idx_events_session ON execution_events(session_id, run_id, seq);
```

## 6. 화면 구성 (F3018, F3019)

| 화면 | 구성 | 호출 API |
|---|---|---|
| 대화 `index.html` | 대화창 / 추천 카드(저장 버튼) / 실행 타임라인 패널(단계·Tool·재계획 구분 색) / 처리 중 표시 / 키 누락 배너 | `/api/health`, `/api/chat`, `/api/plans` |
| 계획 관리 `plans.html` | 날짜별 목록, 상세, 인라인 수정, 삭제, 겹침 경고 | `/api/plans*` |
| 실행 로그 `logs.html` | 세션 목록 → 이벤트 타임라인, 삭제 | `/api/logs*` |
