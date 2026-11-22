from __future__ import annotations

import pytest

from agents.world import TODAY, FakeWorld
from fakes import FakeLLM


class Saver:
    """confirm_plan 저장 함수 대역 (M3에서 PlanRepository 로 교체)."""
    def __init__(self, overlaps=None):
        self.saved: list[dict] = []
        self.overlaps = overlaps or []

    def __call__(self, plan: dict) -> dict:
        self.saved.append(plan)
        return {"plan": {"id": len(self.saved), **plan}, "overlaps": self.overlaps}


@pytest.fixture
def make_agent():
    from app.agents.graph import MainAgent
    from app.agents.memory import MemoryStore

    def make(world: FakeWorld, *script, memory=None, publish=None, save_plan=None, registry=None, llm="default"):
        llm_obj = FakeLLM(list(script)) if llm == "default" else llm
        events: list[dict] = []
        agent = MainAgent(llm=llm_obj, registry=registry or world.registry(), memory=memory or MemoryStore(),
                          publish=publish if publish is not None else events.append,
                          save_plan=save_plan, today=lambda: TODAY)
        return agent, llm_obj, events
    return make


@pytest.fixture
def saver():
    return Saver()
