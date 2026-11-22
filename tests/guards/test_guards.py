"""L6 가드 테스트 — 구조·보안 불변 규칙 (CLAUDE.md '불변 규칙', NF3001·NF3006, F3013).

구현이 진행되어도 항상 참이어야 하는 규칙. 하나라도 깨지면 커밋·push 가 hook 에서 막힌다.
"""
from __future__ import annotations

import ast
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend" / "app"

# 명세 1.2-5) 필수 라이브러리 고정 버전
SPEC_PINS = {
    "langgraph": "1.2.10", "langchain": "1.3.14", "langchain-openai": "1.4.3", "langchain-core": "1.6.0",
    "langchain-text-splitters": "1.1.2", "openai": "2.54.0", "python-dotenv": "1.2.3", "requests": "2.34.2",
    "langsmith": "0.10.17", "typing-extensions": "4.16.0", "fastapi": "0.141.1", "uvicorn[standard]": "0.52.4",
    "pydantic": "2.13.5", "google-api-python-client": "2.201.0", "google-auth-oauthlib": "1.5.0",
    "google-auth-httplib2": "0.4.3", "chromadb": "1.5.9",
}

# LLM을 쓰면 안 되는 구역 (F3013: 로깅 Agent의 수집·저장, 저장소, 이벤트 버스)
NO_LLM_ZONE = ["agents/logging_agent.py", "agents/anomaly.py", "events", "storage"]   # F3020 판정도 규칙
LLM_MODULE_PREFIXES = ("openai", "langchain_openai", "langchain", "langchain_core.language_models", "app.core.llm")

SECRET_PATTERNS = [
    re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}"),          # OpenAI 키
    re.compile(r"KakaoAK\s+[0-9a-f]{32}"),                   # 카카오 REST 키가 박힌 헤더
    re.compile(r"service=[0-9a-f]{32}"),                     # KOPIS 키가 박힌 URL
]


def _git(*args: str) -> list[str]:
    if not shutil.which("git"):
        pytest.skip("git 없음")
    out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True)
    return [p for p in out.stdout.decode("utf-8", "ignore").split("\0") if p]


def _repo_files() -> list[Path]:
    """추적 중이거나 커밋될 수 있는(ignore 안 된) 파일."""
    return [ROOT / p for p in _git("ls-files", "-z", "--cached", "--others", "--exclude-standard")
            if (ROOT / p).is_file()]


# ---------------------------------------------------------------- 버전 고정
def test_requirements_match_spec_pins():
    pins = {}
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if line:
            name, _, ver = line.partition("==")
            pins[name.strip()] = ver.strip()
    assert pins == SPEC_PINS, "requirements.txt 는 명세 고정 버전과 정확히 같아야 한다"


# ---------------------------------------------------------------- 비밀 정보 (NF3001)
def test_env_example_has_no_secret_values():
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        if re.match(r"^\s*[A-Z_]*KEY\s*=", line):
            assert line.split("=", 1)[1].strip() == "", f".env.example 에 키 값이 들어 있음: {line.split('=')[0]}"


def test_sensitive_paths_are_gitignored():
    if not shutil.which("git"):
        pytest.skip("git 없음")
    for path in [".env", ".venv/x", "docs/spec.pdf", ".claude/settings.local.json"]:
        rc = subprocess.run(["git", "check-ignore", "-q", path], cwd=ROOT).returncode
        assert rc == 0, f"{path} 가 .gitignore 에 걸리지 않음"


def test_no_secrets_in_repo_files():
    from dotenv import dotenv_values

    env_path = ROOT / ".env"
    actual = [v for k, v in (dotenv_values(env_path) if env_path.exists() else {}).items() if k.endswith("KEY") and v]
    hits = []
    for f in _repo_files():
        text = f.read_bytes().decode("utf-8", "ignore")
        if any(s in text for s in actual) or any(p.search(text) for p in SECRET_PATTERNS):
            hits.append(str(f.relative_to(ROOT)))
    assert not hits, f"키로 보이는 문자열이 포함된 파일: {hits}"


# ---------------------------------------------------------------- 로깅 Agent LLM 금지 (F3013)
def _imports(py: Path) -> set[str]:
    tree = ast.parse(py.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_logging_zone_does_not_import_llm():
    files = []
    for entry in NO_LLM_ZONE:
        p = BACKEND / entry
        files += [p] if p.is_file() else list(p.rglob("*.py")) if p.is_dir() else []
    bad = {str(f.relative_to(ROOT)): sorted(m for m in _imports(f) if m.startswith(LLM_MODULE_PREFIXES))
           for f in files}
    bad = {k: v for k, v in bad.items() if v}
    assert not bad, f"LLM 금지 구역에서 LLM 모듈 import: {bad}"


# ---------------------------------------------------------------- 브라우저 위장 금지 (결정 D7)
def test_no_browser_user_agent_impersonation():
    offenders = [str(f.relative_to(ROOT)) for f in BACKEND.rglob("*.py")
                 if re.search(r"Mozilla/\d", f.read_text(encoding="utf-8"))]
    assert not offenders, f"브라우저 User-Agent 위장 금지: {offenders}"


# ---------------------------------------------------------------- 모듈 분리 (NF3006)
def test_frontend_and_backend_are_separate_trees():
    assert BACKEND.is_dir()
    frontend = ROOT / "frontend"
    if frontend.exists():
        assert not list(frontend.rglob("*.py")), "프론트엔드 트리에 Python 코드가 섞임"
