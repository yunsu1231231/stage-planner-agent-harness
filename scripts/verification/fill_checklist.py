"""셀프 체크리스트 작성 — docs/셀프체크리스트.xlsx 에 결과·증빙·비고 기입 + docs/08_self_checklist.md 생성.

기입 기준(체크리스트 F3): 확인하지 않은 것을 통과로 적지 않는다. 증빙은 저장소 안 경로·테스트 이름.
실행: .venv/Scripts/python scripts/verification/fill_checklist.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.styles import Alignment

ROOT = Path(__file__).resolve().parents[2]
XLSX = ROOT / "docs" / "셀프체크리스트.xlsx"
MD = ROOT / "docs" / "08_self_checklist.md"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SS = "docs/verification/screenshots/"
HEADER = {"C3": "셀프", "C4": "Yunsu", "C5": "Yunsu (실행·증빙 수집: Claude Code)", "C6": "2026-11-22 21:20"}

# 번호: (결과, 증빙, 비고)
ITEMS: dict[int, tuple[str, str, str]] = {
    1: ("통과", f"docs/verification/tools.json (GET /api/tools 출력), {SS}01_api_docs.png, tests/tools/test_registry.py, "
              "test_never_raises.py (Tool 4호출 × 실패 8종), test_kopis.py·test_nearby.py (키 없음 → MISSING_API_KEY, 잘못된 입력 → INVALID_INPUT)",
        "외부 API 툴 3종(kind=external) 구현. 로컬 서버 API 툴은 구분 구조(kind=local)만 정의 — 해당 심화(F3022·F3023) 미선택"),
    2: ("통과", "test_search_defaults_to_today_and_sends_identifying_ua, test_search_past_date_is_clamped_and_marked_estimated, docs/02_tool_spec.md 5.1",
        "KOPIS 는 미래 일정도 조회되므로 '조회할 수 없는 기준'은 지난 날짜 → 오늘로 보정하고 meta.estimated·note 로 명시"),
    3: ("통과", "test_detail_ids_from_search_feed_detail, test_detail_blank_runtime_is_no_runtime_and_not_invented, "
              "test_detail_unparseable_schedule_is_null_and_flagged, docs/verification/logs/V1.json", ""),
    4: ("통과", f"test_nearby_by_coordinates, test_nearby_no_result (NO_RESULT), {SS}03_chat_recommendation.png (이름·주소·거리·링크)", ""),
    5: ("통과", "docs/verification/scenario_report.md V1·V6 '추출 조건', test_s1_recommends_with_criteria_exclusions_and_places (말하지 않은 age=null), "
              "test_past_or_malformed_values_are_not_used", ""),
    6: ("통과", "docs/verification/logs/V1.json (plan.created → tool 순서), scenario_report.md V5 (Tool 0, plan 미진입), "
              "docs/verification/graph.md, test_graph_has_analyze_plan_execute_judge_respond, test_pw_graph_adds_verify_between_worker_and_judge",
        "기본 구조(planner_worker)는 Worker 와 판단 사이에 verify 노드가 추가됨 — docs/04_agent_design.md 7A.2 와 일치"),
    7: ("통과", f"{SS}14_chat_tool_failure.png, {SS}15_chat_after_failure.png (실패 직후 같은 세션 다음 요청 정상), scenario_report.md V4, "
              "test_one_detail_failure_is_recorded_and_flow_continues", ""),
    8: ("통과", f"{SS}03_chat_recommendation.png 판단 근거, test_eligible_uses_formula_start_plus_runtime, "
              "test_unknown_schedule_gives_back_calculated_latest_start, test_today_excludes_show_times_already_started",
        "실제 응답 73건은 회차가 모두 있어, 역산 기준(회차 미상)은 테스트로 확인"),
    9: ("통과", f"scenario_report.md V2 (재계획 2회, 상세 중복 조회 0), {SS}05_chat_replan.png, test_s2_replans_until_genre_relaxed_and_reuses_results", ""),
    10: ("통과", f"scenario_report.md V3 (재계획 3회 후 limit_reached), {SS}07_chat_limit_reached.png, test_replan_limit_is_enforced_independently_of_strategy_count", ""),
    11: ("통과", "scenario_report.md V7 (장르만 user, 날짜·시각·예산 memory), test_followup_changes_only_genre_and_keeps_other_conditions", ""),
    12: ("통과", f"{SS}03_chat_recommendation.png (추천·주변 식당·판단 근거·근거 Tool·제외 사유), scenario_report.md V1", ""),
    13: ("해당없음", "docs/01_requirements.md 1.1", "공연 도메인은 판단이 위험한 도메인이 아님"),
    14: ("통과", f"docs/verification/logs/V1.json, {SS}11_logs_sessions.png (여러 세션), {SS}12_logs_anomaly.png, "
               "test_sessions_are_isolated_and_summarized, test_logging_agent_stores_every_event_of_a_run_in_order",
         "LLM 판단은 llm.decision 이벤트의 decision·reason, analyze 종료 이벤트의 reason"),
    15: ("통과", "test_agent_runs_normally_without_logging_agent, test_chat_works_without_logging_agent, test_runs_when_publisher_raises",
         "오프라인 테스트로 구독 해제 상태 실행 확인"),
    16: ("통과", "가드 test_logging_zone_does_not_import_llm, test_normal_run_gets_report_and_no_llm_call, "
               "test_anomaly_reports_endpoint_returns_rule_verdict_per_run (정상 실행 LLM 호출 = 메인 Agent 3회뿐)",
         "로깅 Agent 의 LLM 은 '이상 판정 실행의 원인 진단'(F3020)에만 주입. 수집·저장·판정 코드는 LLM import 금지"),
    17: ("통과", f"test_append_keeps_original_event_and_order, {SS}13_logs_raw_events.png, test_storage_failure_does_not_break_conversation", ""),
    18: ("통과", f"{SS}01_api_docs.png (/api/logs 는 GET·DELETE 만), {SS}11_logs_sessions.png, {SS}12_logs_anomaly.png, "
               "test_logs_list_detail_delete_and_no_update (PUT·PATCH → 405)", ""),
    19: ("통과", f"{SS}04_chat_saved_card.png, {SS}09_plans_overlap.png, test_plan_crud_and_overlap, test_overlap_rule_half_open_interval", ""),
    20: ("통과", f"{SS}10_plans_after_edit.png, {SS}16_plans_after_delete.png", ""),
    21: ("통과", f"{SS}01_api_docs.png, docs/05_api_spec.md, test_frontend_calls_only_existing_api_routes, {SS}03·09·11",
         "브라우저 네트워크 탭 대신 API 계약 테스트(프론트 호출 10종 ⊂ OpenAPI)와 실제 화면 캡처로 확인"),
    22: ("통과", f"{SS}02_chat_processing.png (처리 중), {SS}05b_timeline_replan_panel.png (재계획 구분), "
               f"{SS}14_chat_tool_failure.png (Tool 실패), {SS}08_key_missing.png (키 누락)", ""),
    23: ("통과", "docs/verification/scenario_report.md (V1~V9: 응답·실행 로그·기대 vs 실제·처리 시간), docs/07_verification.md 4.7",
         "계획 요청 처리 10~17초(외부 API ~8초 + LLM 3회 ~8초), 화면에 경과 초 표시. 1차 실행 차이 3건은 원인·수정 기록(07 4.7.2)"),
    24: ("통과", "docs/verification/logs/V1.json (대표 요청 전체), V2.json·V3.json (재계획)", ""),
    25: ("통과", f"test_no_secrets_in_repo_files (추적 파일 전체에서 실제 키 값·키 패턴 검색), test_health_reports_flags_never_values, "
               f"test_chat_never_leaks_internal_error_details, {SS}08_key_missing.png", ""),
    26: ("미확인", "README.md 5절, docs/03_planning_validation.md T4, test_frontend_and_backend_are_separate_trees",
         "NF3006 은 확인 완료. NF3007: 카카오 쿼터(일 10만 건)·출처는 기록했으나 KOPIS 공연목록·공연상세 API 의 호출 한도·이용약관은 "
         "공개 페이지에서 확인하지 못함 → KOPIS 마이페이지/Open API 안내 확인 후 README 보완 필요"),
    27: ("통과", "docs/01~07, docs/verification/ (실행 결과 화면 16장·시나리오 기록·실행 로그), README.md, 이 체크리스트, docs/08_self_checklist.md",
         "제출물은 모두 포함. 이용 조건 내용 보완은 #26"),
    28: ("통과", f"tests/agents/test_anomaly.py, tests/events/test_anomaly_logging.py, {SS}12_logs_anomaly.png, "
               "docs/verification/pw_comparison.md C3 (실측: excessive_replan 탐지 + LLM 진단)",
         "이벤트 없는 실행은 evaluate_run([])·inspect(없는 실행) → undeterminable 로 확인"),
    29: ("통과", f"tests/agents/test_planner_worker.py, docs/verification/pw_comparison.md C3(verified_rebuild)·C5(Worker 요청 반영), "
               f"{SS}06_chat_worker_retry.png, {SS}07_chat_limit_reached.png, docs/04_agent_design.md 7A.2 (Agent별 LLM 호출 조건)", ""),
    30: ("통과", "docs/verification/pw_comparison.md (baseline · Worker LLM ON · OFF: 재계획·LLM 호출 수·응답 시간), "
               "test_fatal_failure_never_reaches_worker_llm, test_classify_rules, test_registry_marks_missing_required_argument, "
               f"test_no_result_worker_llm_fixes_tunable_arg_and_keeps_fixed_args, {SS}06_chat_worker_retry.png",
         "필수 인자 누락은 실제 대화로는 생기지 않아(인자를 코드가 채움) 레지스트리 검증·규칙 분류 테스트로 확인"),
    31: ("해당없음", "", "F3022 RAG 검색 Tool 미선택"),
    32: ("해당없음", "", "F3023 캘린더 연동 Tool 미선택"),
}


def main() -> None:
    wb = load_workbook(XLSX)
    ws = wb["체크리스트"]
    for cell, value in HEADER.items():
        ws[cell] = value
    rows = {ws.cell(row=r, column=3).value: r for r in range(9, 41) if isinstance(ws.cell(row=r, column=3).value, int)}
    assert sorted(rows) == list(range(1, 33)), rows
    wrap = Alignment(wrap_text=True, vertical="top")
    for no, (result, evidence, note) in ITEMS.items():
        r = rows[no]
        ws.cell(row=r, column=7, value=result).alignment = Alignment(horizontal="center", vertical="top")
        ws.cell(row=r, column=8, value=evidence or None).alignment = wrap
        ws.cell(row=r, column=9, value=note or None).alignment = wrap
    wb.save(XLSX)

    # ---- 마크다운 사본 (GitHub 에서 바로 읽기용)
    counts = {k: sum(v[0] == k for v in ITEMS.values()) for k in ("통과", "실패", "미확인", "해당없음")}
    lines = ["# 08. 셀프 체크리스트 (AI 코어 프로젝트 3회차)\n",
             f"> 원본: [`셀프체크리스트.xlsx`](셀프체크리스트.xlsx) · 점검 유형 **{HEADER['C3']}** · 작성자 {HEADER['C4']} · "
             f"점검자 {HEADER['C5']} · 점검 일시 {HEADER['C6']}",
             "> 기입 기준: 직접 실행해 기대 결과를 확인한 것만 '통과'. 증빙은 저장소 안 경로·테스트 이름 "
             "(테스트는 [`verification/pytest_report.txt`](verification/pytest_report.txt)).\n",
             f"**집계**: 통과 {counts['통과']} · 실패 {counts['실패']} · 미확인 {counts['미확인']} · 해당없음 {counts['해당없음']} · "
             f"미기입 0 · 전체 {len(ITEMS)}\n",
             "| 번호 | 영역 | 요구사항 | 확인 항목 | 결과 | 증빙 | 비고 |", "|---|---|---|---|---|---|---|"]
    area = None
    for no in range(1, 33):
        r = rows[no]
        merged_area = next((ws.cell(row=rng.min_row, column=2).value for rng in ws.merged_cells.ranges
                            if rng.min_col == 2 and rng.min_row <= r <= rng.max_row), ws.cell(row=r, column=2).value)
        area = merged_area or area
        req, item = ws.cell(row=r, column=4).value, ws.cell(row=r, column=5).value
        result, evidence, note = ITEMS[no]
        mark = {"통과": "✅ 통과", "미확인": "⚠️ 미확인", "실패": "❌ 실패", "해당없음": "— 해당없음"}[result]
        esc = lambda s: (s or "").replace("|", "\\|").replace("\n", " ")  # noqa: E731
        lines.append(f"| {no} | {esc(area)} | {esc(req)} | {esc(item)} | {mark} | {esc(evidence)} | {esc(note)} |")
    MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"xlsx 기입 완료 · {counts} · {MD.name} 생성")


if __name__ == "__main__":
    main()
