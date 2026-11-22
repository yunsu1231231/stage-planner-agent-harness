# 04. Agent 설계 문서 (초안)

> 상태: **초안** — 설계 시험(03 문서 4절 D1·D2) 후 확정한다.
> 설계 원칙: **결정적인 일(계산·저장·판정·순서 정렬)은 코드가, 판단이 필요한 일(조건 추출·Tool 선택·응답 문장화)만 LLM이** 한다. 모든 LLM 판단은 이유와 함께 이벤트로 남긴다.

## 1. 전체 구조

```
[Frontend] ──HTTP──▶ [FastAPI]
                       │
                       ├─ /api/chat ──▶ ChatService ──▶ Main Agent (LangGraph)
                       │                    │                │  ├─ ToolRegistry ─▶ KOPIS / Kakao
                       │                    │                │  └─ publish(event)
                       │                    │                ▼
                       │                    │           EventBus ──(subscribe)──▶ Logging Agent ──▶ SQLite execution_events
                       │                    └─ SessionMemory
                       ├─ /api/plans ──▶ PlanRepository ──▶ SQLite plans
                       └─ /api/logs  ──▶ LogRepository  ──▶ SQLite execution_events (읽기·삭제만)
```

| 구성요소 | 책임 | LLM |
|---|---|---|
| Main Agent | 분석 → 계획 → 실행 → 판단 → 응답 | 분석·계획·응답에서 사용 |
| ToolRegistry | Tool 등록, 스키마 제공, 호출, 공통 응답 보장 | X |
| EventBus | 동기 in-process pub/sub. 구독자 예외는 삼키고 발행자에게 전파하지 않음 | X |
| Logging Agent | 이벤트 구독 → 세션 단위 순서대로 저장 | **X (금지)** |
| SessionMemory | 세션별 조건 슬롯·직전 추천 요약 보관 | X |
| PlanRepository | 계획 CRUD, 겹침 검사 | X |

## 2. LangGraph 그래프

```
START → analyze ─┬─(chitchat)──────────────────────────────▶ respond → END
                 ├─(clarify: 필수 조건 부족)────────────────▶ respond
                 ├─(confirm_plan: 저장 요청)─────────────────▶ respond   ※ 저장은 실행 흐름이 직접 수행
                 └─(plan_performance / fact_query / modify) ▶ plan → execute → judge ─┬─(충족 후보 있음)──▶ execute[enrich] → respond
                                                                    ▲                  ├─(0개 & 재계획 가능)─▶ plan (replan)
                                                                    └──────────────────┘  └─(상한·치명적 실패)──▶ respond
```

- 명세 4.2의 `분석 → 계획 → 실행 → 판단 → 응답` 노드를 그대로 둔다.
- `execute`는 두 단계(`collect`: 후보·상세 수집 / `enrich`: 추천 공연장 좌표·주변 장소)로 나눠 같은 노드에서 수행한다. 주변 장소는 **추천이 확정된 공연장에만** 조회하여 호출 수를 줄인다.

## 3. 상태 (단계 사이에 전달하는 값)

```python
class PlannerState(TypedDict):
    session_id: str
    run_id: str
    user_message: str
    today: str                      # YYYY-MM-DD (상대 날짜 해석 기준)
    # analyze
    intent: Literal["plan_performance", "fact_query", "modify_condition", "confirm_plan", "chitchat"]
    intent_reason: str
    conditions: Conditions          # 아래 3.1
    missing: list[str]              # 되물을 항목
    # plan
    tasks: list[Task]               # 아래 3.2
    plan_version: int               # 0 = 최초, 1~3 = 재계획 회차
    # execute
    tool_cache: dict[str, ToolResult]   # key = tool_name + 정규화 args (재계획 시 재사용, F3009)
    tool_failures: list[ToolFailure]
    candidates: list[Candidate]
    # judge
    evaluations: list[Evaluation]   # eligible / excluded(사유) / unjudgeable(사유)
    replan_reasons: list[str]
    stop_reason: str | None         # "limit_reached" | "fatal:<code>" | None
    # respond
    reply: str
    payload: ResponsePayload        # 화면 표시용 구조화 결과 (05 문서)
```

### 3.1 조건 (F3005)

| 구분 | 필드 | 예 | 비고 |
|---|---|---|---|
| 기준 | `date` | 2026-11-28 | "토요일" → LLM이 today 기준으로 해석, 코드가 형식 검증 |
| 기준 | `earliest_start` | 14:00 | "2시 이후" |
| 선호 | `region` | 종로구(대학로) | 시/구 코드로 매핑 |
| 선호 | `genre` | 연극 | KOPIS 장르 코드 매핑 |
| 제약 | `end_by` | 18:00 | "6시 전에 끝나야" |
| 제약 | `budget_max` | 50000 | "5만원 이하" |
| 제약 | `age` | 12 | "12살 아이랑" (선택) |

- 추출되지 않은 값은 `null`. **임의로 채우지 않는다.**
- 각 필드에 `source: "user" | "memory"` 를 붙여 어떤 값이 이번 발화에서 왔는지 추적한다.

### 3.2 작업 (Task)

```python
class Task(TypedDict):
    id: str                 # "t1"
    tool: str               # "search_performances"
    args: dict              # 실행 시점에 확정
    fixed_args: list[str]   # 사용자 조건으로 고정한 인자 (재계획·F3021 Worker가 바꾸지 못함)
    depends_on: list[str]   # 앞선 Task 결과를 입력으로 쓰는 경우
    phase: Literal["collect", "enrich"]
    status: Literal["pending", "done", "failed", "skipped", "cached"]
```

## 4. 노드별 입출력과 LLM 사용

### 4.1 analyze (F3005, F3010)
- **입력**: `user_message`, `today`, SessionMemory(직전 조건·추천 요약·최근 대화 6턴)
- **LLM 1회** (structured output): `{intent, intent_reason, conditions_delta}`
- **코드**:
  1. `conditions = merge(memory.conditions, conditions_delta)` — 새로 말한 값만 덮어씀
  2. 날짜·시각 형식 검증. 과거 날짜 등 비정상 값은 `missing`으로 이동
  3. **되묻기 규칙**: 계획 의도인데 `date` 없음, 또는 `end_by`만 있고 `earliest_start`도 없음 → `clarify` (Tool 호출 전 되묻기, S6)
- **이벤트**: `node.enter/exit`, `llm.decision {decision: intent, reason}`

### 4.2 plan (F3006, F3009)
- **최초 계획**: LLM에 Tool 명세(이름·설명·입력 스키마)를 `bind_tools`로 넘겨 **필요한 Tool을 고르게 한다 (LLM 1회)**. 코드는 선택 결과를 검증·정렬하여 `tasks`를 만든다.
  - 불필요한 Tool은 계획에서 제외 (예: 지역·식사 언급이 없으면 `search_nearby_places` 제외)
  - 선택 이유를 `llm.decision` 이벤트로 남긴다.
  - LLM이 등록되지 않은 Tool·잘못된 순서를 내면 코드가 바로잡고 `plan.corrected` 이벤트를 남긴다.
- **재계획 (LLM 없음, 규칙)**: 사용자 제약(날짜·시각·종료·예산·연령)은 고정하고, **선호 조건만 단계적으로 완화**한다.

| 회차 | 전략 | 예 |
|---|---|---|
| 1 | 후보 풀 확장 (다음 페이지 / rows 증가) | 20건 → 40건 |
| 2 | 장르 선호 해제 | 연극 → 전체 장르 |
| 3 | 지역 확대 | 종로구 → 서울 전체 |

- 이미 조회한 상세정보는 `tool_cache`에서 재사용하여 **다시 호출하지 않는다**.
- 각 단계에서 이전 단계에 본 후보는 제외하고 **새 후보만** 상세 조회한다.
- 설계 시험 결과: S2는 2회차(`drop_genre`)에서 충족, S3는 3회차 후 `limit_reached`, 같은 조건 재실행 시 상세 호출 0회 (03 문서 4.1).

### 4.3 execute (F3007)
- `tasks`를 순서대로 실행. `depends_on` 결과에서 입력을 채운다 (목록 `performance_id` → 상세, 상세 `venue_id` → 시설 좌표 → 주변 장소).
- 상세 조회는 후보 최대 **15건**까지 (NF3005 응답 시간).
- 실패는 `tool_failures`에 사유를 남기고 다음 Task로 진행. 단, `MISSING_API_KEY`·`AUTH_FAILED`·`RATE_LIMITED`는 **치명적 실패**로 `stop_reason` 설정 → 재계획 없이 안내.
- **LLM 없음.**
- **이벤트**: Tool마다 `tool.request {tool, args}` / `tool.response {ok, error_code, duration_ms, summary}`

### 4.4 judge (F3008) — LLM 없음, 계산식

후보 공연 × 해당 요일 회차마다:

```
weekday_ok   = date ∈ [공연 시작일, 공연 종료일] and 해당 요일 회차 존재
start        = 회차 시작 시각
end          = start + runtime_min
time_ok      = (earliest_start is None or start ≥ earliest_start) and (end_by is None or end ≤ end_by)
budget_ok    = budget_max is None or min_price ≤ budget_max
age_ok       = age is None or age ≥ 관람 연령
eligible     = weekday_ok and time_ok and budget_ok and age_ok
```

| 결과 | 조건 | 응답에 표시 |
|---|---|---|
| eligible | 모두 충족 | 회차·종료 예정·가격 |
| excluded | 하나라도 불충족 | 사유 (예: "종료 18:40 > 제한 18:00") |
| unjudgeable | `NO_RUNTIME` / `NO_SCHEDULE` 등 | 사유 + **역산 기준** (예: 회차 미상 → "18시 종료하려면 늦어도 16:20 시작 회차") |

- **재계획 조건**: eligible 0개 **그리고** 치명적 실패 아님 **그리고** `plan_version < 3`
- **재계획하지 않음**: 치명적 실패, 되묻기, Tool 불필요 요청, 상한 도달 → `stop_reason` 기록 후 respond
- 상한 도달 시 가장 근접한 후보를 근거로 **조건 조정 제안** (예: "종료 제한을 18:30으로 늦추면 2편 가능")
- **이벤트**: `judge.result {eligible, excluded, unjudgeable}`, 재계획 시 `replan {count, reason, strategy}`

### 4.5 respond (F3011)
- **입력**: 구조화된 판단 결과(eligible·excluded·unjudgeable·places·notices)
- **LLM 1회**: 구조화 결과를 자연어로 정리. **입력에 없는 사실을 추가하지 않도록** 프롬프트에서 제한하고, 수치·이름은 `payload`에서 그대로 화면에 표시한다.
- LLM 실패 시 템플릿 문장으로 대체 (응답은 반드시 나간다, NF3003).
- 추정이 섞인 경우(`meta.estimated`) 안내 문구 포함.
- **재계획으로 선호 조건을 완화했다면 그 사실을 반드시 밝힌다** (예: "뮤지컬 중에는 없어 장르 조건을 풀어 찾은 연극입니다"). 설계 시험 S2에서 확인된 요구.

### 4.6 confirm_plan (F3015 연계)
- "1번으로 저장해줘" → analyze가 `confirm_plan` + 대상 인덱스 추출 → 코드가 **Memory의 직전 추천**에서 값을 읽어 PlanRepository에 저장. Tool이 아니다 (사용자가 이미 정한 값, 명세 2.3).
- 겹침이 있으면 저장 후 응답에 알린다.

### 4.6.1 M2 구현 확정 사항
- **되묻기 응답은 템플릿**(LLM 없음): 무엇이 빠졌는지가 규칙으로 정해지므로 결정적으로 만든다.
- **fact_query**: analyze가 `keyword`(공연명)를 추출 → `search_performances(keyword)` → 첫 결과 `get_performance_detail`. 판단 단계는 건너뛰고 사실만 답한다. 직전 추천 번호를 가리키면(`target_index`) Memory의 공연 ID로 상세만 조회. (이를 위해 `SearchInput.keyword` → KOPIS `shprfnm` 추가)
- **Tool 인자는 코드가 채운다**: LLM은 *어떤 Tool을 쓸지*만 고르고(F3006), 인자는 추출된 조건으로 코드가 만든다. LLM이 제안한 인자는 이벤트에만 기록 (값을 지어내지 못하게).
- **재계획 전략은 '적용 가능한 다음 단계'만 사용**: 장르 조건이 없으면 `drop_genre`를 건너뛰고, 이미 시·도 단위면 `widen_region`을 건너뛴다. 더 쓸 전략이 없으면 상한 전이라도 `no_match`로 끝낸다.
- **확정 저장(confirm_plan)**: 저장 함수는 주입(`save_plan`). M3에서 PlanRepository를 연결한다. 직전 추천이 없거나 번호가 범위를 벗어나면 되묻기.
- **이벤트 발행 지점은 M2에서 노드에 심는다**: 발행 함수(`publish`)는 주입. 구독자(로깅 Agent)는 M3. 발행 실패는 무시 (F3012 "발행은 구독자에 의존하지 않음").
- **LLM 실패 처리**: analyze 실패 → `status=error` 응답(중단 없음), plan 실패 → 규칙 기반 계획으로 대체 + `plan.corrected`, respond 실패 → 템플릿 문장.

### 4.7 요청당 LLM 호출 수 (기준선)

| 경로 | analyze | plan | respond | 합계 |
|---|---|---|---|---|
| 계획 요청 | 1 | 1 | 1 | **3** (재계획은 규칙이라 추가 0) |
| 인사·사용법 | 1 | 0 | 1 | 2 |
| 되묻기 | 1 | 0 | 0 (템플릿) | 1 |

→ F3021 비교 실험의 기준선으로 사용.

### 4.8 실측 (M2, 실제 LLM gpt-4.1-mini + 실제 API, S1 대표 요청 1회)
| 구간 | 시간 |
|---|---|
| 전체 | **15.9초** (LLM 3회, 재계획 0) |
| KOPIS 목록 1회 | 3.4초 |
| KOPIS 상세 15회 (세션 재사용) | 합계 2.0초 |
| 주변 장소 3회 (KOPIS 시설 + 카카오) | 합계 2.9초 |
| LLM 3회 (추정) | 약 7.6초 |
- 개선 여지(NF3005): 상세·주변 장소 조회 병렬화, respond 프롬프트 축소. 범위 동결 원칙상 필요 시 3일차에 판단.

## 5. 대화 맥락 (Memory, F3010)

| 보관 | 보관하지 않음 |
|---|---|
| 조건 슬롯 (3.1 전체, source 포함) | Tool 원본 응답 |
| 직전 추천 요약 (번호, 공연 ID, 제목, 공연장, 회차, 종료, 가격) | 실행 이벤트 (로그 저장소 담당) |
| 직전 의도 | API 키·오류 상세 |
| 최근 대화 6턴 (발화·응답 텍스트) | 제외·판단 불가 후보 상세 |

- 저장소: 프로세스 메모리 `dict[session_id → SessionMemory]` (서버 재시작 시 초기화, 범위 밖이면 문서에 명시).
- 갱신: analyze의 `conditions_delta` 중 non-null 값만 덮어씀. "조건 초기화" 발화나 `DELETE /api/chat/sessions/{id}` 시 리셋.

## 6. 실행 이벤트와 로깅 Agent (F3012~F3014)

### 6.1 이벤트 스키마

```json
{
  "event_id": "uuid",
  "session_id": "s-…", "run_id": "r-…", "seq": 12,
  "ts": "2026-11-22T18:00:00.123+09:00",
  "type": "tool.response",
  "node": "execute",
  "payload": { "tool": "get_performance_detail", "ok": false, "error_code": "NO_RUNTIME", "duration_ms": 231 }
}
```

| type | 발행 시점 | payload 핵심 |
|---|---|---|
| `run.start` / `run.end` | 요청 시작·종료 | message 요약 / status, 총 소요시간, LLM 호출 수 |
| `node.enter` / `node.exit` | 각 노드 진입·종료 | node, 요약 출력 |
| `llm.decision` | LLM이 흐름을 바꾸는 판단 | decision, reason, model |
| `plan.created` / `plan.corrected` | 작업 목록 생성·보정 | tasks, plan_version |
| `tool.request` / `tool.response` | Tool 호출 전후 | tool, args / ok, error_code, duration_ms, summary |
| `judge.result` | 판단 완료 | eligible/excluded/unjudgeable 개수와 사유 |
| `replan` | 재계획 결정 | count, reason, strategy |
| `error` | 처리 중 예외 | code (상세 메시지는 서버 로그에만) |

### 6.2 분리 원칙
- 발행자는 `bus.publish(event)`만 호출하고 **누가 구독하는지 모른다**. 구독자가 없어도 정상 동작 (검증: 로깅 Agent 미연결 실행).
- 로깅 Agent는 받은 이벤트를 **그대로** `execution_events` 테이블에 append. 요약·가공·LLM 호출 없음.
- 저장 실패는 로깅 Agent 내부에서 삼키고 대화는 계속된다.

## 7A. 심화 구현 확정 (M6)

### 7A.1 F3020 이상 징후 판단 — 로깅 Agent
- **판정은 규칙**(`agents/anomaly.py`, LLM 금지 구역). 실행(run) 단위로 이벤트를 대조·계수한다.

| 규칙 | 근거 이벤트 | 이상 조건 | 판정 불가 조건 |
|---|---|---|---|
| `repeated_call` | `tool.request` (cached=false) | 같은 Tool·같은 인자 실제 호출 ≥ 2 | Tool 이벤트 없음 → 해당 없음(정상) |
| `excessive_replan` | `replan` | 재계획 횟수 ≥ 상한(3) | — |
| `unplanned_call` | `plan.created` ↔ `tool.request` | 직전 작업 목록에 없는 Tool 호출 | Tool 호출은 있는데 `plan.created` 가 없음 |
| (전체) | `run.start`/`run.end` | — | 이벤트 없음, 종료 판정인데 `run.end` 없음 |
- 결과: `verdict` = `anomaly`(경고 ≥1) · `undeterminable`(경고 0 + 판정 불가 규칙 ≥1) · `normal`. **근거가 없으면 '이상 없음'이 아니라 '판정 불가'.**
- **진단은 이상 실행에만**: `run.end` 수신 시 판정 → `anomaly` 일 때만 주입된 진단 함수(`agents/log_diagnosis.py`, LLM)가 3문장 이내로 원인(어느 Agent 쪽 문제인지, 무엇을 고칠지)을 쓴다. 판정(`anomaly_reports`)과 진단(`anomaly_diagnoses`)은 **다른 테이블**에 저장 → 진단 실패해도 판정·로그 유지, 경고 수에 섞이지 않음.
- **메인 Agent 참조 형식**: `LoggingAgent.inspect(run_id)` 가 실행 중간에도 같은 형식의 보고서를 돌려준다 (F3021 검증 단계에서 사용). 저장된 보고서는 `GET /api/logs/{session_id}/anomalies`.

### 7A.2 F3021 Planner · Worker · 검증
- **Planner** = analyze · plan · judge 노드 (요청 분해, 작업 목록, 제약 판단, 재계획). **Worker** = execute 노드 (작업 목록대로 Tool 호출). **검증** = verify 노드가 로깅 Agent 의 `inspect` 를 호출.
- 그래프(Planner·Worker 모드): `analyze → plan → execute → verify → judge → respond` (+ judge → plan 재계획, judge → execute 보강, verify 이상 → plan 재구성 → judge)
- 기존 단일 구조(baseline)는 그대로 유지하고 `AGENT_MODE` 로 선택 → 구조 변경 전후 비교.

**주고받는 형식** (`agent.message` 이벤트로 실행 로그에 남김)
| 방향 | kind | body |
|---|---|---|
| Planner → Worker | `task_list` | `{plan_version, strategy, tasks:[{id, tool, args, fixed_args, phase}]}` |
| Worker → Planner | `work_result` | `{done, failed, retried, unresolved:[{task_id, tool, code, reason}], replan_requests:[...]}` |
| 로깅 Agent → Planner | `verification` | `{verdict, warnings}` |

**Worker 실패 처리 (규칙 우선, LLM 은 마지막)**
| 실패 | 처리 | LLM |
|---|---|---|
| 치명적 (`MISSING_API_KEY`·`AUTH_FAILED`·`RATE_LIMITED`) | 즉시 중단, Planner 에 보고 → 사용자 안내 | ✗ |
| 필수 인자 누락 (스키마 검증 `missing`) | 중단, Planner 에 보고 (되묻기 대상) | ✗ |
| 재시도 무의미 (`UPSTREAM_ERROR`·`TIMEOUT`·`NO_RUNTIME`) | 기록 후 건너뜀 | ✗ |
| 재시도 가능 (`NO_RESULT`·`NOT_FOUND`·`INVALID_INPUT`) + **고칠 수 있는 인자 없음** | 후보 검색이면 Planner 에 계획 변경 요청, 그 외 건너뜀 | ✗ |
| 재시도 가능 + 고칠 수 있는 인자 있음 + Worker LLM 켜짐 | LLM 이 `retry`(인자 수정) · `skip` · `replan_request` 중 선택 | ✓ |
- 고칠 수 있는 인자(Tool 별 허용 목록 − Planner 고정 인자): `search_performances.keyword`, `search_nearby_places.radius_m`·`size`. 날짜·지역·장르·공연 ID·공연장·장소 종류는 고정.
- LLM 결정 검증(규칙): 고정 인자 변경·허용 외 인자·이전과 같은 인자 → 거부하고 `skip`. 재시도는 **같은 Tool 로만, 작업당 2회**.
- Planner 반영: Worker 의 계획 변경 요청(예: 후보 검색 `NO_RESULT`)은 재계획 사유에 포함되고, 후보가 0건이면 의미 없는 `expand_pool` 을 건너뛴다.
- 검증 이상 → Planner 가 작업 목록을 재구성(`strategy=verified_rebuild`, Worker LLM 재시도 중단)하고 판단으로 진행. 실행당 1회.

**Agent 별 LLM 호출 조건**
| Agent | 호출하는 경우 | 호출하지 않는 경우 |
|---|---|---|
| Planner | 의도·조건 추출(analyze), Tool 선택(plan 최초), 응답 문장화(respond) | 재계획, 제약 판단, 작업 목록 재구성, 되묻기·키 누락 응답 |
| Worker | 재시도 가능한 실패 + 고칠 인자 있음 | 정상 경로(**0회**), 치명적 실패, 필수 인자 누락, 고칠 인자 없음, Worker LLM 꺼짐 |
| 로깅 Agent | `anomaly` 로 판정된 실행의 원인 진단 | 수집·저장, 규칙 판정, 정상·판정 불가 실행 |

## 7. 심화 구조 (초기 구상)

### 7.1 F3020 이상 징후 판단 (로깅 Agent)
| 규칙 | 판정 근거 이벤트 |
|---|---|
| 같은 Tool·같은 args 반복 호출 (≥2) | `tool.request` |
| 재계획 과다 (상한 도달) | `replan` |
| 계획에 없던 Tool 호출 | `plan.created` vs `tool.request` |
| 근거 이벤트 없음 | → **"판정 불가"** (이상 없음 아님) |
- 판정은 규칙, **경고가 있는 실행에만** LLM으로 원인 3문장 진단. 진단은 판정과 분리 저장.

### 7.2 F3021 Planner·Worker
- Planner = 현 analyze + plan, Worker = 현 execute. 작업 목록·수행 결과 형식은 3.2 `Task` 재사용.
- Worker LLM 호출 조건: `retryable=true` 실패(`NO_RESULT`, `NOT_FOUND`, `INVALID_INPUT`)일 때만 → {재시도(고정 인자 불변), 건너뜀, 계획 변경 요청}.
- 비교 실험: Worker LLM on/off × 대표 시나리오 → 재계획 횟수, 요청당 LLM 호출 수, 응답 시간.

## 8. 모듈 구조 (NF3006)

```
backend/app/
  main.py                 # FastAPI 앱, 라우터 등록, 구독자 연결
  core/config.py          # .env 로딩, 키 존재 여부
  api/{chat,plans,logs,health}.py
  schemas/                # Pydantic 요청·응답 모델
  agents/
    graph.py              # LangGraph 조립
    state.py
    nodes/{analyze,plan,execute,judge,respond}.py
    memory.py
    logging_agent.py      # LLM import 금지
  tools/
    base.py               # ToolResult, 실패 코드, 예외→실패 변환 데코레이터
    registry.py
    kopis.py  kakao.py
    parsers.py            # 러닝타임·회차·가격 파서
  events/bus.py
  storage/{db,plans,logs}.py
frontend/
  index.html (대화)  plans.html (계획 관리)  logs.html (실행 로그)
  js/  css/
tests/
  fixtures/  (docs/validation/samples 재사용)
```
