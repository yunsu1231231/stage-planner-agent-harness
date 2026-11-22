from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agents.world import TODAY, s1_world
from app.core.config import Settings
from fakes import FakeLLM

SECRET = "fake-llm-key-SECRET-VALUE-do-not-leak"   # 실제 키 형식(sk-...)과 다르게 — 가드 테스트 오탐 방지
SETTINGS = Settings(llm_api_key=SECRET, llm_base_url=None, llm_model="fake", kopis_api_key="KOPIS-SECRET",
                    kakao_api_key="KAKAO-SECRET")


@pytest.fixture
def make_client(tmp_path):
    from app.api.app import create_app

    def make(*script, world=None, settings=SETTINGS, attach_logger=True, llm="default"):
        world = world or s1_world()
        llm_obj = FakeLLM(list(script)) if llm == "default" else llm
        app = create_app(settings=settings, llm=llm_obj, registry=world.registry(), db_path=tmp_path / "api.db",
                         today=lambda: TODAY, attach_logger=attach_logger)
        return TestClient(app), llm_obj, world
    return make
