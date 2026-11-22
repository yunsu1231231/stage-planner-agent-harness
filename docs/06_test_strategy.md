# 06. 테스트 전략 (검증 하네스)

> 목적: 명세 4장의 확인 항목을 **자동으로 반복 실행 가능한 테스트**로 옮겨, 사람과 에이전트(Claude Code)가 같은 기준으로 "완료"를 판정하게 한다.
> 원칙: **테스트가 먼저, 구현은 테스트를 통과시키는 것.** 테스트는 `docs/` 명세에서 도출하고, 구현 코드를 보고 테스트를 맞추지 않는다.

## 1. 테스트 계층

| 계층 | 대상 | 외부 의존 | 실행 시간 | 예 |
|---|---|---|---|---|
| **L1 단위** | 순수 함수: 파서, 판단 계산식, 조건 병합, 재계획 사다리, 겹침 검사 | 없음 | ms | "1시간 10분"→70, `15:00+70분 ≤ 18:00` |
| **L2 Tool 계약** | 각 Tool의 입출력·실패 코드, **예외를 던지지 않음** | 녹화한 실제 응답(fixture) + 가짜 HTTP | ms | KOPIS `returncode 02` → `AUTH_FAILED` |
| **L3 그래프** | LangGraph 노드 순서, 분기, 재계획 횟수, 캐시 재사용, 이벤트 발행 | 가짜 LLM(정해진 출력) + 가짜 Tool | 초 | S2에서 `replan` 2회, 상세 재호출 0회 |
| **L4 API** | FastAPI 경로·형식·상태 코드 | TestClient + 임시 SQLite | 초 | `PATCH /api/logs/x` → 405 |
| **L5 시나리오** | 대표 요청 S1~S7 끝에서 끝까지 | fixture + 가짜 LLM (기본) / 실제 API·LLM (`live`) | 초~분 | S3 → `limit_reached` |
| **L6 가드** | 구조·보안 불변 규칙 | 없음 | ms | 로깅 Agent 모듈이 LLM 패키지를 import하지 않음, 소스에 키 없음, 버전 고정 유지 |

- 기본 `pytest` 실행은 **L1~L6 오프라인·결정적**. 실제 API·LLM 호출은 `pytest -m live`로만 실행한다 (비용·속도·호출 한도 보호).
- fixture는 `docs/validation/samples/`(기획 검증에서 녹화한 실제 응답, 키 마스킹)를 `tests/fixtures/`로 복사해 사용한다.

## 2. 명세 4장 추적표 (요구사항 → 테스트)

| 명세 확인 항목 | 요구사항 | 계층 | 테스트 (예정 이름) |
|---|---|---|---|
| Tool 이름·설명·스키마 목록 출력 | F3001 | L2 | `test_registry_lists_tools_with_schema` |
| 정상/실패 호출 시 예외 없이 실패 형식 | F3001, NF3003 | L2 | `test_tool_never_raises[각 Tool × 실패 fixture]` |
| 후보 Tool 기본 날짜 | F3002 | L2 | `test_search_default_date_is_today` |
| 요청·실제 조회 기준 차이 명시 | F3002 | L2 | `test_search_marks_estimated` |
| 목록 ID → 상세 연결 | F3002, F3007 | L3 | `test_detail_uses_ids_from_search` |
| 빈 속성 임의로 채우지 않음 | F3003, F3008 | L1/L2 | `test_missing_runtime_is_unjudgeable` |
| 보조 정보 결과 없음 형식 | F3004 | L2 | `test_places_no_result_code` |
| 조건 추출, 없는 조건 null | F3005 | L3 | `test_analyze_keeps_unspecified_null` |
| 그래프 노드 구성 | F3005~F3011 | L3 | `test_graph_nodes_and_edges` |
| Tool 필요/불필요 계획 차이 | F3006 | L3 | `test_chitchat_skips_plan` |
| Tool 하나 실패해도 진행 | F3007, NF3003 | L3 | `test_one_detail_failure_continues` |
| 계산 값과 판단 일치, 역산 기준 | F3008 | L1 | `test_judge_formula[...]`, `test_back_calculated_latest_start` |
| 재계획 시 확보 결과 재사용 | F3009 | L3 | `test_replan_reuses_cache` |
| 상한 도달 시 멈춤 | F3009, NF3004 | L3 | `test_replan_stops_at_limit` |
| 바뀐 조건만 갱신 | F3010 | L1/L3 | `test_memory_merge_only_changed` |
| 응답에 추천·근거·제외 사유 | F3011 | L3 | `test_payload_has_criteria_and_exclusions` |
| 단계·Tool·LLM 판단 이벤트 발행 | F3012 | L3 | `test_events_emitted_per_node_and_tool` |
| 로깅 Agent LLM 미사용 | F3013 | L6 | `test_logging_agent_has_no_llm_import` |
| 구독자 없이도 정상 동작 | F3012 | L3 | `test_graph_runs_without_subscriber` |
| 세션 단위 저장, 섞이지 않음 | F3013 | L4 | `test_logs_isolated_by_session` |
| 로그 목록·상세·삭제, 수정 API 없음 | F3014 | L4 | `test_logs_crud`, `test_logs_update_not_allowed` |
| 계획 저장·겹침 알림 | F3015 | L1/L4 | `test_overlap_detection`, `test_create_plan_reports_overlap` |
| 계획 수정·삭제 | F3016 | L4 | `test_plan_patch_and_delete` |
| 경로 분리·형식 | F3017 | L4 | `test_openapi_paths` |
| 키 누락 안내, 화면에 키 미노출 | F3019, NF3002 | L4 | `test_health_reports_flags_not_values` |
| 소스에 키 없음 | NF3001 | L6 | `test_no_secrets_in_repo` |
| 대표 시나리오 5종 이상 | 4.7 | L5 | `test_scenario[S1..S7]` |

## 3. 가짜 LLM (결정적 테스트의 핵심)
- 노드는 LLM을 직접 만들지 않고 **주입받는다** (`llm` 의존성). 테스트에서는 시나리오별로 정해진 structured output을 돌려주는 가짜 LLM을 넣는다.
- 이렇게 하면 "LLM이 이렇게 판단했을 때 그래프가 올바르게 움직이는가"를 매번 같은 결과로 검증할 수 있다. LLM 자체의 품질은 L5 `live`에서 따로 본다.

## 4. 에이전틱 개발 루프에서의 역할

```
docs 명세 ──▶ [테스트 작성] ──▶ 실패 확인(Red) ──▶ [구현] ──▶ 통과(Green) ──▶ [리뷰] ──▶ 커밋
                 ▲ 테스트 작성자                    ▲ 구현자                    ▲ 리뷰어 (서브에이전트)
```
- 기능 단위마다 **테스트를 먼저 커밋 가능한 상태로 작성**하고, 실패하는 것을 확인한 뒤 구현한다.
- 테스트 작성과 구현을 다른 컨텍스트(서브에이전트)에서 하면 "구현에 맞춘 테스트"를 막을 수 있다 — 실습 포인트.
- **완료 기준 = `pytest` 전체 통과.** CLAUDE.md 커밋 규칙의 "검증 완료 후 커밋"은 이것을 뜻한다.
- 이후 단계에서 hook으로 자동화: 작업 종료 시 pytest 실행, 실패 시 완료 차단 (구현 단계 진입 시 설정).

## 5. 도입 순서
1. **지금 (설계 동결 시점)**: 이 문서 + 추적표 확정, `requirements-dev.txt`(pytest)
2. **구현 0단계 (M0, ✅ 완료)**: `tests/` 골격, `conftest.py`(네트워크 차단), fixture 복사, `FakeLLM`·`FakeSession`, L6 가드 7종, 하네스 자체 테스트 10종, hook(`git commit/push` 직전·종료 전 pytest) → 이때부터 매 커밋 전 자동 실행
   - 가드가 실제로 위반을 잡는지 **의도적 위반 주입(mutation)으로 Red 확인** 완료 (LLM import, 브라우저 UA)
   - FakeSession은 KOPIS의 charset 누락(한글 깨짐)·차단 후 성공 시퀀스·연결 끊김을 재현한다
3. **구현 각 단계**: 해당 기능의 L1/L2 → 구현 → L3/L4
   - **M1 Tool (✅ 완료)**: `tests/tools/` 파서 L1 22 + 레지스트리·KOPIS·카카오 L2 47 + "예외를 던지지 않음" 32조합 → 오프라인 101 통과, `-m live` 5 통과
     - Red 확인(모듈 없음) → 구현 → Green. 한 번에 통과했기 때문에 **mutation 4종 주입**(UTF-8 강제 제거, 공연완료 포함, 백오프 제거, 과거 날짜 보정 제거) → 모두 테스트가 잡음
     - 참고: hook 이 실패 상태 커밋을 막으므로 Red 상태는 커밋 이력에 남지 않는다 (테스트+구현이 한 커밋)
   - **M2 메인 Agent (✅ 완료)**: `tests/agents/` 판단 L1 18 + 메모리 L1 3 + 그래프 L3 25 → 오프라인 147 통과, `-m live` 3 통과(실제 LLM)
     - `FakeWorld`: 가상 카탈로그로 KOPIS·카카오 응답을 생성하고 **실제 Tool 코드**를 그대로 통과시킨다 (그래프 테스트가 Tool 계약까지 검증)
     - mutation 6종 주입 → **처음엔 2종이 살아남음**: ① 본 후보 재조회(캐시가 HTTP 재호출을 가려 중복 판단을 못 잡음) ② 재계획 상한 완화(전략이 3개라 상한 검사가 독립적으로 검증되지 않음) → 테스트 보강 후 6종 모두 검출
     - 테스트 작성 중 **의미 없는 테스트 1건**(항상 통과)을 발견해 '지난 날짜는 쓰지 않고 되묻기' 검증으로 교체
   - **M3 로깅·저장·API (✅ 완료)**: `tests/storage` 계획 11 + 로그 5, `tests/events` 버스·로깅 Agent 4, `tests/api` 13 → 오프라인 179 통과
     - 하네스 수정: 네트워크 차단이 **루프백까지 막아** TestClient(Windows asyncio socketpair)가 못 뜨는 문제 → 외부만 차단하고 루프백 허용
     - **가드가 잡은 것**: 테스트용 가짜 키 `sk-test-…` 가 OpenAI 키 패턴과 같아 `test_no_secrets_in_repo_files` 실패 → 형식이 다른 가짜 값으로 교체
     - **테스트 시간이 드러낸 성능 문제**: 전체 5초 → 46초. 원인은 이벤트마다 SQLite 연결 개폐 → 연결 재사용으로 대화 테스트 2초 → 0.3초
     - mutation 6종(겹침 경계, 수정 시 자기 자신과 겹침, 로깅 예외 전파, 시작>종료 허용, health 키 노출, 로그 정렬) 모두 검출
     - 실서버 스모크: 실제 키로 chat → 저장 → 로그 → 405 확인 후 테스트 데이터 삭제
   - **M4 프론트엔드 (✅ 완료)**: JS 단위 13 (`node --test`, pytest 가 실행 → hook 게이트에 포함) + `tests/frontend` 7 → 전체 186 통과
     - **API 계약 테스트**: 프론트 JS 의 `api("METHOD", "/api/...")` 호출을 모아 FastAPI OpenAPI 경로·메서드와 대조 → 백엔드 변경 시 화면이 조용히 깨지는 것 방지
     - **XSS 가드**: `innerHTML` 은 `dom.js` 한 곳에서만, 나머지는 자동 이스케이프 템플릿을 거치도록 강제
     - mutation 6종(없는 경로 호출, 잘못된 메서드, 이스케이프 제거, innerHTML 우회, 재계획 라운드 미분리, 겹침 경계) 모두 검출
     - 한계: 브라우저 렌더링 자체(레이아웃·클릭 흐름)는 자동화하지 않음 → 사람이 화면으로 확인 (명세 4.5 캡처 항목)
4. **3일차**: L5 시나리오로 4.7 검증 기록 자동 생성 (`docs/` 검증 결과 문서의 근거)
