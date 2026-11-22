"""메인 Agent — LangGraph (docs/04 2절, 7A.2).

baseline       : analyze → plan → execute → judge → respond               (필수 구현, 명세 4.2)
planner_worker : analyze → plan → execute(Worker) → verify(로깅 Agent) → judge → respond   (심화 F3021)
"""
from __future__ import annotations

import time
import uuid
from datetime import date, datetime
from datetime import time as dtime
from typing import Any, Callable

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from ..tools.registry import ToolRegistry
from .memory import MemoryStore
from .nodes.analyze import analyze
from .nodes.execute import execute
from .nodes.judge import judge
from .nodes.plan import plan
from .nodes.respond import respond
from .nodes.verify import verify
from .runtime import AgentDeps, RunContext
from .state import PLAN_INTENTS, PlannerState

NodeFn = Callable[[PlannerState, RunContext], dict[str, Any]]
MODES = ("baseline", "planner_worker")
ROLE = {"analyze": "Planner", "plan": "Planner", "judge": "Planner", "respond": "Planner",
        "execute": "Worker", "verify": "LoggingAgent"}


def _traced(name: str, fn: NodeFn) -> Callable[[PlannerState, RunnableConfig], dict[str, Any]]:
    """노드 진입·종료 이벤트 (F3012). RunContext 는 config 로 받아 요청끼리 섞이지 않게 한다."""
    def node(state: PlannerState, config: RunnableConfig) -> dict[str, Any]:
        run: RunContext = config["configurable"]["run"]
        extra = {"role": ROLE[name]} if run.deps.mode == "planner_worker" else {}
        run.emit("node.enter", name, **extra)
        out = fn(state, run)
        summary = {k: out[k] for k in ("intent", "missing", "next", "stop_reason", "phase", "plan_version")
                   if k in out}
        if name == "analyze" and "intent_reason" in out:
            summary["reason"] = out["intent_reason"]
        run.emit("node.exit", name, **summary, **extra)
        return out
    return node


def _after_analyze(state: PlannerState) -> str:
    if state.get("stop_reason") or state.get("missing") or state.get("intent") in ("chitchat", "confirm_plan"):
        return "respond"
    return "plan"


def _after_judge(state: PlannerState) -> str:
    return {"replan": "plan", "enrich": "execute"}.get(state.get("next", ""), "respond")


def build_graph(mode: str = "baseline"):
    if mode not in MODES:
        raise ValueError(f"unknown mode: {mode}")
    g = StateGraph(PlannerState)
    nodes = [("analyze", analyze), ("plan", plan), ("execute", execute), ("judge", judge), ("respond", respond)]
    if mode == "planner_worker":
        nodes.append(("verify", verify))
    for name, fn in nodes:
        g.add_node(name, _traced(name, fn))
    g.add_edge(START, "analyze")
    g.add_conditional_edges("analyze", _after_analyze, {"plan": "plan", "respond": "respond"})
    after_collect = "verify" if mode == "planner_worker" else "judge"
    g.add_conditional_edges("execute", lambda s: "respond" if s.get("phase") == "done" else after_collect,
                            {after_collect: after_collect, "respond": "respond"})
    if mode == "planner_worker":
        g.add_conditional_edges("plan", lambda s: s.get("route_after_plan", "execute"),
                                {"execute": "execute", "judge": "judge"})
        g.add_conditional_edges("verify", lambda s: "plan" if s.get("rebuild_requested") else "judge",
                                {"plan": "plan", "judge": "judge"})
    else:
        g.add_edge("plan", "execute")
    g.add_conditional_edges("judge", _after_judge, {"plan": "plan", "execute": "execute", "respond": "respond"})
    g.add_edge("respond", END)
    return g.compile()


class MainAgent:
    def __init__(self, llm: Any, registry: ToolRegistry, memory: MemoryStore | None = None,
                 publish: Callable[[dict], None] | None = None, save_plan: Callable[[dict], dict] | None = None,
                 today: Callable[[], date] | None = None, max_replan: int = 3,
                 now: Callable[[], datetime] | None = None, mode: str = "baseline", worker_llm: bool = True,
                 verifier: Callable[[str], dict] | None = None, max_worker_retries: int = 2):
        from ..tools.factory import KST, kst_today
        self.llm = llm
        self.memory = memory or MemoryStore()
        self.publish = publish
        self.mode = mode
        if now is None:
            # 시계를 주입한 테스트는 그날 00:00 기준(지난 회차 없음), 실제 실행은 현재 KST 시각
            now = (lambda: datetime.combine(today(), dtime.min)) if today else (lambda: datetime.now(KST).replace(tzinfo=None))
        self.deps = AgentDeps(llm=llm, registry=registry, today=today or kst_today, save_plan=save_plan,
                              max_replan=max_replan, now=now, mode=mode, worker_llm=worker_llm,
                              max_worker_retries=max_worker_retries, verifier=verifier)
        self.graph = build_graph(mode)

    def run(self, session_id: str, message: str) -> dict[str, Any]:
        mem = self.memory.get(session_id)
        run = RunContext(deps=self.deps, session_id=session_id, run_id=f"r-{uuid.uuid4().hex[:12]}",
                         memory=mem, publish=self.publish)
        t0 = time.perf_counter()
        run.emit("run.start", None, message=message[:200], mode=self.mode)
        final: dict[str, Any] = {}
        if self.llm is None:
            response = {"status": "config_missing", "reply": "LLM API 키가 설정되지 않았습니다. .env 의 LLM_API_KEY 를 확인해 주세요."}
        else:
            try:
                final = self.graph.invoke({"session_id": session_id, "user_message": message},
                                          config={"configurable": {"run": run}, "recursion_limit": 60})
                response = final["response"]
            except Exception as e:  # noqa: BLE001 — 어떤 경우에도 서비스는 응답한다 (NF3003)
                run.emit("error", None, code="AGENT_FAILED", detail=type(e).__name__)
                response = {"status": "error", "reply": "처리 중 문제가 생겼어요. 잠시 후 다시 시도해 주세요."}

        self._remember(mem, final, response, message)
        run.emit("run.end", None, status=response["status"], llm_calls=run.llm_calls,
                 worker_llm_calls=run.worker_llm_calls, mode=self.mode,
                 duration_ms=round((time.perf_counter() - t0) * 1000), replan_count=response.get("replan_count", 0))
        return {"session_id": session_id, "run_id": run.run_id, **response, "agent_mode": self.mode,
                "verification": final.get("verification"), "timeline": run.events,
                "llm_calls": run.llm_calls, "worker_llm_calls": run.worker_llm_calls}

    @staticmethod
    def _remember(mem, final: dict[str, Any], response: dict[str, Any], message: str) -> None:
        intent = final.get("intent")
        if intent in PLAN_INTENTS and final.get("conditions") is not None:
            mem.conditions = dict(final["conditions"])
        if response.get("recommendations"):
            mem.remember_recommendations(response["recommendations"])
        if intent:
            mem.last_intent = intent
        mem.add_turn(message, response.get("reply", ""))
