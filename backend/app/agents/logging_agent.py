"""로깅 서브 Agent (F3013). 이벤트를 구독해 받는 즉시 세션 단위로 그대로 저장한다.

- 수집·저장에 LLM 을 쓰지 않는다 (가드 테스트 test_logging_zone_does_not_import_llm 이 import 를 감시).
- 저장에 실패해도 예외를 밖으로 내보내지 않는다 → 대화는 계속된다.
- 심화 F3020(이상 징후 판정)은 이 Agent 에 규칙으로 추가된다.
"""
from __future__ import annotations

from typing import Any, Protocol


class EventSink(Protocol):
    def append(self, event: dict[str, Any]) -> None: ...


class Subscribable(Protocol):
    def subscribe(self, handler): ...


class LoggingAgent:
    def __init__(self, sink: EventSink):
        self.sink = sink
        self.stored = 0
        self.failures = 0

    def handle(self, event: dict[str, Any]) -> None:
        try:
            self.sink.append(event)
            self.stored += 1
        except Exception:  # noqa: BLE001
            self.failures += 1

    def attach(self, bus: Subscribable):
        return bus.subscribe(self.handle)
