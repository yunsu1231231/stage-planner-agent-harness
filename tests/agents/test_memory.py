"""L1 — F3010 대화 맥락: 바뀐 조건만 갱신, 원본 Tool 응답 미보관."""
from __future__ import annotations

from app.agents.memory import MemoryStore, merge_conditions


def test_merge_updates_only_changed_and_tracks_source():
    prev = {"date": "2026-11-28", "earliest_start": "14:00", "genre": "연극", "budget_max": 50000}
    merged, src = merge_conditions(prev, {"genre": "뮤지컬", "date": None})
    assert merged == {**prev, "genre": "뮤지컬"}
    assert src["genre"] == "user" and src["date"] == "memory" and src["budget_max"] == "memory"


def test_reset_drops_previous_conditions():
    merged, src = merge_conditions({"genre": "연극", "region": "대학로"}, {"genre": "뮤지컬"}, reset=True)
    assert merged == {"genre": "뮤지컬"} and src == {"genre": "user"}


def test_history_keeps_last_six_turns_and_no_raw_tool_payloads():
    store = MemoryStore()
    m = store.get("s")
    for i in range(10):
        m.add_turn(f"q{i}", f"a{i}")
    assert len(m.history) == 12 and m.history[0]["text"] == "q4"
    m.remember_recommendations([{"performance_id": "PF1", "title": "T", "venue_id": "FC1", "venue_name": "V",
                                 "date": "2026-11-28", "start_time": "15:00", "end_time": "16:40",
                                 "min_price": 40000, "criteria": "...", "evidence": ["x"], "places": [{"name": "p"}]}])
    rec = m.last_recommendations[0]
    assert rec["index"] == 1 and "places" not in rec and "evidence" not in rec    # 요약만 보관
    assert store.get("s") is m and store.get("other") is not m
    store.reset("s")
    assert store.get("s").conditions == {}
