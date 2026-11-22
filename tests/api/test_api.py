"""L4 — F3017 FastAPI: 대화·계획·로그 경로 분리, 요청·응답 형식, NF3002 노출 제한."""
from __future__ import annotations

from agents.scripts import DETAIL, NEARBY, S1_ANALYZE, SEARCH, analyze, plan
from api.conftest import SECRET

PLAN = {"performance_id": "PF1", "title": "연극A", "venue_name": "극장", "date": "2026-11-28",
        "start_time": "15:00", "end_time": "16:40", "price": 40000}


# ---------------------------------------------------------------- 구조·보안
def test_routes_are_separated_by_resource(make_client):
    client, _, _ = make_client()
    paths = client.get("/openapi.json").json()["paths"]
    for p in ["/api/chat", "/api/chat/sessions/{session_id}", "/api/plans", "/api/plans/{plan_id}",
              "/api/logs", "/api/logs/{session_id}", "/api/health", "/api/tools"]:
        assert p in paths, p
    assert set(paths["/api/logs/{session_id}"]) == {"get", "delete"}        # 수정 경로 없음 (F3014)


def test_health_reports_flags_never_values(make_client):
    client, _, _ = make_client()
    body = client.get("/api/health").text
    assert '"llm":true' in body.replace(" ", "") and SECRET not in body and "KOPIS-SECRET" not in body


def test_tools_endpoint_lists_registered_specs(make_client):
    client, _, _ = make_client()
    tools = client.get("/api/tools").json()["tools"]
    assert {t["name"] for t in tools} == {SEARCH, DETAIL, NEARBY} and all(t["kind"] == "external" for t in tools)


# ---------------------------------------------------------------- 대화
def test_chat_returns_agent_result_with_session_and_timeline(make_client):
    client, _, _ = make_client(S1_ANALYZE, plan(SEARCH, DETAIL, NEARBY), "추천")
    r = client.post("/api/chat", json={"message": "토요일 ..."})
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"].startswith("s-") and body["status"] == "ok" and body["reply"] == "추천"
    assert body["recommendations"][0]["performance_id"] == "PFA1"
    assert body["timeline"][0]["type"] == "run.start" and body["llm_calls"] == 3


def test_chat_validates_input(make_client):
    client, _, _ = make_client()
    assert client.post("/api/chat", json={"message": ""}).status_code == 422


def test_chat_never_leaks_internal_error_details(make_client):
    client, _, world = make_client(S1_ANALYZE, plan(SEARCH, DETAIL, NEARBY), RuntimeError(f"boom {SECRET}"))
    world.detail_failures["PFA1"] = RuntimeError("Traceback secret path C:/Users/...")
    body = client.post("/api/chat", json={"message": "..."}).text
    assert SECRET not in body and "Traceback" not in body and "C:/Users" not in body


def test_chat_without_llm_key_guides_configuration(make_client):
    client, _, _ = make_client(llm=None)
    body = client.post("/api/chat", json={"message": "안녕"}).json()
    assert body["status"] == "config_missing" and "LLM_API_KEY" in body["reply"]


def test_confirm_plan_through_chat_persists_and_reports_overlap(make_client):
    client, _, _ = make_client(S1_ANALYZE, plan(SEARCH, DETAIL, NEARBY), "추천",
                               analyze("confirm_plan", target_index=1))
    client.post("/api/plans", json={**PLAN, "title": "기존 계획", "start_time": "16:00", "end_time": "17:00"})
    sid = client.post("/api/chat", json={"message": "토요일 ..."}).json()["session_id"]
    body = client.post("/api/chat", json={"session_id": sid, "message": "1번 저장"}).json()
    assert body["status"] == "saved" and body["saved_plan"]["performance_id"] == "PFA1"
    assert any(n["type"] == "overlap" for n in body["notices"])
    assert [p["title"] for p in client.get("/api/plans").json()["plans"]] == ["추천될 연극", "기존 계획"]


def test_reset_chat_session(make_client):
    client, _, _ = make_client()
    assert client.delete("/api/chat/sessions/s-x").status_code == 204


# ---------------------------------------------------------------- 계획 (F3015, F3016)
def test_plan_crud_and_overlap(make_client):
    client, _, _ = make_client()
    r1 = client.post("/api/plans", json=PLAN)
    assert r1.status_code == 201 and r1.json()["overlaps"] == [] and r1.json()["plan"]["created_at"]
    r2 = client.post("/api/plans", json={**PLAN, "title": "연극B", "start_time": "16:00", "end_time": "17:00"})
    assert r2.status_code == 201 and [o["title"] for o in r2.json()["overlaps"]] == ["연극A"]
    pid = r2.json()["plan"]["id"]

    assert client.get("/api/plans", params={"date": "2026-11-28"}).json()["total"] == 2
    assert client.get(f"/api/plans/{pid}").json()["title"] == "연극B"

    upd = client.patch(f"/api/plans/{pid}", json={"start_time": "18:00", "end_time": "19:00"})
    assert upd.status_code == 200 and upd.json()["plan"]["start_time"] == "18:00" and upd.json()["overlaps"] == []
    assert client.delete(f"/api/plans/{pid}").status_code == 204
    assert client.get(f"/api/plans/{pid}").status_code == 404
    assert client.get(f"/api/plans/{pid}").json()["error"]["code"] == "PLAN_NOT_FOUND"


def test_plan_validation(make_client):
    client, _, _ = make_client()
    assert client.post("/api/plans", json={**PLAN, "end_time": "14:00"}).status_code == 400   # 종료 < 시작
    assert client.post("/api/plans", json={**PLAN, "date": "28/11/2026"}).status_code == 422
    client.post("/api/plans", json=PLAN)
    assert client.patch("/api/plans/1", json={"end_time": "10:00"}).status_code == 400
    assert client.patch("/api/plans/99", json={"memo": "x"}).status_code == 404


# ---------------------------------------------------------------- 실행 로그 (F3014)
def test_logs_list_detail_delete_and_no_update(make_client):
    client, _, _ = make_client(S1_ANALYZE, plan(SEARCH, DETAIL, NEARBY), "추천")
    sid = client.post("/api/chat", json={"message": "..."}).json()["session_id"]
    sessions = client.get("/api/logs").json()["sessions"]
    assert sessions[0]["session_id"] == sid and sessions[0]["run_count"] == 1
    events = client.get(f"/api/logs/{sid}").json()["events"]
    assert [e["seq"] for e in events] == sorted(e["seq"] for e in events) and events[0]["type"] == "run.start"
    assert client.put(f"/api/logs/{sid}", json={}).status_code == 405
    assert client.patch(f"/api/logs/{sid}", json={}).status_code == 405
    assert client.delete(f"/api/logs/{sid}").status_code == 204
    assert client.get(f"/api/logs/{sid}").status_code == 404


def test_chat_works_without_logging_agent(make_client):
    client, _, _ = make_client(S1_ANALYZE, plan(SEARCH, DETAIL, NEARBY), "추천", attach_logger=False)
    assert client.post("/api/chat", json={"message": "..."}).json()["status"] == "ok"
    assert client.get("/api/logs").json()["sessions"] == []
