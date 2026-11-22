"""가짜 LLM 대본 조각 — analyze(structured) / plan(tool_calls) / respond(text)."""
from __future__ import annotations

from typing import Any

SEARCH, DETAIL, NEARBY = "search_performances", "get_performance_detail", "search_nearby_places"


def analyze(intent: str, reason: str = "테스트 분류", **conditions: Any) -> dict:
    """AnalyzeOutput 대본. 명시하지 않은 조건은 null."""
    return {"intent": intent, "reason": reason, **conditions}


def plan(*tools: str) -> list[dict]:
    """plan 노드의 bind_tools 응답 — LLM이 고른 Tool 목록 (인자는 일부러 엉뚱하게: 코드가 채워야 함)."""
    return [{"name": t, "args": {"date": "1999-01-01"} if t == SEARCH else {}} for t in tools]


S1_ANALYZE = analyze("plan_performance", "날짜·시간·예산 조건과 함께 공연 추천 요청",
                     date="2026-11-28", earliest_start="14:00", end_by="18:00", budget_max=50000,
                     region="대학로", genre="연극", place_category="restaurant")
S2_ANALYZE = analyze("plan_performance", date="2026-11-29", earliest_start="19:00", end_by="21:00",
                     budget_max=30000, region="대학로", genre="뮤지컬")
S3_ANALYZE = analyze("plan_performance", date="2026-11-25", earliest_start="09:00", end_by="11:00",
                     region="대학로", genre="연극")
