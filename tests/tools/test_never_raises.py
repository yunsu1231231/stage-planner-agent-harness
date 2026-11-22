"""L2 — 어떤 오류가 나도 Tool은 예외를 던지지 않는다 (F3001, NF3003, 명세 4.1)."""
from __future__ import annotations

import pytest
import requests

from fakes import FakeResponse

CALLS = [
    ("search_performances", {}),
    ("get_performance_detail", {"performance_id": "PF1"}),
    ("search_nearby_places", {"venue_id": "FC1", "category": "restaurant"}),
    ("search_nearby_places", {"x": "1", "y": "2", "category": "cafe"}),
]
FAILURES = [
    requests.Timeout("t"), requests.ConnectionError("c"), ValueError("v"), KeyError("k"),
    FakeResponse(500, "<html>server error</html>", content_type="text/html"),
    FakeResponse(200, "", content_type="application/xml"),
    FakeResponse(200, "{not json", content_type="application/json"),
    FakeResponse(200, '{"documents": [{"unexpected": 1}]}', content_type="application/json"),
]


@pytest.mark.parametrize("name,args", CALLS)
@pytest.mark.parametrize("failure", FAILURES, ids=lambda f: type(f).__name__ + str(getattr(f, "status_code", "")))
def test_tool_never_raises(make_registry, session, name, args, failure):
    session.add(r".*", failure)
    r = make_registry().call(name, args)          # 예외가 나면 이 줄에서 테스트 실패
    assert r.ok is False and r.error.code
