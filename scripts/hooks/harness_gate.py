"""Claude Code hook — 검증 게이트 (docs/06 4절, CLAUDE.md 테스트 규칙).

  pretool : Bash 실행 직전. 명령에 `git commit` / `git push` 가 있으면 **항상** 전체 pytest,
            실패하면 exit 2 로 그 명령을 막는다 ("검증 완료 후에만 커밋/푸시").
  stop    : Claude가 응답을 끝내려 할 때. **마지막으로 통과한 이후 코드가 바뀐 경우에만** pytest.
            - 코드 변경 없음(질의응답만 한 턴)            → 건너뜀
            - 변경은 있지만 지난 통과 때와 내용이 같음   → 건너뜀
            - 새 변경 + 실패                            → exit 2 로 종료를 막고 실패 내용을 돌려줌 (1회)

"코드 변경"의 기준: git 작업 트리에서 바뀐(추적·미추적) 코드 파일들의 경로+내용 해시.
통과 시 그 해시를 .claude/harness/state.json 에 저장하고, 모든 판단은 .claude/harness/gate.log 에 남긴다.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
PY = str(VENV_PY if VENV_PY.exists() else Path(sys.executable))
STATE_DIR = ROOT / ".claude" / "harness"
STATE = STATE_DIR / "state.json"
LOG = STATE_DIR / "gate.log"
CODE_PATTERN = re.compile(r"(^(backend|tests|scripts)/)|(\.(py|ini|toml|cfg)$)|(^requirements[\w-]*\.txt$)|(^\.claude/settings\.json$)")
GIT_GATED = re.compile(r"\bgit\s+(commit|push)\b")


# ---------------------------------------------------------------- utils
def read_input() -> dict:
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}


def log(mode: str, decision: str, **extra) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    rec = {"ts": datetime.now().isoformat(timespec="seconds"), "mode": mode, "decision": decision, **extra}
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_pass(fingerprint: str | None) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({"last_pass_fingerprint": fingerprint,
                                 "last_pass_at": datetime.now().isoformat(timespec="seconds")}), encoding="utf-8")


def changed_code_files() -> list[str]:
    out = subprocess.run(["git", "status", "--porcelain", "-z", "-uall"], cwd=ROOT, capture_output=True)
    paths = []
    for entry in out.stdout.decode("utf-8", "ignore").split("\0"):
        if len(entry) > 3:
            p = entry[3:].replace("\\", "/")
            if CODE_PATTERN.search(p):
                paths.append(p)
    return sorted(set(paths))


def fingerprint(paths: list[str]) -> str | None:
    if not paths:
        return None
    h = hashlib.sha256()
    for p in paths:
        f = ROOT / p
        h.update(p.encode())
        h.update(f.read_bytes() if f.is_file() else b"<deleted>")
    return h.hexdigest()


def run_pytest() -> tuple[int, str, float]:
    t0 = time.perf_counter()
    try:
        proc = subprocess.run([PY, "-m", "pytest", "-q", "-x", "--no-header"], cwd=ROOT,
                              capture_output=True, timeout=600)
        rc, text = proc.returncode, (proc.stdout + proc.stderr).decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        rc, text = 1, "pytest 시간 초과 (600s)"
    return rc, text, round(time.perf_counter() - t0, 2)


def summary(text: str) -> str:
    lines = [l for l in text.strip().splitlines() if l.strip()]
    return lines[-1] if lines else ""


def block(reason: str, output: str) -> None:
    tail = "\n".join(output.strip().splitlines()[-40:])
    sys.stderr.write(f"[harness gate] {reason}\n--- pytest (마지막 40줄) ---\n{tail}\n")
    sys.exit(2)


# ---------------------------------------------------------------- modes
def on_stop(data: dict) -> None:
    if data.get("stop_hook_active"):                   # 이미 한 번 막았으면 무한 루프 방지
        log("stop", "skip:stop_hook_active")
        return
    paths = changed_code_files()
    fp = fingerprint(paths)
    if fp is None:
        log("stop", "skip:no_code_change")
        return
    if fp == load_state().get("last_pass_fingerprint"):
        log("stop", "skip:unchanged_since_last_pass", files=len(paths))
        return
    rc, out, sec = run_pytest()
    log("stop", "pass" if rc == 0 else "block", files=len(paths), seconds=sec, result=summary(out))
    if rc != 0:
        block("마지막 통과 이후 코드가 바뀌었는데 pytest 가 실패했습니다. 고친 뒤 종료하세요.", out)
    save_pass(fp)


def on_pretool(data: dict) -> None:
    command = (data.get("tool_input") or {}).get("command", "")
    if not GIT_GATED.search(command):
        return                                          # 일반 Bash 명령은 기록 없이 통과
    action = GIT_GATED.search(command).group(1)
    rc, out, sec = run_pytest()
    log("pretool", "pass" if rc == 0 else "block", action=action, seconds=sec, result=summary(out))
    if rc != 0:
        block(f"pytest 실패 — 검증이 끝나기 전에는 git {action} 할 수 없습니다 (CLAUDE.md).", out)
    save_pass(fingerprint(changed_code_files()))


def main() -> None:
    for stream in (sys.stdout, sys.stderr):            # Windows 콘솔(cp949)에서도 한글이 깨지지 않게
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    data = read_input()
    if mode == "stop":
        on_stop(data)
    elif mode == "pretool":
        on_pretool(data)
    sys.exit(0)


if __name__ == "__main__":
    main()
