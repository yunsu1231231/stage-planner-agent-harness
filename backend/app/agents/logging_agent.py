"""로깅 서브 Agent (F3013 + 심화 F3020).

- 수집·저장: 이벤트를 받는 즉시 세션 단위로 그대로 저장. **LLM 을 쓰지 않는다** (가드 테스트가 import 감시).
- 이상 징후 판정(F3020): 실행(run)마다 이벤트를 모아 두었다가 `run.end` 에서 규칙으로 판정해 저장.
- 원인 진단: `anomaly` 판정에만, **주입된** 진단 함수를 호출 (LLM 은 그 함수 쪽에 있다). 진단은 판정과 따로 저장.
- 검증 제공(F3021): `inspect(run_id)` 로 실행 중간에도 같은 형식의 판정 보고서를 메인 Agent(Planner)에 준다.
- 저장·진단 실패는 삼킨다 → 대화는 계속된다.
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any, Callable, Protocol

from .anomaly import evaluate_run

Diagnoser = Callable[[list[dict[str, Any]], dict[str, Any]], str]


class EventSink(Protocol):
    def append(self, event: dict[str, Any]) -> None: ...


class Subscribable(Protocol):
    def subscribe(self, handler): ...


class LoggingAgent:
    MAX_BUFFERED_RUNS = 200

    def __init__(self, sink: EventSink, diagnoser: Diagnoser | None = None, run_async: bool = True,
                 replan_limit: int = 3):
        self.sink = sink
        self.diagnoser = diagnoser
        self.run_async = run_async
        self.replan_limit = replan_limit
        self._runs: "OrderedDict[str, list[dict]]" = OrderedDict()
        self._lock = threading.Lock()
        self.stored = self.failures = self.diagnosis_failures = 0

    # ---------------------------------------------------------------- 수집·저장 (LLM 없음)
    def handle(self, event: dict[str, Any]) -> None:
        try:
            self.sink.append(event)
            self.stored += 1
        except Exception:  # noqa: BLE001
            self.failures += 1
        run_id = event.get("run_id")
        if not run_id:
            return
        with self._lock:
            self._runs.setdefault(run_id, []).append(event)
            while len(self._runs) > self.MAX_BUFFERED_RUNS:
                self._runs.popitem(last=False)
        if event.get("type") == "run.end":
            self._finish(run_id)

    def attach(self, bus: Subscribable):
        return bus.subscribe(self.handle)

    # ---------------------------------------------------------------- 판정 (규칙)
    def inspect(self, run_id: str) -> dict[str, Any]:
        """실행 중간 점검 — 메인 Agent(Planner)가 참조하는 형식."""
        with self._lock:
            events = list(self._runs.get(run_id, []))
        report = evaluate_run(events, replan_limit=self.replan_limit, final=False)
        report["run_id"] = run_id
        return report

    def buffered_runs(self) -> int:
        return len(self._runs)

    def _finish(self, run_id: str) -> None:
        with self._lock:
            events = self._runs.pop(run_id, [])
        report = evaluate_run(events, replan_limit=self.replan_limit, final=True)
        report["session_id"] = events[0].get("session_id") if events else None
        save = getattr(self.sink, "save_report", None)
        if save is None:
            return
        try:
            save(report)
        except Exception:  # noqa: BLE001
            self.failures += 1
            return
        if report["verdict"] == "anomaly" and self.diagnoser is not None:
            if self.run_async:
                threading.Thread(target=self._diagnose, args=(events, report), daemon=True).start()
            else:
                self._diagnose(events, report)

    # ---------------------------------------------------------------- 진단 (이상 실행만, 주입된 LLM 함수)
    def _diagnose(self, events: list[dict[str, Any]], report: dict[str, Any]) -> None:
        try:
            text = self.diagnoser(events, report)
            self.sink.save_diagnosis(report["run_id"], text)
        except Exception:  # noqa: BLE001 — 진단이 실패해도 판정과 실행 로그는 남는다
            self.diagnosis_failures += 1
