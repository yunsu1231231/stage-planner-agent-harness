"""Tool 공통 응답 형식과 실패 코드 (docs/02 1~2절, F3001).

모든 Tool은 예외를 밖으로 던지지 않고 ToolResult 하나로 답한다.
  성공: {ok: true,  data: {...}, error: null, meta: {...}}
  실패: {ok: false, data: null, error: {code, message, retryable, partial?, detail?}, meta: {...}}
"""
from __future__ import annotations

import functools
from enum import StrEnum
from typing import Any, Callable

from pydantic import BaseModel, Field


class ErrorCode(StrEnum):
    MISSING_API_KEY = "MISSING_API_KEY"
    AUTH_FAILED = "AUTH_FAILED"
    INVALID_INPUT = "INVALID_INPUT"
    NO_RESULT = "NO_RESULT"
    NOT_FOUND = "NOT_FOUND"
    NO_RUNTIME = "NO_RUNTIME"
    NO_SCHEDULE = "NO_SCHEDULE"
    NO_PRICE = "NO_PRICE"
    UPSTREAM_ERROR = "UPSTREAM_ERROR"
    TIMEOUT = "TIMEOUT"
    RATE_LIMITED = "RATE_LIMITED"
    UNKNOWN_TOOL = "UNKNOWN_TOOL"


# 인자를 고치면 결과가 달라질 수 있는 실패 (F3021 Worker가 LLM 판단을 요청할 수 있는 경우)
RETRYABLE = frozenset({ErrorCode.INVALID_INPUT, ErrorCode.NO_RESULT, ErrorCode.NOT_FOUND})
# 다시 해도 같은 결과 → 재계획 없이 즉시 안내 (docs/04 4.3)
FATAL = frozenset({ErrorCode.MISSING_API_KEY, ErrorCode.AUTH_FAILED, ErrorCode.RATE_LIMITED})


class ToolError(BaseModel):
    code: ErrorCode
    message: str                                   # 사용자에게 보여도 되는 문장
    retryable: bool
    partial: dict[str, Any] | None = None          # 제외 사유 표시용 부분 정보 (예: 제목)
    detail: str | None = None                      # 진단용 (예외 타입명 등). 키·URL은 넣지 않는다


class ToolResult(BaseModel):
    ok: bool
    data: dict[str, Any] | None = None
    error: ToolError | None = None
    meta: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def success(cls, data: dict[str, Any], **meta: Any) -> "ToolResult":
        return cls(ok=True, data=data, meta=meta)

    @classmethod
    def failure(cls, code: ErrorCode, message: str, *, partial: dict[str, Any] | None = None,
                detail: str | None = None, **meta: Any) -> "ToolResult":
        return cls(ok=False, error=ToolError(code=code, message=message, retryable=code in RETRYABLE,
                                             partial=partial, detail=detail), meta=meta)


def never_raises(fn: Callable[..., ToolResult]) -> Callable[..., ToolResult]:
    """Tool 함수 안에서 무슨 일이 나도 UPSTREAM_ERROR 로 바꿔 돌려준다 (NF3003).
    예외 메시지는 URL·키를 담을 수 있으므로 버리고 타입명만 detail 에 남긴다."""
    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> ToolResult:
        try:
            result = fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001 — 의도적으로 모든 예외를 실패 형식으로 변환
            return ToolResult.failure(ErrorCode.UPSTREAM_ERROR, "외부 서비스 응답을 처리하지 못했습니다.",
                                      detail=type(e).__name__)
        if not isinstance(result, ToolResult):
            return ToolResult.failure(ErrorCode.UPSTREAM_ERROR, "도구가 올바른 형식으로 응답하지 않았습니다.",
                                      detail=type(result).__name__)
        return result
    return wrapper
