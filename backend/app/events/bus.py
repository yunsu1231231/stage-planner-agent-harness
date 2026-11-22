"""실행 이벤트 버스 (F3012). 동기 in-process pub/sub.

발행자는 publish() 만 호출하고 누가 구독하는지 모른다. 구독자 예외는 여기서 삼키고 세기만 한다.
"""
from __future__ import annotations

from typing import Any, Callable

Handler = Callable[[dict[str, Any]], None]


class EventBus:
    def __init__(self) -> None:
        self._handlers: list[Handler] = []
        self.failures = 0

    def subscribe(self, handler: Handler) -> Callable[[], None]:
        self._handlers.append(handler)
        return lambda: self._handlers.remove(handler)

    def publish(self, event: dict[str, Any]) -> None:
        for handler in list(self._handlers):
            try:
                handler(event)
            except Exception:  # noqa: BLE001 — 구독자 장애가 발행자를 멈추면 안 된다
                self.failures += 1
