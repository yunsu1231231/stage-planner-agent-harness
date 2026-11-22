"""LLM 생성 — OpenAI 호환 (개인 OpenAI 키 또는 SSAFY GMS). 키가 없으면 None → Agent가 config_missing 으로 안내."""
from __future__ import annotations

from langchain_openai import ChatOpenAI

from .config import Settings


def make_llm(settings: Settings, temperature: float = 0.0) -> ChatOpenAI | None:
    if not settings.llm_api_key:
        return None
    return ChatOpenAI(model=settings.llm_model, api_key=settings.llm_api_key, base_url=settings.llm_base_url,
                      temperature=temperature, timeout=30, max_retries=1)
