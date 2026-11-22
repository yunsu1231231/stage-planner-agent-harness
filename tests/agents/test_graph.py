"""L3 — 메인 Agent 실행 흐름 F3005~F3011 (명세 4.2 확인 항목). 가짜 LLM + FakeWorld + 실제 Tool 코드."""
from __future__ import annotations

import requests

from agents.scripts import DETAIL, NEARBY, S1_ANALYZE, S2_ANALYZE, S3_ANALYZE, SEARCH, analyze, plan
from agents.world import SAT, FakeWorld, Show, s1_world, s2_world, s3_world
from app.agents.memory import MemoryStore
from fakes import FakeResponse


def types(events, t):
    return [e for e in events if e["type"] == t]


# ---------------------------------------------------------------- 구조
def test_graph_has_analyze_plan_execute_judge_respond(make_agent):
    agent, _, _ = make_agent(s1_world())
    nodes = set(agent.graph.get_graph().nodes) - {"__start__", "__end__"}
    assert nodes == {"analyze", "plan", "execute", "judge", "respond"}


# ---------------------------------------------------------------- S1: 한 번에 충족 (F3005~F3008, F3011, F3004)
def test_s1_recommends_with_criteria_exclusions_and_places(make_agent):
    world = s1_world()
    agent, llm, events = make_agent(world, S1_ANALYZE, plan(SEARCH, DETAIL, NEARBY), "추천 문장")
    res = agent.run("s1", "토요일 2시 이후 대학로에서 5만원 이하 연극, 6시 전에 끝나야 해. 끝나고 갈 식당도")

    assert res["status"] == "ok" and res["reply"] == "추천 문장" and res["replan_count"] == 0
    # F3005 조건 추출 + 출처
    c = res["conditions"]
    assert c["date"] == {"value": SAT, "source": "user"} and c["end_by"]["value"] == "18:00"
    assert c["age"] is None                                           # 말하지 않은 조건은 비움
    # F3008/F3011 추천 + 판단 기준 + 근거
    [rec] = res["recommendations"]
    assert (rec["performance_id"], rec["start_time"], rec["end_time"]) == ("PFA1", "15:00", "16:40")
    assert "100분" in rec["criteria"] and rec["evidence"] == ["get_performance_detail(PFA1)"]
    # F3004 보조 정보가 추천 공연장 기준으로 붙음
    assert rec["places"][0]["name"] == "혜화 국밥"
    # 제외·판단 불가 사유
    reasons = {e["performance_id"]: e["reason_code"] for e in res["excluded"] + res["unjudgeable"]}
    assert reasons == {"PFA2": "TIME_MISMATCH", "PFA3": "NO_RUNTIME", "PFA4": "NO_SCHEDULE",
                       "PFA5": "OVER_BUDGET", "PFA6": "NO_SHOW_ON_DAY"}
    assert next(u for u in res["unjudgeable"] if u["performance_id"] == "PFA4")["latest_start"] == "16:50"
    assert llm.call_count == 3                                        # analyze, plan, respond


def test_tool_args_come_from_conditions_not_llm(make_agent):
    world = s1_world()
    agent, _, events = make_agent(world, S1_ANALYZE, plan(SEARCH, DETAIL, NEARBY), "ok")
    agent.run("s1", "...")
    p = world.list_calls()[0]
    assert p["stdate"] == "20261128" and p["signgucodesub"] == "1111" and p["shcate"] == "AAAA"   # 1999-01-01 무시
    created = types(events, "plan.created")[0]["payload"]
    assert [t["tool"] for t in created["tasks"]] == [SEARCH, DETAIL, NEARBY]
    assert "date" in created["tasks"][0]["fixed_args"]


def test_detail_uses_ids_from_search_and_nearby_uses_venue_from_detail(make_agent):
    world = s1_world()
    agent, _, events = make_agent(world, S1_ANALYZE, plan(SEARCH, DETAIL, NEARBY), "ok")
    agent.run("s1", "...")
    tool_seq = [(e["payload"]["tool"], e["payload"]["args"]) for e in types(events, "tool.request")]
    assert tool_seq[0][0] == SEARCH
    detail_ids = {a["performance_id"] for t, a in tool_seq if t == DETAIL}
    assert detail_ids == {"PFA1", "PFA2", "PFA3", "PFA4", "PFA5", "PFA6"}       # 뮤지컬 PFM9 는 후보 아님
    assert (NEARBY, {"venue_id": "FC001", "category": "restaurant"}) in tool_seq


# ---------------------------------------------------------------- F3006 Tool 필요/불필요 계획
def test_chitchat_skips_plan_and_tools(make_agent):
    world = s1_world()
    agent, llm, events = make_agent(world, analyze("chitchat", "인사"), "안녕하세요! 공연 조건을 알려주세요.")
    res = agent.run("s1", "안녕")
    assert res["status"] == "chat" and world.session.calls == []
    assert "plan" not in [e["node"] for e in types(events, "node.enter")]
    assert llm.call_count == 2


def test_nearby_not_planned_when_user_did_not_ask(make_agent):
    world = s1_world()
    no_food = {**S1_ANALYZE, "place_category": None}
    agent, _, events = make_agent(world, no_food, plan(SEARCH, DETAIL, NEARBY), "ok")
    res = agent.run("s1", "...")
    created = types(events, "plan.created")[0]["payload"]
    assert NEARBY not in [t["tool"] for t in created["tasks"]]
    assert types(events, "plan.corrected")[0]["payload"]["removed"] == [NEARBY]
    assert world.session.calls_to("kakao") == [] and res["recommendations"][0]["places"] == []


def test_plan_corrects_llm_that_omits_or_invents_tools(make_agent):
    world = s1_world()
    agent, _, events = make_agent(world, S1_ANALYZE, [{"name": SEARCH}], "ok")
    agent.run("s1", "...")
    corrected = types(events, "plan.corrected")[0]["payload"]
    assert set(corrected["added"]) == {DETAIL, NEARBY}


# ---------------------------------------------------------------- 되묻기 (S6)
def test_clarify_before_any_tool_when_start_point_missing(make_agent):
    world = s1_world()
    agent, llm, _ = make_agent(world, analyze("plan_performance", end_by="19:00"))
    res = agent.run("s1", "7시 전에 끝나야 해")
    assert res["status"] == "clarify" and set(res["missing"]) == {"date", "earliest_start"}
    assert world.session.calls == [] and llm.call_count == 1          # 되묻기 응답은 템플릿
    assert "관람 날짜" in res["reply"] and "시작 시각" in res["reply"]
    assert "을(를)" not in res["reply"]                                # V6 실측: 어색한 조사 제거


# ---------------------------------------------------------------- F3007 Tool 실패 후 진행
def test_one_detail_failure_is_recorded_and_flow_continues(make_agent):
    world = s1_world()
    world.detail_failures["PFA2"] = requests.ConnectionError("reset")
    agent, _, _ = make_agent(world, S1_ANALYZE, plan(SEARCH, DETAIL, NEARBY), "ok")
    res = agent.run("s1", "...")
    assert res["status"] == "partial" and res["recommendations"][0]["performance_id"] == "PFA1"
    assert {"tool": DETAIL, "target": "PFA2", "code": "UPSTREAM_ERROR"} in res["tool_failures"]
    assert any("상세" in n["message"] and "제외" in n["message"] for n in res["notices"])


def test_nearby_failure_is_reported_as_failure_not_as_no_places(make_agent):
    """V4 실측에서 발견: 주변 장소 조회 실패를 '후보 제외'·'식당 없음'으로 잘못 안내."""
    world = s1_world()
    world.kakao_status = 401
    agent, _, _ = make_agent(world, S1_ANALYZE, plan(SEARCH, DETAIL, NEARBY), "ok")
    res = agent.run("s1", "...")
    assert res["status"] == "partial" and res["recommendations"][0]["performance_id"] == "PFA1"
    msgs = " ".join(n["message"] for n in res["notices"])
    assert "주변 장소" in msgs and "실패" in msgs and "제외" not in msgs
    assert res["recommendations"][0]["places_status"] == "failed"


def test_missing_key_stops_without_replan_and_guides_setup(make_agent):
    world = s1_world()
    agent, llm, events = make_agent(world, S1_ANALYZE, plan(SEARCH, DETAIL), registry=world.registry(kopis_key=None))
    res = agent.run("s1", "...")
    assert res["status"] == "config_missing" and res["replan_count"] == 0
    assert types(events, "replan") == [] and llm.call_count == 2      # 응답은 템플릿 (키 이름만 안내)
    assert "KOPIS" in res["reply"]


# ---------------------------------------------------------------- F3009 재계획
def test_s2_replans_until_genre_relaxed_and_reuses_results(make_agent):
    world = s2_world()
    agent, llm, events = make_agent(world, S2_ANALYZE, plan(SEARCH, DETAIL), "ok")
    res = agent.run("s2", "일요일 7시 이후 9시 전에 끝나는 3만원 이하 뮤지컬")
    assert res["status"] == "ok" and res["replan_count"] == 2
    assert [e["payload"]["strategy"] for e in types(events, "replan")] == ["expand_pool", "drop_genre"]
    assert res["recommendations"][0]["performance_id"] == "PFB1"
    assert res["relaxed"] == ["genre"] and any("장르" in n["message"] for n in res["notices"])
    assert all(world.detail_calls(pid) == 1 for pid in ["PFM1", "PFM2", "PFB1", "PFB2"])   # 재조회 없음
    detail_requests = [e["payload"]["args"]["performance_id"] for e in types(events, "tool.request")
                       if e["payload"]["tool"] == DETAIL]
    assert len(detail_requests) == len(set(detail_requests))           # 캐시 조회조차 하지 않음 (본 후보는 건너뜀)
    judged = [e["performance_id"] for e in res["excluded"] + res["unjudgeable"] + res["recommendations"]]
    assert len(judged) == len(set(judged))                             # 같은 후보를 두 번 판단하지 않음
    assert llm.call_count == 3                                         # 재계획은 규칙 → LLM 추가 호출 0


def test_replan_limit_is_enforced_independently_of_strategy_count(saver):
    """상한(NF3004)은 전략 개수와 별개로 지켜져야 한다: 상한 2 → 전략이 남아 있어도 2회에서 멈춤."""
    from app.agents.graph import MainAgent
    from fakes import FakeLLM
    from agents.world import TODAY
    world = s3_world()
    agent = MainAgent(llm=FakeLLM([S3_ANALYZE, plan(SEARCH, DETAIL), "ok"]), registry=world.registry(),
                      today=lambda: TODAY, max_replan=2)
    res = agent.run("s", "...")
    assert res["status"] == "limit_reached" and res["replan_count"] == 2
    assert sum(e["type"] == "replan" for e in res["timeline"]) == 2


def test_s3_stops_at_replan_limit_with_reason_and_suggestion(make_agent):
    world = s3_world()
    agent, _, events = make_agent(world, S3_ANALYZE, plan(SEARCH, DETAIL), "ok")
    res = agent.run("s3", "수요일 오전 9시 이후 11시 전에 끝나는 연극")
    assert res["status"] == "limit_reached" and res["replan_count"] == 3
    assert [e["payload"]["strategy"] for e in types(events, "replan")] == ["expand_pool", "drop_genre", "widen_region"]
    assert world.list_calls()[-1].get("signgucodesub") is None and world.list_calls()[-1]["signgucode"] == "11"
    assert res["suggestions"] and res["recommendations"] == []


def test_no_strategy_left_ends_as_no_match_before_limit(make_agent):
    world = FakeWorld([Show("PFX", "x", schedule="토요일(20:00)")])
    agent, _, events = make_agent(world, analyze("plan_performance", date=SAT, earliest_start="10:00", end_by="12:00",
                                                 region="서울"), plan(SEARCH, DETAIL), "ok")
    res = agent.run("s", "...")
    assert res["status"] == "no_match" and res["replan_count"] == 1   # expand_pool 뿐 (장르 없음, 이미 서울)


# ---------------------------------------------------------------- F3010 대화 맥락
def test_followup_changes_only_genre_and_keeps_other_conditions(make_agent):
    world = s1_world()
    memory = MemoryStore()
    agent, _, _ = make_agent(world, S1_ANALYZE, plan(SEARCH, DETAIL, NEARBY), "first",
                             analyze("modify_condition", "장르만 변경", genre="뮤지컬"), plan(SEARCH, DETAIL), "second",
                             memory=memory)
    agent.run("s7", "토요일 ...")
    res = agent.run("s7", "같은 날 뮤지컬로")
    c = res["conditions"]
    assert c["genre"] == {"value": "뮤지컬", "source": "user"}
    assert c["date"] == {"value": SAT, "source": "memory"} and c["budget_max"]["source"] == "memory"
    assert world.list_calls()[-1]["shcate"] == "GGGA" and world.list_calls()[-1]["stdate"] == "20261128"
    assert res["recommendations"][0]["performance_id"] == "PFM9"
    assert len(memory.get("s7").history) == 4


# ---------------------------------------------------------------- LLM 실패 내성
def test_respond_llm_failure_falls_back_to_template(make_agent):
    agent, _, _ = make_agent(s1_world(), S1_ANALYZE, plan(SEARCH, DETAIL, NEARBY), TimeoutError("llm down"))
    res = agent.run("s1", "...")
    assert res["status"] == "ok" and "추천될 연극" in res["reply"] and "15:00" in res["reply"]


def test_analyze_llm_failure_returns_error_status_not_exception(make_agent):
    world = s1_world()
    agent, _, _ = make_agent(world, RuntimeError("down"))
    res = agent.run("s1", "...")
    assert res["status"] == "error" and world.session.calls == []


def test_plan_llm_failure_falls_back_to_rule_plan(make_agent):
    world = s1_world()
    agent, _, events = make_agent(world, S1_ANALYZE, RuntimeError("down"), "ok")
    res = agent.run("s1", "...")
    assert res["status"] == "ok" and types(events, "plan.corrected")[0]["payload"]["reason"] == "llm_failed"


def test_no_llm_configured_returns_config_missing(make_agent):
    agent, _, _ = make_agent(s1_world(), llm=None)
    assert agent.run("s1", "안녕")["status"] == "config_missing"


# ---------------------------------------------------------------- F3005 잘못된 조건은 채우지 않고 되묻기
def test_past_or_malformed_values_are_not_used(make_agent):
    world = s1_world()
    bad = {**S1_ANALYZE, "date": "2026-11-01", "end_by": "6시"}
    agent, _, _ = make_agent(world, bad)
    res = agent.run("s1", "...")
    assert res["status"] == "clarify" and "date" in res["missing"]
    assert res["conditions"]["end_by"] is None and world.session.calls == []
    assert any("지난 날짜" in n["message"] for n in res["notices"])


# ---------------------------------------------------------------- fact_query / confirm_plan
def test_fact_query_searches_by_keyword_and_answers_facts(make_agent):
    world = s1_world()
    agent, llm, _ = make_agent(world, analyze("fact_query", keyword="추천될"), plan(SEARCH, DETAIL), "100분이에요")
    res = agent.run("s", "추천될 연극 러닝타임 몇 분이야?")
    assert res["status"] == "ok" and res["facts"]["runtime_min"] == 100 and res["facts"]["title"] == "추천될 연극"
    assert world.list_calls()[0]["shprfnm"] == "추천될"


def test_confirm_plan_saves_previous_recommendation(make_agent, saver):
    memory = MemoryStore()
    world = s1_world()
    agent, _, _ = make_agent(world, S1_ANALYZE, plan(SEARCH, DETAIL, NEARBY), "first",
                             analyze("confirm_plan", "저장 요청", target_index=1), memory=memory, save_plan=saver)
    agent.run("s", "...")
    res = agent.run("s", "1번으로 저장해줘")
    assert res["status"] == "saved" and saver.saved[0]["performance_id"] == "PFA1"
    assert (saver.saved[0]["date"], saver.saved[0]["start_time"], saver.saved[0]["end_time"]) == (SAT, "15:00", "16:40")


def test_confirm_plan_without_recommendation_asks_back(make_agent, saver):
    agent, _, _ = make_agent(s1_world(), analyze("confirm_plan", target_index=2), save_plan=saver)
    res = agent.run("s", "2번 저장")
    assert res["status"] == "clarify" and saver.saved == []


# ---------------------------------------------------------------- 발행이 구독자에 의존하지 않음 (F3012 선행)
def test_runs_when_publisher_raises(make_agent):
    def broken(_):
        raise RuntimeError("logger down")
    agent, _, _ = make_agent(s1_world(), S1_ANALYZE, plan(SEARCH, DETAIL, NEARBY), "ok", publish=broken)
    assert agent.run("s1", "...")["status"] == "ok"


def test_timeline_is_ordered_and_marks_replan(make_agent):
    agent, _, _ = make_agent(s2_world(), S2_ANALYZE, plan(SEARCH, DETAIL), "ok")
    res = agent.run("s2", "...")
    seqs = [e["seq"] for e in res["timeline"]]
    assert seqs == sorted(seqs) and seqs[0] == 1
    assert res["timeline"][0]["type"] == "run.start" and res["timeline"][-1]["type"] == "run.end"
    assert sum(e["type"] == "replan" for e in res["timeline"]) == 2
    assert res["llm_calls"] == 3
