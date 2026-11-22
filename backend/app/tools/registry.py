"""Tool 레지스트리 — F3001 명세 정의·등록 (docs/02 5절).

Agent에는 이름·설명·입력 스키마만 노출한다. call() 은 어떤 경우에도 예외를 던지지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ValidationError

from .base import ErrorCode, ToolResult, never_raises


@dataclass(frozen=True)
class ToolSpec:
    name: str
    kind: Literal["external", "local"]    # 외부 API 툴 / 로컬 서버 API 툴
    description: str                      # LLM이 '언제 쓰는지' 판단하는 유일한 근거
    input_model: type[BaseModel]
    func: Callable[[BaseModel], ToolResult]


class ToolRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._specs:
            raise ValueError(f"이미 등록된 Tool: {spec.name}")
        self._specs[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._specs.get(name)

    def names(self) -> list[str]:
        return list(self._specs)

    def list_specs(self) -> list[dict[str, Any]]:
        return [{"name": s.name, "kind": s.kind, "description": s.description,
                 "input_schema": s.input_model.model_json_schema()} for s in self._specs.values()]

    def call(self, name: str, args: dict[str, Any] | None = None) -> ToolResult:
        spec = self._specs.get(name)
        if spec is None:
            return ToolResult.failure(ErrorCode.UNKNOWN_TOOL, f"등록되지 않은 도구입니다: {name}")
        try:
            inp = spec.input_model.model_validate(args or {})
        except ValidationError as e:
            errs = e.errors()
            fields = ", ".join(".".join(map(str, err["loc"])) or "입력" for err in errs)
            missing = [".".join(map(str, err["loc"])) for err in errs if err["type"] == "missing"]
            # 필수 인자 누락은 Worker 가 LLM 으로 고칠 일이 아니라 되묻거나 멈출 일 (F3021) → detail 로 구분
            detail = f"missing:{','.join(missing)}" if missing else "invalid"
            return ToolResult.failure(ErrorCode.INVALID_INPUT, f"입력값이 올바르지 않습니다: {fields}", detail=detail)
        return never_raises(spec.func)(inp)

    def as_langchain_tools(self) -> list[StructuredTool]:
        def runner(tool_name: str) -> Callable[..., dict]:
            return lambda **kwargs: self.call(tool_name, kwargs).model_dump()
        return [StructuredTool.from_function(func=runner(s.name), name=s.name, description=s.description,
                                             args_schema=s.input_model) for s in self._specs.values()]
