"""Claude Code hook — 검증 게이트 (docs/06 4절, CLAUDE.md 테스트 규칙).

  stop     : Claude가 작업을 끝내려 할 때. 코드(.py 등) 변경이 있으면 pytest 실행,
             실패하면 exit 2 로 종료를 막고 실패 내용을 Claude에게 돌려준다.
  pretool  : Bash 실행 직전. 명령에 `git commit` / `git push` 가 있으면 pytest 실행,
             실패하면 exit 2 로 그 명령을 막는다 ("검증 완료 후에만 커밋/푸시").

stdin 으로 hook 입력 JSON 을 받는다. 다른 Bash 명령에는 즉시 통과(exit 0).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
PY = str(VENV_PY if VENV_PY.exists() else Path(sys.executable))
CODE_PATTERN = re.compile(r"\.(py|ini|txt|toml|cfg)$|^(backend|tests|scripts)/")
GIT_GATED = re.compile(r"\bgit\s+(commit|push)\b")


def read_input() -> dict:
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}


def code_changed() -> bool:
    out = subprocess.run(["git", "status", "--porcelain", "-z", "-uall"], cwd=ROOT, capture_output=True)
    entries = [e[3:] for e in out.stdout.decode("utf-8", "ignore").split("\0") if len(e) > 3]
    return any(CODE_PATTERN.search(p.replace("\\", "/")) for p in entries)


def run_pytest() -> tuple[int, str]:
    try:
        proc = subprocess.run([PY, "-m", "pytest", "-q", "-x", "--no-header"], cwd=ROOT,
                              capture_output=True, timeout=600)
    except subprocess.TimeoutExpired:
        return 1, "pytest 시간 초과 (600s)"
    text = (proc.stdout + proc.stderr).decode("utf-8", "replace")
    return proc.returncode, text


def block(reason: str, output: str) -> None:
    tail = "\n".join(output.strip().splitlines()[-40:])
    sys.stderr.write(f"[harness gate] {reason}\n--- pytest (마지막 40줄) ---\n{tail}\n")
    sys.exit(2)


def main() -> None:
    for stream in (sys.stdout, sys.stderr):   # Windows 콘솔(cp949)에서도 한글이 깨지지 않게
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    data = read_input()

    if mode == "stop":
        if data.get("stop_hook_active"):   # 이미 한 번 막았으면 무한 루프 방지
            sys.exit(0)
        if not code_changed():
            sys.exit(0)
        rc, out = run_pytest()
        if rc != 0:
            block("코드 변경이 있는데 pytest 가 실패했습니다. 고친 뒤 종료하세요.", out)
        sys.exit(0)

    if mode == "pretool":
        command = (data.get("tool_input") or {}).get("command", "")
        if not GIT_GATED.search(command):
            sys.exit(0)
        rc, out = run_pytest()
        if rc != 0:
            block("pytest 실패 — 검증이 끝나기 전에는 commit/push 할 수 없습니다 (CLAUDE.md).", out)
        sys.exit(0)

    sys.exit(0)


if __name__ == "__main__":
    main()
