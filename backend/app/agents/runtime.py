"""실행 컨텍스트: 의존성(LLM·레지스트리·시계), 요청 1건 단위의 이벤트 발행·LLM 호출 수·Tool 캐시 호출."""
from __future__ import annotations

import copy
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Callable

from ..tools.base import ToolResult
from ..tools.registry import ToolRegistry
from .memory import SessionMemory


@dataclass
class AgentDeps:
    llm: Any
    registry: ToolRegistry
    today: Callable[[], date]
    save_plan: Callable[[dict], dict] | None = None
    now: Callable[[], datetime] | None = None   # 오늘 관람이면 지난 회차 제외 (judge)
    mode: str = "baseline"                      # baseline | planner_worker (F3021)
    worker_llm: bool = True                     # Worker LLM 판단 on/off (비교 실험)
    max_worker_retries: int = 2
    verifier: Callable[[str], dict] | None = None   # 로깅 Agent 의 inspect(run_id)
    max_replan: int = 3                 # NF3004
    max_detail: int = 15                # NF3005: 단계당 상세 조회 상한
    max_enrich: int = 3                 # 주변 장소를 붙일 추천 공연장 수


@dataclass
class RunContext:
    deps: AgentDeps
    session_id: str
    run_id: str
    memory: SessionMemory
    publish: Callable[[dict], None] | None = None
    events: list[dict] = field(default_factory=list)
    llm_calls: int = 0
    worker_llm_calls: int = 0
    _seq: int = 0

    def message(self, node: str, sender: str, receiver: str, kind: str, body: dict) -> None:
        """Agent 사이 메시지를 실행 로그에 남긴다 (F3021: Planner·Worker·로깅 Agent)."""
        self.emit("agent.message", node, **{"from": sender, "to": receiver, "kind": kind, "body": body})

    # ---- F3012 이벤트 발행: 구독자가 없거나 실패해도 흐름에 영향 없음
    def emit(self, type_: str, node: str | None = None, **payload: Any) -> dict:
        self._seq += 1
        # 발행 시점의 값을 고정한다 — 이후 호출자가 같은 dict 를 고쳐도(예: Worker 재시도 인자) 기록은 바뀌지 않는다
        event = {"event_id": uuid.uuid4().hex, "session_id": self.session_id, "run_id": self.run_id, "seq": self._seq,
                 "ts": datetime.now().astimezone().isoformat(timespec="milliseconds"),
                 "type": type_, "node": node, "payload": copy.deepcopy(payload)}
        self.events.append(event)
        if self.publish is not None:
            try:
                self.publish(event)
            except Exception:  # noqa: BLE001 — 로깅 쪽 장애가 Agent를 멈추면 안 된다
                pass
        return event

    # ---- Tool 호출 (+ 캐시 재사용, 이벤트)
    def call_tool(self, cache: dict[str, dict], node: str, tool: str, args: dict[str, Any],
                  extra: dict[str, Any] | None = None) -> ToolResult:
        key = f"{tool}:{json.dumps(args, sort_keys=True, ensure_ascii=False)}"
        extra = extra or {}
        if key in cache:
            result = ToolResult.model_validate(cache[key])
            self.emit("tool.request", node, tool=tool, args=args, cached=True, **extra)
            self.emit("tool.response", node, tool=tool, ok=result.ok, error_code=_code(result), duration_ms=0,
                      cached=True, summary=summarize(tool, result))
            return result
        self.emit("tool.request", node, tool=tool, args=args, cached=False, **extra)
        t0 = time.perf_counter()
        result = self.deps.registry.call(tool, args)
        self.emit("tool.response", node, tool=tool, ok=result.ok, error_code=_code(result),
                  duration_ms=round((time.perf_counter() - t0) * 1000), cached=False, summary=summarize(tool, result))
        cache[key] = result.model_dump()
        return result


def _code(r: ToolResult) -> str | None:
    return r.error.code.value if r.error else None


def summarize(tool: str, r: ToolResult) -> str:
    if not r.ok:
        return f"{r.error.code.value}: {r.error.message}"
    d = r.data or {}
    if "items" in d:
        return f"후보 {len(d['items'])}건"
    if "runtime_min" in d:
        return f"{d.get('title')} · {d['runtime_min']}분 · {d.get('schedule_raw')} · {d.get('price_raw')}"
    if "places" in d:
        return f"장소 {len(d['places'])}곳"
    return "ok"
