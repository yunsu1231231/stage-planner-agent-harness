"""실제 LLM + 실제 API로 대표 요청 확인 (기본 제외, 비용 발생).
실행: .venv/Scripts/python -m pytest -m live tests/agents/test_live_agent.py -s
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def agent():
    from app.agents.graph import MainAgent
    from app.core.config import Settings
    from app.core.llm import make_llm
    from app.tools.factory import build_registry
    s = Settings.from_env()
    if not (s.llm_api_key and s.kopis_api_key and s.kakao_api_key):
        pytest.skip("키 없음")
    return MainAgent(llm=make_llm(s), registry=build_registry(s.kopis_api_key, s.kakao_api_key))


def show(res):
    print(f"\n[{res['status']}] replan={res['replan_count']} llm={res['llm_calls']} intent={res['intent']}")
    print({k: v["value"] for k, v in (res.get("conditions") or {}).items() if v})
    print(res["reply"][:600])


def test_live_s1_extracts_conditions_and_plans(agent):
    res = agent.run("live-s1", "이번 토요일 오후 2시 이후에 대학로에서 5만원 이하 연극 보고 6시 전에는 끝내고 싶어. 끝나고 갈 식당도 알려줘")
    show(res)
    c = {k: v["value"] for k, v in res["conditions"].items() if v}
    assert res["intent"]["value"] == "plan_performance"
    assert c["earliest_start"] == "14:00" and c["end_by"] == "18:00" and c["budget_max"] == 50000
    assert c["genre"] == "연극" and c["place_category"] == "restaurant"
    assert res["status"] in ("ok", "partial", "limit_reached", "no_match")
    assert 3 <= res["llm_calls"] <= 3


def test_live_followup_keeps_conditions(agent):
    res = agent.run("live-s1", "같은 날 뮤지컬로 바꿔줘")
    show(res)
    c = res["conditions"]
    assert c["genre"]["value"] == "뮤지컬" and c["genre"]["source"] == "user"
    assert c["date"]["source"] == "memory" and c["end_by"]["value"] == "18:00"


def test_live_clarify_and_chitchat(agent):
    r1 = agent.run("live-s6", "7시 전에 끝나야 해")
    show(r1)
    assert r1["status"] == "clarify" and r1["llm_calls"] == 1
    r2 = agent.run("live-s5", "안녕! 너는 뭘 할 수 있어?")
    show(r2)
    assert r2["status"] == "chat" and r2["llm_calls"] == 2
