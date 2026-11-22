"""KOPIS 자유 텍스트 파서 (docs/02 6.1). 해석하지 못하면 None — 값을 지어내지 않는다."""
from __future__ import annotations

import re

WEEKDAYS = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]
_SEGMENT = re.compile(r"([^(),]+?)\s*\(([^)]*)\)")
_RANGE = re.compile(r"^(\S+요일)\s*~\s*(\S+요일)$")
_TIME = re.compile(r"\b(\d{1,2}):(\d{2})\b")


def parse_runtime(raw: str | None) -> int | None:
    """'1시간 10분' → 70, '100분' → 100, '2시간' → 120. 첫 '시간'과 첫 '분'만 사용."""
    s = raw or ""
    h = re.search(r"(\d+)\s*시간", s)
    m = re.search(r"(\d+)\s*분", s)
    if not h and not m:
        return None
    total = (int(h.group(1)) * 60 if h else 0) + (int(m.group(1)) if m else 0)
    return total or None


def parse_price(raw: str | None) -> int | None:
    """등급별 금액 중 최솟값. 금액이 없고 '무료'만 있으면 0."""
    s = raw or ""
    amounts = [int(x.replace(",", "")) for x in re.findall(r"(\d[\d,]*)\s*원", s)]
    if amounts:
        return min(amounts)
    return 0 if "무료" in s else None


def parse_schedule(raw: str | None) -> dict[str, list[str]] | None:
    """'화요일 ~ 금요일(19:30), 토요일(14:00,18:00), HOL(14:00)' → {요일: [HH:MM, ...]}.
    해석 못 한 구간은 버리고, 남는 것이 없으면 None."""
    out: dict[str, set[str]] = {}
    for days, times in _SEGMENT.findall(raw or ""):
        days = days.strip()
        ts = {f"{int(h):02d}:{m}" for h, m in _TIME.findall(times)}
        if not ts:
            continue
        rng = _RANGE.match(days)
        if rng and rng.group(1) in WEEKDAYS and rng.group(2) in WEEKDAYS:
            a, b = WEEKDAYS.index(rng.group(1)), WEEKDAYS.index(rng.group(2))
            keys = WEEKDAYS[a:b + 1] if a <= b else WEEKDAYS[a:] + WEEKDAYS[:b + 1]
        elif days in WEEKDAYS:
            keys = [days]
        elif days.upper().startswith("HOL"):
            keys = ["HOL"]
        else:
            keys = []
        for k in keys:
            out.setdefault(k, set()).update(ts)
    return {k: sorted(v) for k, v in out.items()} or None


def parse_kopis_date(raw: str | None) -> str | None:
    """'2026.11.21' → '2026-11-21'"""
    m = re.match(r"^\s*(\d{4})\.(\d{2})\.(\d{2})", raw or "")
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None
