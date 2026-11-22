# Planner·Worker 구조 전후 비교 (F3021)

- 생성 2026-11-22T20:40:04 · 모델 `gpt-4.1-mini` · 실제 KOPIS·카카오 API · 시나리오 5 × 구성 3
- 실행: `.venv/Scripts/python scripts/verification/compare_architectures.py` · 원본 `pw_comparison.json`, `logs/compare_*.json`

## 1. 요약 (요청당 평균)

| 구성 | LLM 호출 | 그중 Worker | 재계획 합계 | 실제 Tool 호출 | 응답 시간 |
|---|---|---|---|---|---|
| baseline (필수 구조) | 3.0 | 0.0 | 7 | 30.2 | 10.6초 |
| Planner·Worker · Worker LLM ON | 3.4 | 0.4 | 7 | 30.6 | 10.7초 |
| Planner·Worker · Worker LLM OFF | 3.0 | 0.0 | 7 | 30.2 | 10.6초 |

## 2. 시나리오별

### C1. 정상 경로

요청: 이번 토요일 오후 2시 이후에 대학로에서 5만원 이하 연극 보고 6시 전에는 끝내고 싶어. 끝나고 갈 식당도 알려줘

| 구성 | 결과 | 재계획 (전략) | LLM (Worker) | 실제 Tool | 시간 | 검증·최종 판정 | 결과 요약 |
|---|---|---|---|---|---|---|---|
| baseline (필수 구조) | `ok` | 0 (-) | 3 (0) | 19 | 16.3초 | - · normal | 타조소년들 [대학로], 단막극 낭독공연, 시선: Eleven Ways o |
| Planner·Worker · Worker LLM ON | `ok` | 0 (-) | 3 (0) | 19 | 14.9초 | normal · normal | 타조소년들 [대학로], 단막극 낭독공연, 시선: Eleven Ways o |
| Planner·Worker · Worker LLM OFF | `ok` | 0 (-) | 3 (0) | 19 | 10.2초 | normal · normal | 타조소년들 [대학로], 단막극 낭독공연, 시선: Eleven Ways o |

### C2. 재계획 후 성공

요청: 11월 29일 일요일 저녁 7시 이후에 시작해서 9시 반 전에 끝나는 3만원 이하 대학로 뮤지컬 찾아줘

| 구성 | 결과 | 재계획 (전략) | LLM (Worker) | 실제 Tool | 시간 | 검증·최종 판정 | 결과 요약 |
|---|---|---|---|---|---|---|---|
| baseline (필수 구조) | `ok` | 2 (expand_pool → drop_genre) | 3 (0) | 48 | 10.2초 | - · normal | 꿈깨 [대학로] |
| Planner·Worker · Worker LLM ON | `ok` | 2 (expand_pool → drop_genre) | 3 (0) | 48 | 12.9초 | normal/normal/normal · normal | 꿈깨 [대학로] |
| Planner·Worker · Worker LLM OFF | `ok` | 2 (expand_pool → drop_genre) | 3 (0) | 48 | 14.0초 | normal/normal/normal · normal | 꿈깨 [대학로] |

### C3. 재계획 상한

요청: 다음 주 수요일 오전 9시 이후에 시작해서 오전 11시 전에 끝나는 대학로 연극 있어?

| 구성 | 결과 | 재계획 (전략) | LLM (Worker) | 실제 Tool | 시간 | 검증·최종 판정 | 결과 요약 |
|---|---|---|---|---|---|---|---|
| baseline (필수 구조) | `limit_reached` | 3 (expand_pool → drop_genre → widen_region) | 3 (0) | 62 | 12.9초 | - · anomaly ['excessive_replan'] | - |
| Planner·Worker · Worker LLM ON | `limit_reached` | 3 (expand_pool → drop_genre → widen_region) | 3 (0) | 62 | 11.7초 | normal/normal/normal/anomaly · anomaly ['excessive_replan'] | - |
| Planner·Worker · Worker LLM OFF | `limit_reached` | 3 (expand_pool → drop_genre → widen_region) | 3 (0) | 62 | 17.2초 | normal/normal/normal/anomaly · anomaly ['excessive_replan'] | - |
- baseline (필수 구조) 로깅 Agent 진단(LLM): 문제는 Planner Agent에 있습니다. 후보가 없을 때마다 재계획 전략을 변경하며 3회 재계획 상한에 도달했습니다. 재계획 조건이나 전략을 개선해 불필요한 재계획을 줄여야 합니다.
- Planner·Worker · Worker LLM ON 로깅 Agent 진단(LLM): 문제는 Planner Agent에 있습니다. 후보가 없을 때마다 재계획을 반복하여 상한 3회를 초과했습니다. Planner가 재계획 조건과 전략을 개선해 재계획 횟수를 줄여야 합니다.
- Planner·Worker · Worker LLM OFF 로깅 Agent 진단(LLM): 경고 원인은 Planner가 후보가 없어서 재계획을 3회 시도한 점입니다. Planner가 후보 확보 전략을 개선하거나 재계획 횟수 제한을 조정해야 합니다. Worker와 로깅 Agent에는 문제 없습니다.

### C4. 공연명 오타 (Worker 인자 수정)

요청: 여신님 보고계셔 러닝타임이 몇 분이야?

| 구성 | 결과 | 재계획 (전략) | LLM (Worker) | 실제 Tool | 시간 | 검증·최종 판정 | 결과 요약 |
|---|---|---|---|---|---|---|---|
| baseline (필수 구조) | `no_match` | 0 (-) | 3 (0) | 1 | 3.3초 | - · normal | - |
| Planner·Worker · Worker LLM ON | `no_match` | 0 (-) | 5 (2) | 3 | 5.4초 | normal · normal | - |
| Planner·Worker · Worker LLM OFF | `no_match` | 0 (-) | 3 (0) | 1 | 4.1초 | normal · normal | - |
- Planner·Worker · Worker LLM ON Worker 판단: `retry` (LLM) search_performances NO_RESULT patch={"keyword": "여신님 보고 계셔 공연"} — 현재 키워드로 공연 검색 결과가 없으므로 키워드를 변경하여 다시 시도합니다.
- Planner·Worker · Worker LLM ON Worker 판단: `retry` (LLM) search_performances NO_RESULT patch={"keyword": "여신님 공연"} — 검색어를 조금 더 일반적으로 변경하여 공연을 다시 찾아봅니다.
- Planner·Worker · Worker LLM ON Worker 판단: `replan_request` (규칙) search_performances NO_RESULT — retry_limit
- Planner·Worker · Worker LLM OFF Worker 판단: `replan_request` (규칙) search_performances NO_RESULT — worker_llm_off

### C5. 후보 0건 장르 (Worker 계획 변경 요청)

요청: 11월 28일 토요일 저녁 6시 이후 대학로에서 서커스 보고 싶어. 9시 전에 끝나야 해

| 구성 | 결과 | 재계획 (전략) | LLM (Worker) | 실제 Tool | 시간 | 검증·최종 판정 | 결과 요약 |
|---|---|---|---|---|---|---|---|
| baseline (필수 구조) | `ok` | 2 (expand_pool → drop_genre) | 3 (0) | 21 | 10.1초 | - · normal | 타조소년들 [대학로], 단막극 낭독공연, 시선: Eleven Ways o |
| Planner·Worker · Worker LLM ON | `ok` | 2 (expand_pool → drop_genre) | 3 (0) | 21 | 8.6초 | normal/normal/normal · normal | 타조소년들 [대학로], 단막극 낭독공연, 시선: Eleven Ways o |
| Planner·Worker · Worker LLM OFF | `ok` | 2 (expand_pool → drop_genre) | 3 (0) | 21 | 7.7초 | normal/normal/normal · normal | 타조소년들 [대학로], 단막극 낭독공연, 시선: Eleven Ways o |

## 3. 실행 흐름 예 (C4)

- **baseline (필수 구조)**: analyze → plan → execute → judge → respond
- **Planner·Worker · Worker LLM ON**: analyze → plan → execute → verify → judge → respond
- **Planner·Worker · Worker LLM OFF**: analyze → plan → execute → verify → judge → respond
