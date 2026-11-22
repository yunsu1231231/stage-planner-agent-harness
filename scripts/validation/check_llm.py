"""C1, C2: GMS(OpenAI 호환) LLM 연결 및 Tool 선택 검증.

실행: .venv/Scripts/python scripts/validation/check_llm.py
"""
from __future__ import annotations

import time

from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from _common import env, record

KEY, BASE_URL, MODEL = env("LLM_API_KEY"), env("LLM_BASE_URL"), env("LLM_MODEL") or "gpt-4.1-mini"


@tool
def search_performances(start_date: str, region: str | None = None, genre: str | None = None) -> dict:
    """사용자가 볼 공연을 아직 정하지 않았을 때, 날짜·지역·장르 조건으로 후보 공연 목록을 찾을 때 사용한다.
    start_date는 YYYY-MM-DD 형식이다."""
    return {}


def main() -> None:
    if not KEY:
        record("C1", False, "LLM_API_KEY 가 .env 에 없음")
        return

    llm = ChatOpenAI(model=MODEL, api_key=KEY, base_url=BASE_URL, timeout=30, max_retries=1)

    # ---- C1: 단순 호출 ----
    t0 = time.perf_counter()
    try:
        resp = llm.invoke("한 단어로만 답해: 대한민국의 수도는?")
    except Exception as e:  # 검증 스크립트이므로 원인을 그대로 기록 (키는 메시지에 포함되지 않음)
        record("C1", False, f"{type(e).__name__}: {str(e)[:200]}", model=MODEL, base_url=BASE_URL)
        return
    record("C1", True, f"응답='{resp.content.strip()}'", model=MODEL, base_url=BASE_URL,
           latency_s=round(time.perf_counter() - t0, 2))

    # ---- C2: Tool 명세를 넘겼을 때 Tool 호출을 선택하는지 / 인사에는 선택하지 않는지 ----
    bound = llm.bind_tools([search_performances])
    r1 = bound.invoke("오늘은 2026-11-21이야. 이번 토요일(2026-11-21) 대학로에서 볼 연극 찾아줘")
    r2 = bound.invoke("안녕! 너는 뭘 할 수 있어?")
    picked = [c["name"] for c in r1.tool_calls]
    record("C2", picked == ["search_performances"] and not r2.tool_calls,
           f"계획요청 tool_calls={picked}, 인사 tool_calls={[c['name'] for c in r2.tool_calls]}",
           args=r1.tool_calls[0]["args"] if r1.tool_calls else None)


if __name__ == "__main__":
    main()
