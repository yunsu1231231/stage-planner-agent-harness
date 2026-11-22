"""가짜 HTTP 세션 — 외부 API를 녹화 응답(fixture)으로 대체 (docs/06 1절 L2).

requests.Session 중 우리가 쓰는 표면(headers, get)만 흉내 낸다. Tool 구현은 세션을
주입받으므로, 테스트에서는 이 FakeSession을 넣는다.

기획 검증에서 발견한 실제 동작을 재현할 수 있다:
  - 응답 헤더에 charset이 없으면 requests처럼 ISO-8859-1로 디코딩 → 한글 깨짐
    (Tool이 r.encoding = "utf-8" 을 빠뜨리면 테스트가 잡는다)
  - 연속 응답 시퀀스: [차단 HTML 400, 정상 XML] → 재시도 로직 검증
  - 예외 주입: requests.ConnectionError 등
등록되지 않은 요청은 UnexpectedHTTPCall 로 실패한다 (테스트 중 실제 네트워크 금지).
"""
from __future__ import annotations

import json as _json
import re
from dataclasses import dataclass, field
from typing import Any, Callable


class UnexpectedHTTPCall(AssertionError):
    """등록된 route에 맞지 않는 HTTP 호출."""


class FakeResponse:
    def __init__(self, status_code: int = 200, body: str | bytes = "", content_type: str = "application/xml",
                 headers: dict[str, str] | None = None):
        self.status_code = status_code
        self.content = body.encode("utf-8") if isinstance(body, str) else body
        self.headers = {"Content-Type": content_type, **(headers or {})}
        # requests 동작 재현: charset 없으면 encoding=None → text는 ISO-8859-1로 추정
        m = re.search(r"charset=([\w-]+)", content_type, re.I)
        self.encoding: str | None = m.group(1) if m else None

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    @property
    def text(self) -> str:
        return self.content.decode(self.encoding or "ISO-8859-1", errors="replace")

    def json(self) -> Any:
        return _json.loads(self.content.decode(self.encoding or "utf-8"))

    def raise_for_status(self) -> None:
        if not self.ok:
            import requests
            raise requests.HTTPError(f"{self.status_code}", response=self)  # type: ignore[arg-type]


Responder = FakeResponse | BaseException | Callable[[str, dict], "FakeResponse"]


@dataclass
class Route:
    pattern: re.Pattern
    responses: list[Responder]
    repeat_last: bool = True
    hits: int = 0


@dataclass
class HTTPCall:
    method: str
    url: str
    params: dict
    headers: dict
    timeout: Any


@dataclass
class FakeSession:
    headers: dict[str, str] = field(default_factory=dict)
    routes: list[Route] = field(default_factory=list)
    calls: list[HTTPCall] = field(default_factory=list)

    def add(self, url_regex: str, *responses: Responder, repeat_last: bool = True) -> "FakeSession":
        """url_regex 에 맞는 요청에 responses 를 순서대로 돌려준다. 다 쓰면 마지막 것을 반복."""
        self.routes.append(Route(re.compile(url_regex), list(responses), repeat_last))
        return self

    def get(self, url: str, params: dict | None = None, headers: dict | None = None,
            timeout: Any = None, **kwargs: Any) -> FakeResponse:
        merged = {**self.headers, **(headers or {})}
        self.calls.append(HTTPCall("GET", url, dict(params or {}), merged, timeout))
        for route in self.routes:
            if route.pattern.search(url):
                idx = min(route.hits, len(route.responses) - 1) if route.repeat_last else route.hits
                route.hits += 1
                if idx >= len(route.responses):
                    raise UnexpectedHTTPCall(f"route {route.pattern.pattern} 응답 소진 (호출 {route.hits}회)")
                resp = route.responses[idx]
                if isinstance(resp, BaseException):
                    raise resp
                if callable(resp) and not isinstance(resp, FakeResponse):
                    return resp(url, dict(params or {}))
                return resp
        raise UnexpectedHTTPCall(f"등록되지 않은 HTTP 호출: GET {url} params={params}")

    # 편의 조회
    def calls_to(self, url_regex: str) -> list[HTTPCall]:
        p = re.compile(url_regex)
        return [c for c in self.calls if p.search(c.url)]
