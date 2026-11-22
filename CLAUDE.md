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

## 진행 방식
- 사용자와 단계별로 상호작용하며 진행한다. 단계마다 결정 사항을 제시하고 확인받은 뒤 다음으로 넘어간다.
- 구현 범위 동결 후에는 새 기능을 추가하지 않는다 (명세 3장).

## 환경
- Python은 **`.venv/Scripts/python`** (3.13) 만 사용한다. 시스템 기본 python은 3.9라 명세(3.10+) 미달.
- `requirements.txt` 버전은 명세 고정 버전이다. 변경 금지.
- LLM 설정은 `.env`의 `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` 로만 읽는다 (현재 개인 OpenAI 키, base_url 비움).

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
- **GitHub push는 사용자 승인 후에만** 진행한다. 커밋은 로컬에서 자유롭게 하되, push 전에는 반드시 묻는다.
