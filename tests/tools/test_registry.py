"""L2 — F3001 Tool 명세 정의·등록, 공통 응답 형식 (명세 4.1 첫 두 항목)."""
from __future__ import annotations

from pydantic import BaseModel

from app.tools.base import ErrorCode, ToolResult
from app.tools.registry import ToolRegistry, ToolSpec
from fakes import FakeLLM

EXPECTED = {"search_performances", "get_performance_detail", "search_nearby_places"}


def test_registry_lists_tools_with_name_description_schema(make_registry):
    specs = make_registry().list_specs()
    assert {s["name"] for s in specs} == EXPECTED
    for s in specs:
        assert s["kind"] == "external"                       # 필수 3종은 모두 외부 API 툴
        assert "때" in s["description"], "설명에는 기능이 아니라 '언제 쓰는지'를 적는다 (명세 2.3)"
        assert s["input_schema"]["type"] == "object" and s["input_schema"]["properties"]


def test_unknown_tool_returns_failure_not_exception(make_registry):
    r = make_registry().call("book_ticket", {})
    assert r.ok is False and r.error.code == ErrorCode.UNKNOWN_TOOL and r.data is None


def test_invalid_input_is_reported_as_invalid_input(make_registry, session):
    r = make_registry().call("search_performances", {"date": "2026/11/28"})
    assert r.ok is False and r.error.code == ErrorCode.INVALID_INPUT
    assert session.calls == []                               # 검증 실패면 외부 호출 없음


def test_nearby_requires_venue_or_coordinates(make_registry):
    r = make_registry().call("search_nearby_places", {"category": "restaurant"})
    assert r.error.code == ErrorCode.INVALID_INPUT


def test_exception_inside_tool_becomes_upstream_error_without_leaking_detail():
    class In(BaseModel):
        x: int = 0

    def boom(_: In) -> ToolResult:
        raise RuntimeError("stack detail with secret-ish info")

    reg = ToolRegistry()
    reg.register(ToolSpec(name="boom", kind="local", description="테스트할 때 쓴다", input_model=In, func=boom))
    r = reg.call("boom", {})
    assert r.ok is False and r.error.code == ErrorCode.UPSTREAM_ERROR
    assert "secret-ish" not in r.error.message


def test_result_shape_is_uniform():
    ok = ToolResult.success({"a": 1}, source="TEST")
    bad = ToolResult.failure(ErrorCode.NO_RESULT, "없음")
    assert ok.ok and ok.error is None and ok.meta["source"] == "TEST"
    assert not bad.ok and bad.data is None and bad.error.retryable is True
    assert set(ok.model_dump()) == set(bad.model_dump()) == {"ok", "data", "error", "meta"}


def test_langchain_tools_expose_only_name_description_schema(make_registry):
    tools = make_registry().as_langchain_tools()
    assert {t.name for t in tools} == EXPECTED
    llm = FakeLLM([[{"name": "search_performances", "args": {"region": "대학로"}}]])
    msg = llm.bind_tools(tools).invoke("대학로 연극")       # 바인딩 가능해야 한다
    assert msg.tool_calls[0]["name"] == "search_performances"
