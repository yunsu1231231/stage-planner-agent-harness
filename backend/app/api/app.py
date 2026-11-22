"""FastAPI 앱 조립 — 설정·Tool·LLM·저장소·이벤트 버스·로깅 Agent·메인 Agent 연결."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ..agents.graph import MainAgent
from ..agents.log_diagnosis import make_diagnoser
from ..agents.logging_agent import LoggingAgent
from ..agents.memory import MemoryStore
from ..core.config import ROOT, Settings
from ..core.llm import make_llm
from ..events.bus import EventBus
from ..storage.db import Database
from ..storage.logs import LogRepository
from ..storage.plans import PlanRepository
from ..tools.factory import build_registry
from ..tools.registry import ToolRegistry
from .routes import ApiError, chat, logs, plans, system

_UNSET: Any = object()


def create_app(settings: Settings | None = None, llm: Any = _UNSET, registry: ToolRegistry | None = None,
               db_path: str | Path | None = None, today: Callable[[], date] | None = None,
               attach_logger: bool = True) -> FastAPI:
    settings = settings or Settings.from_env()
    llm = make_llm(settings) if llm is _UNSET else llm
    registry = registry or build_registry(settings.kopis_api_key, settings.kakao_api_key)
    db = Database(db_path or ROOT / "data" / "planner.db")
    plan_repo, log_repo = PlanRepository(db), LogRepository(db)

    bus = EventBus()
    diagnoser = make_diagnoser(llm) if (llm is not None and settings.log_diagnosis) else None
    logging_agent = LoggingAgent(log_repo, diagnoser=diagnoser)
    if attach_logger:
        logging_agent.attach(bus)

    def save_plan(plan: dict) -> dict:
        saved, overlaps = plan_repo.create(plan)
        return {"plan": saved, "overlaps": overlaps}

    agent = MainAgent(llm=llm, registry=registry, memory=MemoryStore(), publish=bus.publish,
                      save_plan=save_plan, today=today, mode=settings.agent_mode, worker_llm=settings.worker_llm,
                      verifier=logging_agent.inspect if attach_logger else None)

    app = FastAPI(title="공연 관람 플래너 API", version="0.1.0",
                  description="Agent 기반 공연 관람 플래너 — 대화, 계획 관리, 실행 로그")
    app.state.settings, app.state.registry, app.state.agent = settings, registry, agent
    app.state.plans, app.state.logs, app.state.bus, app.state.logging_agent = plan_repo, log_repo, bus, logging_agent

    # 프론트엔드는 별도 출처에서 정적 파일로 서빙 (NF3006 분리)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        return JSONResponse(status_code=exc.status, content={"error": {"code": exc.code, "message": exc.message}})

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception):  # NF3002: 상세는 숨긴다
        return JSONResponse(status_code=500, content={"error": {"code": "INTERNAL_ERROR",
                                                                "message": "서버에서 문제가 발생했습니다."}})

    for router in (chat, plans, logs, system):
        app.include_router(router)
    return app
