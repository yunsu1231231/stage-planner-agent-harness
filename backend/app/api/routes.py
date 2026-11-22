"""API 라우터 — 대화 / 계획 / 실행 로그 / 시스템 (F3017, docs/05)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, Request, Response

from ..schemas.api import (ChatRequest, ChatResponse, ErrorResponse, Health, LogDetail, LogSessions, Plan, PlanCreate,
                           PlanList, PlanSaveResult, PlanUpdate, ToolList)


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


ERRORS = {404: {"model": ErrorResponse}, 400: {"model": ErrorResponse}}

chat = APIRouter(prefix="/api/chat", tags=["대화"])
plans = APIRouter(prefix="/api/plans", tags=["계획"])
logs = APIRouter(prefix="/api/logs", tags=["실행 로그"])
system = APIRouter(prefix="/api", tags=["시스템"])


# ---------------------------------------------------------------- 대화
@chat.post("", response_model=ChatResponse, summary="대화 요청 → 메인 Agent 실행")
def post_chat(body: ChatRequest, request: Request):
    session_id = body.session_id or f"s-{uuid.uuid4().hex[:12]}"
    return request.app.state.agent.run(session_id, body.message)


@chat.delete("/sessions/{session_id}", status_code=204, summary="대화 맥락 초기화 (실행 로그는 유지)")
def reset_session(session_id: str, request: Request):
    request.app.state.agent.memory.reset(session_id)
    return Response(status_code=204)


# ---------------------------------------------------------------- 계획
def _check_range(start: str, end: str) -> None:
    if end <= start:
        raise ApiError(400, "INVALID_TIME_RANGE", "종료 시각은 시작 시각보다 늦어야 합니다.")


@plans.post("", response_model=PlanSaveResult, status_code=201, responses=ERRORS, summary="계획 저장 (겹침은 알림)")
def create_plan(body: PlanCreate, request: Request):
    _check_range(body.start_time, body.end_time)
    plan, overlaps = request.app.state.plans.create(body.model_dump())
    return {"plan": plan, "overlaps": overlaps}


@plans.get("", response_model=PlanList, summary="계획 목록 (날짜·시작 시각 순)")
def list_plans(request: Request, date: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$")):
    items = request.app.state.plans.list(date=date)
    return {"plans": items, "total": len(items)}


@plans.get("/{plan_id}", response_model=Plan, responses=ERRORS, summary="계획 상세")
def get_plan(plan_id: int, request: Request):
    plan = request.app.state.plans.get(plan_id)
    if plan is None:
        raise ApiError(404, "PLAN_NOT_FOUND", "계획을 찾을 수 없습니다.")
    return plan


@plans.patch("/{plan_id}", response_model=PlanSaveResult, responses=ERRORS, summary="계획 수정 (겹침 재검사)")
def update_plan(plan_id: int, body: PlanUpdate, request: Request):
    repo = request.app.state.plans
    current = repo.get(plan_id)
    if current is None:
        raise ApiError(404, "PLAN_NOT_FOUND", "계획을 찾을 수 없습니다.")
    changes = body.model_dump(exclude_unset=True)
    _check_range(changes.get("start_time", current["start_time"]), changes.get("end_time", current["end_time"]))
    plan, overlaps = repo.update(plan_id, changes)
    return {"plan": plan, "overlaps": overlaps}


@plans.delete("/{plan_id}", status_code=204, responses=ERRORS, summary="계획 삭제")
def delete_plan(plan_id: int, request: Request):
    if not request.app.state.plans.delete(plan_id):
        raise ApiError(404, "PLAN_NOT_FOUND", "계획을 찾을 수 없습니다.")
    return Response(status_code=204)


# ---------------------------------------------------------------- 실행 로그 (수정 경로 없음)
@logs.get("", response_model=LogSessions, summary="세션 단위 실행 로그 목록")
def list_logs(request: Request):
    return {"sessions": request.app.state.logs.list_sessions()}


@logs.get("/{session_id}", response_model=LogDetail, responses=ERRORS, summary="세션 실행 로그 상세 (발생 순서)")
def get_log(session_id: str, request: Request, run_id: str | None = None):
    events = request.app.state.logs.get_session(session_id, run_id=run_id)
    if not events:
        raise ApiError(404, "LOG_NOT_FOUND", "실행 로그를 찾을 수 없습니다.")
    return {"session_id": session_id, "events": events}


@logs.delete("/{session_id}", status_code=204, responses=ERRORS, summary="세션 실행 로그 삭제")
def delete_log(session_id: str, request: Request):
    if request.app.state.logs.delete_session(session_id) == 0:
        raise ApiError(404, "LOG_NOT_FOUND", "실행 로그를 찾을 수 없습니다.")
    return Response(status_code=204)


# ---------------------------------------------------------------- 시스템
@system.get("/health", response_model=Health, summary="상태와 키 설정 여부 (값은 노출하지 않음)")
def health(request: Request):
    return {"status": "ok", "config": request.app.state.settings.flags()}


@system.get("/tools", response_model=ToolList, summary="등록된 Tool 명세")
def tools(request: Request):
    return {"tools": request.app.state.registry.list_specs()}
