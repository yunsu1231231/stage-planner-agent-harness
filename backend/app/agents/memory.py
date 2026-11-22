"""F3010 대화 맥락 (docs/04 5절). 보관: 조건 슬롯·직전 추천 요약·최근 6턴. Tool 원본 응답은 보관하지 않는다."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

COND_KEYS = ("date", "earliest_start", "end_by", "budget_max", "age", "region", "genre", "place_category")
_REC_KEYS = ("performance_id", "title", "venue_id", "venue_name", "date", "start_time", "end_time", "min_price")


def merge_conditions(prev: dict[str, Any], delta: dict[str, Any], reset: bool = False
                     ) -> tuple[dict[str, Any], dict[str, str]]:
    """새로 말한(non-null) 값만 덮어쓴다. → (병합 결과, 항목별 출처 user|memory)"""
    base = {} if reset else {k: v for k, v in prev.items() if v is not None}
    sources = {k: "memory" for k in base}
    for k, v in delta.items():
        if v is not None:
            base[k], sources[k] = v, "user"
    return base, sources


@dataclass
class SessionMemory:
    conditions: dict[str, Any] = field(default_factory=dict)
    last_recommendations: list[dict[str, Any]] = field(default_factory=list)
    last_intent: str | None = None
    history: deque = field(default_factory=lambda: deque(maxlen=12))   # 6턴 = 발화 6 + 응답 6

    def add_turn(self, user: str, assistant: str) -> None:
        self.history.append({"role": "user", "text": user})
        self.history.append({"role": "assistant", "text": assistant})

    def remember_recommendations(self, recs: list[dict[str, Any]]) -> None:
        self.last_recommendations = [{"index": i, **{k: r.get(k) for k in _REC_KEYS}} for i, r in enumerate(recs, 1)]

    def summary(self) -> str:
        lines = [f"이전 조건: {self.conditions or '없음'}"]
        if self.last_recommendations:
            lines.append("직전 추천: " + "; ".join(f"{r['index']}번 {r['title']} {r['date']} {r['start_time']}"
                                                  for r in self.last_recommendations))
        if self.history:
            lines.append("최근 대화: " + " / ".join(f"{h['role']}: {h['text'][:60]}" for h in self.history))
        return "\n".join(lines)


class MemoryStore:
    """세션별 맥락. 프로세스 메모리 (서버 재시작 시 초기화 — docs/04 5절)."""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionMemory] = {}

    def get(self, session_id: str) -> SessionMemory:
        return self._sessions.setdefault(session_id, SessionMemory())

    def reset(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
