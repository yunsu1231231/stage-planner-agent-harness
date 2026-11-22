# Planner·Worker 구조 전후 비교 (F3021)

- 생성 2026-11-22T20:45:11 · 모델 `gpt-4.1-mini` · 실제 KOPIS·카카오 API · 시나리오 5 × 구성 3
- 실행: `.venv/Scripts/python scripts/verification/compare_architectures.py` · 원본 `pw_comparison.json`, `logs/compare_*.json`

## 1. 요약 (요청당 평균)

| 구성 | LLM 호출 | 그중 Worker | 재계획 합계 | 실제 Tool 호출 | 응답 시간 |
|---|---|---|---|---|---|
| baseline (필수 구조) | 3.0 | 0.0 | 7 | 29.6 | 9.9초 |
| Planner·Worker · Worker LLM ON | 3.2 | 0.2 | 6 | 29.8 | 9.7초 |
| Planner·Worker · Worker LLM OFF | 3.0 | 0.0 | 6 | 29.4 | 8.9초 |

## 2. 시나리오별

### C1. 정상 경로

요청: 이번 토요일 오후 2시 이후에 대학로에서 5만원 이하 연극 보고 6시 전에는 끝내고 싶어. 끝나고 갈 식당도 알려줘

| 구성 | 결과 | 재계획 (전략) | LLM (Worker) | 실제 Tool | 시간 | 검증·최종 판정 | 결과 요약 |
|---|---|---|---|---|---|---|---|
| baseline (필수 구조) | `ok` | 0 (-) | 3 (0) | 19 | 10.2초 | - · normal | 타조소년들 [대학로], 단막극 낭독공연, 시선: Eleven Ways o |
| Planner·Worker · Worker LLM ON | `ok` | 0 (-) | 3 (0) | 19 | 10.6초 | normal · normal | 타조소년들 [대학로], 단막극 낭독공연, 시선: Eleven Ways o |
| Planner·Worker · Worker LLM OFF | `ok` | 0 (-) | 3 (0) | 19 | 10.0초 | normal · normal | 타조소년들 [대학로], 단막극 낭독공연, 시선: Eleven Ways o |

### C2. 재계획 후 성공

요청: 11월 29일 일요일 저녁 7시 이후에 시작해서 9시 반 전에 끝나는 3만원 이하 대학로 뮤지컬 찾아줘

| 구성 | 결과 | 재계획 (전략) | LLM (Worker) | 실제 Tool | 시간 | 검증·최종 판정 | 결과 요약 |
|---|---|---|---|---|---|---|---|
| baseline (필수 구조) | `ok` | 2 (expand_pool → drop_genre) | 3 (0) | 48 | 12.4초 | - · normal | 꿈깨 [대학로] |
| Planner·Worker · Worker LLM ON | `ok` | 2 (expand_pool → drop_genre) | 3 (0) | 48 | 11.5초 | normal/normal/normal · normal | 꿈깨 [대학로] |
| Planner·Worker · Worker LLM OFF | `ok` | 2 (expand_pool → drop_genre) | 3 (0) | 48 | 10.0초 | normal/normal/normal · normal | 꿈깨 [대학로] |

### C3. 재계획 상한

요청: 다음 주 수요일 오전 9시 이후에 시작해서 오전 11시 전에 끝나는 대학로 연극 있어?

| 구성 | 결과 | 재계획 (전략) | LLM (Worker) | 실제 Tool | 시간 | 검증·최종 판정 | 결과 요약 |
|---|---|---|---|---|---|---|---|
| baseline (필수 구조) | `limit_reached` | 3 (expand_pool → drop_genre → widen_region) | 3 (0) | 62 | 16.9초 | - · anomaly ['excessive_replan'] | - |
| Planner·Worker · Worker LLM ON | `limit_reached` | 3 (expand_pool → drop_genre → widen_region) | 3 (0) | 62 | 15.0초 | normal/normal/normal/anomaly · anomaly ['excessive_replan'] | - |
| Planner·Worker · Worker LLM OFF | `limit_reached` | 3 (expand_pool → drop_genre → widen_region) | 3 (0) | 62 | 13.3초 | normal/normal/normal/anomaly · anomaly ['excessive_replan'] | - |
- baseline (필수 구조) 로깅 Agent 진단(LLM): Planner Agent 문제입니다. 후보 충족이 없어 재계획이 3회 발생했으므로, 후보 선정 기준이나 필터 조건을 완화하여 후보를 확보하도록 수정해야 합니다.
- Planner·Worker · Worker LLM ON 로깅 Agent 진단(LLM): 경고 원인은 Planner의 재계획이 3회로 상한에 도달했기 때문입니다. Planner가 후보가 없을 때 재계획 전략을 조정하거나 재계획 횟수를 제한하는 로직을 개선해야 합니다. Worker와 로깅 Agent에는 문제점이 없습니다.
- Planner·Worker · Worker LLM OFF 로깅 Agent 진단(LLM): 경고 원인은 Planner의 재계획 3회 초과입니다. Planner가 후보가 없을 때마다 재계획을 반복하는 전략을 수정해야 합니다. Worker와 로깅 Agent에는 문제 없습니다.

### C4. 공연명 오타 (Worker 인자 수정)

요청: 여신님 보고계셔 러닝타임이 몇 분이야?

| 구성 | 결과 | 재계획 (전략) | LLM (Worker) | 실제 Tool | 시간 | 검증·최종 판정 | 결과 요약 |
|---|---|---|---|---|---|---|---|
| baseline (필수 구조) | `no_match` | 0 (-) | 3 (0) | 1 | 3.0초 | - · normal | - |
| Planner·Worker · Worker LLM ON | `ok` | 0 (-) | 4 (1) | 3 | 4.5초 | normal · normal | 여신님이 보고 계셔 [대학로] |
| Planner·Worker · Worker LLM OFF | `no_match` | 0 (-) | 3 (0) | 1 | 2.8초 | normal · normal | - |
- Planner·Worker · Worker LLM ON Worker 판단: `retry` (LLM) search_performances NO_RESULT patch={"keyword": "여신님"} — 공연명이 길어 검색 결과가 없으므로 앞부분만 사용해 검색한다.
- Planner·Worker · Worker LLM OFF Worker 판단: `replan_request` (규칙) search_performances NO_RESULT — worker_llm_off

### C5. 후보 0건 장르 (Worker 계획 변경 요청)

요청: 11월 28일 토요일 저녁 6시 이후 대학로에서 대중무용 공연 보고 싶어. 9시 전에 끝나야 해

| 구성 | 결과 | 재계획 (전략) | LLM (Worker) | 실제 Tool | 시간 | 검증·최종 판정 | 결과 요약 |
|---|---|---|---|---|---|---|---|
| baseline (필수 구조) | `ok` | 2 (expand_pool → drop_genre) | 3 (0) | 18 | 7.2초 | - · normal | 타조소년들 [대학로], 단막극 낭독공연, 시선: Eleven Ways o |
| Planner·Worker · Worker LLM ON | `ok` | 1 (drop_genre) | 3 (0) | 17 | 7.1초 | normal/normal · normal | 타조소년들 [대학로], 단막극 낭독공연, 시선: Eleven Ways o |
| Planner·Worker · Worker LLM OFF | `ok` | 1 (drop_genre) | 3 (0) | 17 | 8.7초 | normal/normal · normal | 타조소년들 [대학로], 단막극 낭독공연, 시선: Eleven Ways o |
- Planner·Worker · Worker LLM ON Worker 판단: `replan_request` (규칙) search_performances NO_RESULT — 고칠 수 있는 인자 없음 — Planner 에 계획 변경 요청
- Planner·Worker · Worker LLM ON 재계획 사유: 충족 후보 0개 (제외 0, 판단 불가 0); Worker 요청: search_performances NO_RESULT
- Planner·Worker · Worker LLM OFF Worker 판단: `replan_request` (규칙) search_performances NO_RESULT — 고칠 수 있는 인자 없음 — Planner 에 계획 변경 요청
- Planner·Worker · Worker LLM OFF 재계획 사유: 충족 후보 0개 (제외 0, 판단 불가 0); Worker 요청: search_performances NO_RESULT

## 3. 실행 흐름 예 (C4)

- **baseline (필수 구조)**: analyze → plan → execute → judge → respond
- **Planner·Worker · Worker LLM ON**: analyze → plan → execute → verify → judge → respond
- **Planner·Worker · Worker LLM OFF**: analyze → plan → execute → verify → judge → respond
