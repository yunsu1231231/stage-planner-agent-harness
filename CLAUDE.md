# CLAUDE.md

공연 관람 플래너 — SSAFY AI 코어 프로젝트 3회차 (Agent 기반 도메인 플래너 서비스).
원본 명세: `docs/AI코어프로젝트_3회차_요구사항정의서.pdf`

## 기준 문서 (Single Source of Truth)
구현은 아래 문서를 따른다. 구현이 문서와 달라져야 하면 **문서를 먼저 고친다**.

| 문서 | 내용 |
|---|---|
| `docs/00_project_plan.md` | 결정 로그, 일정, 하네스 방침 |
| `docs/01_requirements.md` | 요구사항 정의서 (F3001~, NF3001~) |
| `docs/02_tool_spec.md` | Tool 정의서, 실패 코드, 외부 API 호출 규약 |
| `docs/03_planning_validation.md` | 기획 검증 결과, 설계 변경 이력 |
| `docs/04_agent_design.md` | LangGraph 노드·상태, 판단 계산식, 재계획, Memory, 이벤트, 모듈 구조 |
| `docs/05_api_spec.md` | 백엔드 API 경로·요청·응답, SQLite 스키마, 화면 구성 |
| `docs/06_test_strategy.md` | 테스트 계층(L1~L6), 명세 4장 → 테스트 추적표, 개발 루프 |

## 테스트 규칙
- **테스트 먼저**: 기능을 구현하기 전에 `docs/06_test_strategy.md` 추적표의 해당 테스트를 작성하고 실패(Red)를 확인한다.
- 테스트는 **명세 문서에서 도출**한다. 구현 코드에 맞춰 테스트를 고치지 않는다. 명세가 틀렸다면 문서를 먼저 고친다.
- 기본 `pytest`는 오프라인·결정적이어야 한다: 외부 API는 `tests/fixtures/`의 녹화 응답, LLM은 가짜 LLM을 주입한다.
- 실제 API·LLM 호출 테스트는 `@pytest.mark.live`로 표시하고 `pytest -m live`로만 실행한다.
- **완료 기준 = `.venv/Scripts/python -m pytest` 전체 통과.** 실패 상태로 커밋하지 않는다.

## 진행 방식
- 사용자와 단계별로 상호작용하며 진행한다. 단계마다 결정 사항을 제시하고 확인받은 뒤 다음으로 넘어간다.
- 구현 범위 동결 후에는 새 기능을 추가하지 않는다 (명세 3장).

## 환경
- Python은 **`.venv/Scripts/python`** (3.13) 만 사용한다. 시스템 기본 python은 3.9라 명세(3.10+) 미달.
- `requirements.txt` 버전은 명세 고정 버전이다. 변경 금지.
- LLM 설정은 `.env`의 `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` 로만 읽는다 (현재 개인 OpenAI 키, base_url 비움).
- 서버 실행: `.venv/Scripts/python -m uvicorn app.main:app --app-dir backend --port 8000` (문서 `/docs`, DB `data/planner.db`)
- 테스트: `.venv/Scripts/python -m pytest` (오프라인) / `-m live` (실제 API·LLM, 비용 발생 — 필요할 때만)

## 불변 규칙 (명세 유래)
- Tool은 예외를 밖으로 던지지 않는다. 항상 `{ok, data | error{code, message}}` 공통 형식으로 반환한다.
- 외부 API로 확인할 수 없는 값은 지어내지 않는다. 비어 있으면 실패 코드로 남기고 판단에서 제외한다.
- 로깅 Agent의 이벤트 수집·저장에는 LLM을 쓰지 않는다. 이벤트 발행은 구독자에 의존하지 않는다.
- 실행 로그는 수정 API를 두지 않는다 (목록·상세·삭제만).
- 재계획에는 상한(3회)이 있다.
- KOPIS 호출에는 자체 식별 User-Agent `ai-planner/0.1 (SSAFY AI core project)` 를 쓴다. 브라우저로 위장하지 않는다.
- API 키를 코드·문서·화면·로그에 노출하지 않는다 (NF3001, NF3002). 검증 샘플 저장 시 키는 마스킹한다.

## Git 커밋 규칙
- **의미 있는 작업 단위별로** 커밋한다. 여러 관심사를 한 커밋에 섞지 않는다.
- **구현 및 검증이 완료된 시점에** 커밋한다. 테스트·검증이 실패한 상태로 커밋하지 않는다.
- 커밋 메시지는 **Conventional Commits** 형식을 사용한다.
  - `type(scope): 요약` — type: `feat` `fix` `docs` `test` `refactor` `chore` `build` `ci` `perf` `style`
  - 예: `feat(tools): add KOPIS performance search tool`, `docs(validation): record API call results`
  - 요약은 한국어·영어 모두 가능, 본문에 이유와 관련 요구사항 번호(F30xx)를 적는다.
- **API 키, `.env`, `.venv`는 커밋하지 않는다.** `.env.example` 에는 실제 값을 넣지 않는다.
- **커밋 전 변경 사항을 확인한다**: `git status` 와 `git diff --staged` 로 스테이징 내용을 검토하고, 키 문자열이 섞이지 않았는지 확인한다. `git add -A` / `git add .` 대신 파일을 명시해 스테이징한다.
- **GitHub push는 Claude가 자율적으로 진행해도 된다** (사용자 위임, 2026-11-22). 단, push 전에 반드시:
  1. `pytest` 전체 통과 (hook이 `git push` 직전에 자동 실행해 실패 시 차단)
  2. 키 노출 없음 (가드 테스트 `test_no_secrets_in_repo_files`)
  3. `docs/*.pdf`(대외비 명세서)가 추적되지 않음
  - force push, 히스토리 재작성, 원격 브랜치 삭제는 여전히 사용자 승인 필요.

## 하네스 (자동 검증 장치)
| 장치 | 위치 | 동작 |
|---|---|---|
| 가드 테스트 (L6) | `tests/guards/` | 버전 고정, 키 노출, 로깅 구역 LLM import, 브라우저 UA 위장, 모듈 분리 |
| 하네스 자체 테스트 | `tests/harness/` | FakeLLM·FakeSession·네트워크 차단이 의도대로 동작하는지 |
| 가짜 LLM / HTTP | `tests/fakes/` | 대본 기반 LLM, fixture 기반 HTTP. 대본·route 밖 호출은 실패 |
| 네트워크 차단 | `tests/conftest.py` | `live` 마커 없는 테스트에서 실제 소켓 연결 금지 |
| hook: PreToolUse(Bash) | `.claude/settings.json` → `scripts/hooks/harness_gate.py pretool` | `git commit`/`git push` 직전 pytest, 실패 시 차단 |
| hook: Stop | 〃 `stop` | **마지막 통과 이후 코드가 바뀐 경우에만** 종료 전 pytest (질의응답 턴은 건너뜀), 실패 시 종료 차단(1회) |
| hook 기록 | `.claude/harness/gate.log`, `state.json` (git 제외) | 모든 판단(pass/block/skip 사유)을 JSON 한 줄씩 기록. 마지막 통과 시점의 코드 해시 보관 |
