"""기획 검증(명세 2.7)용 공통 유틸. 제품 코드가 아니다.

- .env 로딩
- 실제 응답을 docs/validation/samples/ 에 저장 (키는 마스킹)
- 결과 요약을 docs/validation/results.json 에 누적
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "docs" / "validation" / "samples"
RESULTS = ROOT / "docs" / "validation" / "results.json"

load_dotenv(ROOT / ".env")
SAMPLES.mkdir(parents=True, exist_ok=True)

# Windows 콘솔 한글 출력
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def env(name: str) -> str | None:
    v = os.getenv(name, "").strip()
    return v or None


def mask(text: str, *secrets: str | None) -> str:
    for s in secrets:
        if s:
            text = text.replace(s, "***")
    return text


def save_sample(name: str, body: str, *secrets: str | None) -> Path:
    path = SAMPLES / name
    path.write_text(mask(body, *secrets), encoding="utf-8")
    return path


def record(check_id: str, ok: bool, note: str = "", **extra) -> None:
    """검증 결과를 results.json 에 누적한다 (같은 ID는 덮어씀)."""
    data = {}
    if RESULTS.exists():
        data = json.loads(RESULTS.read_text(encoding="utf-8"))
    data[check_id] = {
        "ok": ok,
        "note": note,
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        **extra,
    }
    RESULTS.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {check_id}: {note}")
