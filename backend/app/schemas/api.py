"""API 요청·응답 Pydantic 모델 (docs/05)."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

DATE = r"^\d{4}-\d{2}-\d{2}$"
HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


# ---------------------------------------------------------------- 대화
class ChatRequest(BaseModel):
    session_id: str | None = Field(None, pattern=r"^[\w-]{1,64}$")
    message: str = Field(..., min_length=1, max_length=1000)


class TimelineEvent(BaseModel):
    event_id: str | None = None
    seq: int
    ts: str
    type: str
    node: str | None = None
    run_id: str | None = None
    payload: dict[str, Any] = {}


class ChatResponse(BaseModel):
    session_id: str
    run_id: str
    status: str
    reply: str
    intent: dict[str, Any] | None = None
    conditions: dict[str, Any] | None = None
    missing: list[str] = []
    notices: list[dict[str, Any]] = []
    recommendations: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    unjudgeable: list[dict[str, Any]] = []
    suggestions: list[str] = []
    replan_count: int = 0
    relaxed: list[str] = []
    tool_failures: list[dict[str, Any]] = []
    facts: dict[str, Any] | None = None
    saved_plan: dict[str, Any] | None = None
    timeline: list[TimelineEvent] = []
    llm_calls: int = 0


# ---------------------------------------------------------------- 계획
class PlanBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    performance_id: str | None = None
    title: str = Field(..., min_length=1, max_length=200)
    venue_name: str | None = Field(None, max_length=200)
    date: str = Field(..., pattern=DATE)
    start_time: str = Field(..., pattern=HHMM)
    end_time: str = Field(..., pattern=HHMM)
    price: int | None = Field(None, ge=0)
    memo: str | None = Field(None, max_length=500)
    source_session_id: str | None = None


class PlanCreate(PlanBase):
    pass


class PlanUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(None, min_length=1, max_length=200)
    venue_name: str | None = Field(None, max_length=200)
    date: str | None = Field(None, pattern=DATE)
    start_time: str | None = Field(None, pattern=HHMM)
    end_time: str | None = Field(None, pattern=HHMM)
    price: int | None = Field(None, ge=0)
    memo: str | None = Field(None, max_length=500)


class Plan(PlanBase):
    model_config = ConfigDict(extra="ignore")
    id: int
    created_at: str
    updated_at: str


class PlanSaveResult(BaseModel):
    plan: Plan
    overlaps: list[Plan]


class PlanList(BaseModel):
    plans: list[Plan]
    total: int


# ---------------------------------------------------------------- 실행 로그
class LogSession(BaseModel):
    session_id: str
    first_at: str
    last_at: str
    run_count: int
    event_count: int
    replan_total: int
    error_count: int
    tool_failure_count: int


class LogSessions(BaseModel):
    sessions: list[LogSession]


class LogDetail(BaseModel):
    session_id: str
    events: list[TimelineEvent]


class AnomalyReport(BaseModel):
    run_id: str
    verdict: str                           # normal | anomaly | undeterminable
    checked: dict[str, str] = {}
    warnings: list[dict[str, Any]] = []
    reason: str | None = None
    event_count: int | None = None
    created_at: str | None = None
    diagnosis: dict[str, Any] | None = None   # 판정과 분리된 LLM 진단 (이상 실행만)


class AnomalyReports(BaseModel):
    session_id: str
    reports: list[AnomalyReport]


# ---------------------------------------------------------------- 시스템
class Health(BaseModel):
    status: str
    config: dict[str, bool]


class ToolInfo(BaseModel):
    name: str
    kind: str
    description: str
    input_schema: dict[str, Any]


class ToolList(BaseModel):
    tools: list[ToolInfo]
