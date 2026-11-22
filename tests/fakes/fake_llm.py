"""가짜 LLM — 그래프 테스트를 결정적으로 만들기 위한 대역 (docs/06 3절).

ChatOpenAI 중 우리가 쓰는 표면만 흉내 낸다:
  - llm.invoke(messages)                       → AIMessage(content=...)
  - llm.with_structured_output(Schema).invoke  → Schema 인스턴스
  - llm.bind_tools(tools).invoke               → AIMessage(tool_calls=[...])

응답은 미리 적어 둔 대본(script)에서 순서대로 꺼낸다. 대본보다 많이 호출되면
UnexpectedLLMCall 로 실패한다 → "이 경로에서는 LLM을 N번만 불러야 한다"를 검증할 수 있다
(예: F3021 정상 경로 Worker LLM 호출 0회).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import AIMessage


class UnexpectedLLMCall(AssertionError):
    """대본에 없는 LLM 호출이 발생했다."""


@dataclass
class LLMCall:
    kind: str          # "chat" | "structured" | "tools"
    input: Any
    schema: Any = None
    tools: list[str] = field(default_factory=list)


class FakeLLM:
    def __init__(self, script: list[Any] | None = None, name: str = "fake-llm"):
        self._script = list(script or [])
        self.calls: list[LLMCall] = []
        self.model_name = name

    # ---- 대본 관리 -------------------------------------------------------------
    def push(self, *responses: Any) -> "FakeLLM":
        self._script.extend(responses)
        return self

    @property
    def call_count(self) -> int:
        return len(self.calls)

    @property
    def remaining(self) -> int:
        return len(self._script)

    def _next(self, call: LLMCall) -> Any:
        self.calls.append(call)
        if not self._script:
            raise UnexpectedLLMCall(
                f"FakeLLM: 대본에 없는 {len(self.calls)}번째 호출 (kind={call.kind}, input={str(call.input)[:200]})"
            )
        resp = self._script.pop(0)
        if isinstance(resp, BaseException):
            raise resp
        if callable(resp):
            resp = resp(call)
        return resp

    # ---- ChatOpenAI 표면 --------------------------------------------------------
    def invoke(self, input: Any, config: Any = None, **kwargs: Any) -> AIMessage:
        resp = self._next(LLMCall("chat", input))
        return resp if isinstance(resp, AIMessage) else AIMessage(content=str(resp))

    def with_structured_output(self, schema: Any, **kwargs: Any) -> "_Structured":
        return _Structured(self, schema)

    def bind_tools(self, tools: list[Any], **kwargs: Any) -> "_ToolBound":
        names = [getattr(t, "name", None) or (t.get("name") if isinstance(t, dict) else str(t)) for t in tools]
        return _ToolBound(self, names)


class _Structured:
    def __init__(self, parent: FakeLLM, schema: Any):
        self.parent, self.schema = parent, schema

    def invoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
        resp = self.parent._next(LLMCall("structured", input, schema=self.schema))
        if isinstance(resp, dict) and hasattr(self.schema, "model_validate"):
            return self.schema.model_validate(resp)   # 대본이 스키마와 어긋나면 여기서 바로 실패
        return resp


class _ToolBound:
    def __init__(self, parent: FakeLLM, tool_names: list[str]):
        self.parent, self.tool_names = parent, tool_names

    def invoke(self, input: Any, config: Any = None, **kwargs: Any) -> AIMessage:
        resp = self.parent._next(LLMCall("tools", input, tools=self.tool_names))
        if isinstance(resp, AIMessage):
            return resp
        if isinstance(resp, str):
            return AIMessage(content=resp)
        # [{"name": ..., "args": {...}}, ...] → tool_calls
        calls = [{"name": c["name"], "args": c.get("args", {}), "id": c.get("id", f"call_{i}"), "type": "tool_call"}
                 for i, c in enumerate(resp)]
        unknown = [c["name"] for c in calls if c["name"] not in self.tool_names]
        if unknown:
            raise AssertionError(f"FakeLLM 대본이 바인딩되지 않은 Tool을 호출: {unknown} (bound={self.tool_names})")
        return AIMessage(content="", tool_calls=calls)
