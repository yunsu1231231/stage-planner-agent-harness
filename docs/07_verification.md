# 07. 검증 결과 (명세 4장)

> 범위: 필수 기능 F3001~F3019, 비기능 NF3001~NF3007. 심화 F3020·F3021은 M6에서 추가한다.
> 원칙: 확인은 **실행 결과로 증명**한다. 자동 테스트(오프라인·결정적) + 실제 LLM·API 시나리오 + 결함 주입(mutation) 세 가지로 확인했다.

## 0. 요약

| 구분 | 결과 | 증거 |
|---|---|---|
| 자동 테스트 (오프라인) | **188 통과** / 0 실패 | [`verification/pytest_report.txt`](verification/pytest_report.txt) |
| 실제 API·LLM 테스트 (`-m live`) | Tool 5 + Agent 3 통과 | `tests/tools/test_live.py`, `tests/agents/test_live_agent.py` |
| 대표 시나리오 (4.7) | **9개 모두 기대와 일치** (2차 실행) | [`verification/scenario_report.md`](verification/scenario_report.md) |
| 1차 실행에서 찾은 차이 | **3건** → 테스트 추가 후 수정 | 아래 4.7.2 |
| 결함 주입 | 24종 주입(가드 2 · Tool 4 · Agent 6 · 저장/API 6 · 프론트 6) → 24종 검출 (Agent 2종은 처음에 놓쳐 테스트 보강) | [`06_test_strategy.md`](06_test_strategy.md) |

테스트 분포: Tool 85 · Agent 47 · 저장소 15 · API 13 · 하네스 자체 10 · 가드 7 · 프론트 7(내부 JS 단위 13) · 이벤트 4.

## 1. 검증 방법

| 방법 | 무엇을 | 왜 |
|---|---|---|
| L1~L4 자동 테스트 | 파서·판단식·Tool 계약·그래프 흐름·저장소·API | 매 커밋 전 hook 이 실행해 실패 시 커밋 차단 |
| L5 실제 시나리오 | 실제 LLM(gpt-4.1-mini) + KOPIS·카카오 + FastAPI 앱 전체 + 로깅 Agent | 가짜 LLM 으로는 알 수 없는 프롬프트 품질·실제 데이터 동작 확인 |
| L6 가드 | 키 노출, 버전 고정, 로깅 구역 LLM 금지, 브라우저 UA 위장, innerHTML | 구조·보안 불변 규칙 |
| 결함 주입 | 핵심 규칙을 일부러 깨서 테스트가 잡는지 | "테스트가 통과한다"가 "테스트가 의미 있다"를 뜻하게 하기 위해 |

## 2. 항목별 확인 (4.1 ~ 4.5)

### 4.1 Tool 확인 (F3001 ~ F3004)
| 확인 항목 | 결과 | 증거 |
|---|---|---|
| 등록 Tool 이름·설명·입력 스키마 목록 출력 | ✅ 3종 모두 external, 설명은 '언제 쓰는지' | [`verification/tools.json`](verification/tools.json) (`GET /api/tools`), `test_registry_lists_tools_with_name_description_schema` |
| Tool 마다 정상/실패 호출 → 예외 없이 실패 형식 | ✅ 4 호출 × 8 실패 = 32 조합 | `test_never_raises.py`, `test_search_bad_key_is_auth_failed`, `test_nearby_http_errors_map_to_codes`, `test_*_missing_key*` |
| 기준 날짜 미지정 시 기본값 | ✅ 오늘(KST), `meta.defaults=["date"]` | `test_search_defaults_to_today_and_sends_identifying_ua` |
| 요청 기준 ≠ 조회 기준 → 추정 명시 | ✅ 지난 날짜 → 오늘로 보정, `meta.estimated`·`note` | `test_search_past_date_is_clamped_and_marked_estimated` |
| 후보 식별자 → 상세 Tool 연결 | ✅ | `test_detail_ids_from_search_feed_detail`, 시나리오 V1 Tool 이력 |
| 비어 있는 속성을 임의 값으로 채우지 않음 | ✅ 러닝타임 없음 → `NO_RUNTIME`, 회차·가격 없음 → `null` + `missing` | `test_detail_blank_runtime_is_no_runtime_and_not_invented`, `test_detail_unparseable_schedule_is_null_and_flagged` |
| 보조 정보 결과 없음 형식 | ✅ `NO_RESULT` | `test_nearby_no_result` |

### 4.2 메인 Agent 실행 흐름 (F3005 ~ F3011)
| 확인 항목 | 결과 | 증거 |
|---|---|---|
| 추출 조건 출력, 없던 조건을 채우지 않음 | ✅ 조건마다 `source`(user/memory), 말하지 않은 조건 `null`, 지난 날짜·형식 오류 값은 버림 | 시나리오 V1 추출 조건, `test_past_or_malformed_values_are_not_used` |
| 그래프가 분석 → 계획 → 실행 → 판단 → 응답 | ✅ | [`verification/graph.md`](verification/graph.md) (mermaid 출력), `test_graph_has_analyze_plan_execute_judge_respond` |
| Tool 필요/불필요 요청의 계획 차이 | ✅ 인사는 plan 노드 미진입·Tool 0회 | V5, `test_chitchat_skips_plan_and_tools` |
| 앞 Tool 결과 → 다음 Tool 입력, 하나 실패해도 진행 | ✅ | `test_detail_uses_ids_from_search_and_nearby_uses_venue_from_detail`, `test_one_detail_failure_is_recorded_and_flow_continues`, V4 |
| 계산 값과 판단 기준 일치 | ✅ 추천마다 `시작 + 러닝타임 = 종료 ≤ 제한, 최저가 ≤ 예산` 근거 문장 | `test_eligible_uses_formula_start_plus_runtime`, V1 추천 근거 |
| 확인 불가 값은 역산 기준 제시 | ✅ 회차 미상 → "늦어도 16:50 시작 회차여야" | `test_unknown_schedule_gives_back_calculated_latest_start` |
| 재계획 시 확보 결과 재사용 | ✅ 본 후보는 상세 재조회 없음 | V2 (재계획 2회, 상세 중복 0), `test_s2_replans_until_genre_relaxed_and_reuses_results` |
| 상한 도달 시 멈추고 사유와 함께 응답 | ✅ 3회 후 `limit_reached` + 조정 제안 | V3, `test_s3_stops_at_replan_limit_with_reason_and_suggestion`, `test_replan_limit_is_enforced_independently_of_strategy_count` |
| 후속 요청에서 바뀐 조건만 갱신 | ✅ 장르만 user, 나머지 memory | V7, `test_followup_changes_only_genre_and_keeps_other_conditions` |
| 응답에 추천·보조 정보·판단 기준·근거 Tool 결과, 제외 사유 | ✅ | V1 추천 카드, `test_s1_recommends_with_criteria_exclusions_and_places` |
| 위험 도메인 면책 | 해당 없음 (공연 도메인) | — |

### 4.3 로깅 Agent 와 실행 로그 (F3012 ~ F3014)
| 확인 항목 | 결과 | 증거 |
|---|---|---|
| 단계 진입·종료, Tool 요청·응답·소요 시간 이벤트 | ✅ | [`verification/logs/V1.json`](verification/logs/V1.json) (대표 요청 1건 전체 로그), `test_logging_agent_stores_every_event_of_a_run_in_order` |
| LLM 판단과 이유가 이벤트에 남음 | ✅ `llm.decision`(의도·이유, Tool 선택), `node.exit`(analyze 이유) | V1 로그, 시나리오 리포트의 "LLM 판단" 줄 |
| 로깅 Agent 가 LLM 을 쓰지 않음 | ✅ | 가드 `test_logging_zone_does_not_import_llm` (logging_agent·events·storage import 감시) |
| 로깅 Agent 미연결에도 메인 Agent 정상 | ✅ | `test_agent_runs_normally_without_logging_agent`, `test_chat_works_without_logging_agent`, 발행 함수가 예외를 던져도 정상 `test_runs_when_publisher_raises` |
| 세션 단위 구분, 섞이지 않음 | ✅ | `test_sessions_are_isolated_and_summarized` |
| 목록·상세(실행 순서)·삭제 | ✅ | `test_logs_list_detail_delete_and_no_update`, `test_runs_listed_in_occurrence_order_even_when_seq_restarts` |
| 수정 API 없음 | ✅ `PUT/PATCH /api/logs/{id}` → 405, 저장소에 update 메서드 없음 | `test_routes_are_separated_by_resource`, `test_repository_has_no_update_path` |

### 4.4 계획 관리 (F3015 ~ F3016)
| 확인 항목 | 결과 | 증거 |
|---|---|---|
| 핵심 값·생성 일시가 목록·상세에 | ✅ | `test_create_returns_plan_with_core_values_and_timestamps`, `test_plan_crud_and_overlap` |
| 같은 날 시간 겹침 → 저장되고 알림 | ✅ `[start, end)` 반열린 구간, 경계 맞닿음은 겹침 아님 | `test_overlap_rule_half_open_interval` (5 경우), `test_confirm_plan_through_chat_persists_and_reports_overlap` |
| 수정·삭제 → 화면 즉시 반영 | ✅ API 수정 시 겹침 재검사 / 화면은 수정·삭제 후 목록 재조회 | `test_update_changes_fields_rechecks_overlap_excluding_self`, `frontend/js/plans.js` (📷 캡처 필요) |

### 4.5 서비스 구성과 화면 (F3017 ~ F3019)
| 확인 항목 | 결과 | 증거 |
|---|---|---|
| 대화·계획·로그 API 경로 분리, 형식 일치 | ✅ Pydantic 모델 | `test_routes_are_separated_by_resource`, `/docs` (📷) |
| 두 화면이 백엔드 API 로 데이터 표시 | ✅ | 계약 테스트 `test_frontend_calls_only_existing_api_routes` (프론트 호출 10종 ⊂ OpenAPI) (📷) |
| 실행 단계·Tool 이력 순서, 재계획 지점 구분 | ✅ | `timeline.test.mjs`, 화면 오른쪽 패널 (📷 V2 처럼 재계획 있는 요청) |
| 처리 중 상태, Tool 실패·키 누락 안내 | ✅ 스피너+경과 초 / 부분 실패 안내 / `/api/health` 배너 | V4·V9, `test_health_reports_flags_never_values` (📷) |

## 3. 4.6 심화 기능
M6 에서 F3020(이상 징후 판단) → F3021(Planner·Worker) 구현 후 이 절을 채운다.

## 4. 4.7 대표 시나리오 검증

### 4.7.1 결과 (2차 실행, 2026-11-22 20시대, 실제 LLM·API)
| ID | 명세 유형 | 요청 | 결과 | 재계획 | LLM | 시간 |
|---|---|---|---|---|---|---|
| V1 | 한 번에 충족 | 토 14시 이후 대학로 5만원↓ 연극, 18시 전 종료, 식당도 | `ok` 추천 3 + 주변 식당 | 0 | 3 | 17.7초 |
| V2 | **재계획 필요** | 11/29(일) 19시 이후·21:30 전 종료·3만원↓ 대학로 뮤지컬 | `ok` — 후보 확장 → **장르 해제** 후 1편, 완화 안내 | 2 | 3 | 11.6초 |
| V3 | **상한 도달** | 수 오전 9시 이후·오전 11시 전 종료 대학로 연극 | `limit_reached` — 후보 확장 → 장르 해제 → 지역 확대 후 멈춤 + 조정 제안 | 3 | 3 | 12.5초 |
| V4 | **Tool 하나 실패** | V1 + 카카오 키 무효 | `partial` — 추천 유지, 주변 장소 `AUTH_FAILED` 안내 | 0 | 3 | 13.6초 |
| V5 | **Tool 불필요** | 인사·사용법 | `chat` — plan 미진입, Tool 0 | 0 | 2 | 2.7초 |
| V6 | 되묻기 | "7시 전에 끝나야 해" | `clarify` — 날짜·시작 시각 질문, Tool 0 | 0 | 1 | 1.4초 |
| V7 | 대화 맥락 | (V1 후) "같은 날 뮤지컬로" | `ok` — 장르만 갱신 | 0 | 3 | 8.9초 |
| V8 | 계획 저장 | (V7 후) "1번으로 저장해줘" | `saved` | 0 | 1 | 1.2초 |
| V9 | 키 누락 | V1 + KOPIS 키 없음 | `config_missing` — 재계획 없이 키 이름만 안내 | 0 | 2 | 2.2초 |

- 요청별 실행 결과·실행 로그(단계, Tool 호출 이력, 재계획)·기대 vs 실제 검사표: [`verification/scenario_report.md`](verification/scenario_report.md)
- **대표 요청 1건의 전체 실행 로그**: [`verification/logs/V1.json`](verification/logs/V1.json)
- **재계획 사례**: [`verification/logs/V2.json`](verification/logs/V2.json) (재계획 후 성공), [`verification/logs/V3.json`](verification/logs/V3.json) (상한 도달)

### 4.7.2 기대와 실제의 차이 → 원인 → 수정 (1차 실행)
1차 실행([`scenario_report_run1.md`](verification/scenario_report_run1.md))은 자동 검사 9/9 통과였지만, **결과를 사람이 읽어 3건의 차이를 찾았다.** 모두 실패하는 테스트를 먼저 추가한 뒤 수정했다.

| # | 시나리오 | 기대 | 실제 (1차) | 원인 | 수정 | 회귀 테스트 |
|---|---|---|---|---|---|---|
| 1 | V2 | 아직 볼 수 있는 회차만 추천 | 19:55에 '이번 일요일'(=당일) **이미 시작한 19:00 회차를 추천** | 판단 단계가 현재 시각을 고려하지 않음 | 관람일이 오늘이면 현재 시각 이전 회차 제외 (`judge.evaluate(now=)`) | `test_today_excludes_show_times_already_started` |
| 2 | V4 | 주변 장소 조회 실패라고 안내 | 안내 "해당 후보는 제외했습니다"(사실과 다름), 응답 "식당 장소는 없습니다" | 실패한 Tool 과 무관한 고정 문구, '조회 실패'와 '결과 없음'을 구분하지 않음 | Tool 별 안내 문구, 추천마다 `places_status`(ok·none·failed), 응답 프롬프트에 구분 규칙 | `test_nearby_failure_is_reported_as_failure_not_as_no_places` |
| 3 | V6 | 자연스러운 되묻기 | "몇 시 이후에 시작하면 좋을지을(를)" | 템플릿 조사 처리 | 항목 나열형 문장으로 변경 | `test_clarify_before_any_tool_when_start_point_missing` |

- 수정 1의 부수 효과: V2 요청이 '이번 일요일'(실행 당일 저녁)이라 2차 실행에서는 저녁 회차가 모두 지나 `limit_reached` 가 됨 → **판단은 올바르다**. 재계획 성공 사례를 안정적으로 재현하도록 요청 날짜를 '11월 29일 일요일'로 명시.
- 시나리오 러너에 위 3건을 검사 항목으로 추가해 재발을 막는다.

## 5. 4.8 비기능 요구사항
| 번호 | 확인 | 결과 | 증거 |
|---|---|---|---|
| NF3001 API 키 관리 | 소스·제출물에 키 없음 | ✅ `.env` 만 사용, git 제외. 가드가 추적 파일 전체에서 실제 키 값·키 패턴 검사 (가짜 키 `sk-test-…` 도 잡아냄) | `test_no_secrets_in_repo_files`, `test_env_example_has_no_secret_values`, `test_sensitive_paths_are_gitignored` |
| NF3002 화면 노출 제한 | 키·오류 상세 미노출 | ✅ health 는 설정 여부만, 오류는 `{code, message}`, 예외 메시지는 타입명만 보존, 화면 출력은 자동 이스케이프 | `test_health_reports_flags_never_values`, `test_chat_never_leaks_internal_error_details`, `test_exception_inside_tool_becomes_upstream_error_without_leaking_detail`, `dom.test.mjs` |
| NF3003 Tool 실패 처리 | 서비스 중단 없음 | ✅ | `test_never_raises.py`(32), V4, V9 |
| NF3004 재계획 상한 | 무한 반복 없음 | ✅ 상한 3, 전략 수와 독립 검증 | V3, `test_replan_limit_is_enforced_independently_of_strategy_count` |
| NF3005 응답 시간 | 사용에 지장 없음 | △ 대표 계획 요청 **11~18초**, 되묻기·대화 1~3초. 처리 중 경과 초를 화면에 표시. 내역: KOPIS 목록 ~3초, 상세 15건 ~2초, 주변 장소 ~3초, LLM 3회 ~8초 | 시나리오 표, `04_agent_design.md` 4.8 |
| NF3006 모듈 분리 | 프론트/백, Agent/Tool 파일 분리 | ✅ `frontend/`(정적) ↔ `backend/app/{agents,tools,events,storage,api}` | `test_frontend_and_backend_are_separate_trees`, 디렉터리 구조 |
| NF3007 출처·이용 조건 | 기록 | △ 카카오 쿼터 기록(일 10만 건). **KOPIS 약관·호출 한도는 공개 페이지에서 확인하지 못함** → 마이페이지 확인 필요 | `README.md` 외부 API 절, `03_planning_validation.md` T4 |

## 6. 4.9 제출 전 점검 목록
| 항목 | 상태 |
|---|---|
| 필수 기능 F3001~F3019 모두 동작 | ✅ (위 2절, 시나리오 9종) |
| 선택한 심화 기능 동작 + 필수 결과와 비교 | ⏳ M6 |
| 증명 스크린샷·실행 로그 첨부 | 실행 로그 ✅ / **스크린샷 📷 사람이 캡처 필요** (아래 7절) |
| 요구사항 정의서·Agent 설계·Tool 정의서·API 명세서·소스·실행 로그 샘플·README | ✅ `docs/01, 04, 02, 05`, 소스, `docs/verification/logs/`, `README.md` |
| 셀프 체크리스트 | ⏳ 3일차 오후 제공 예정 |

## 7. 사람이 캡처해야 할 화면 (📷)
자동화하지 않은 브라우저 화면. 백엔드(8000)·프론트(5500)를 띄운 뒤 캡처해 `docs/verification/screenshots/` 에 둔다.
1. `http://127.0.0.1:8000/docs` — API 경로 분리 (4.5)
2. 대화 화면 — V1 요청: 추천 카드(근거·주변 식당) + 오른쪽 실행 과정 (4.2, 4.5)
3. 대화 화면 — V2 요청: 타임라인의 **주황색 재계획 구분선** (4.5, F3019)
4. 대화 화면 — 처리 중 스피너 (4.5)
5. 대화 화면 — `.env` 에서 KOPIS 키를 지우고 재시작 → 키 누락 배너 (4.5)
6. 계획 관리 — 겹치는 계획 노란 표시, 수정 후 즉시 반영 (4.4)
7. 실행 로그 — 세션 목록 → 타임라인·원본 이벤트 (4.3)

## 8. 한계와 남은 일
- 브라우저 렌더링·클릭 흐름은 자동 검증하지 않음 (계약·로직만 자동) → 7절 캡처로 보완
- 대화 맥락은 서버 메모리 보관 → 서버 재시작 시 초기화 (설계대로)
- 응답 시간 단축(상세·주변 장소 병렬 조회)은 범위 동결 원칙상 보류
- KOPIS 이용약관·호출 한도 확인 필요 (NF3007)
