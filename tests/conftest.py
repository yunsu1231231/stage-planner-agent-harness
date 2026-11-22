"""공통 테스트 하네스 (docs/06_test_strategy.md).

- 기본 실행은 오프라인: live 마커가 없는 테스트에서 실제 소켓 연결을 차단한다.
- fixture 로더: tests/fixtures/ (기획 검증에서 녹화한 실제 응답, 키 마스킹)
- fake_http / fake_llm 팩토리
"""
from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from fakes import FakeLLM, FakeSession

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"


class NetworkBlocked(RuntimeError):
    """오프라인 테스트에서 실제 네트워크 연결을 시도했다."""


@pytest.fixture(autouse=True)
def _block_network(request, monkeypatch):
    if request.node.get_closest_marker("live"):
        return

    def guard(*args, **kwargs):
        raise NetworkBlocked("오프라인 테스트에서 실제 네트워크 연결 시도 — FakeSession/FakeLLM 을 주입하세요")

    monkeypatch.setattr(socket.socket, "connect", guard)
    monkeypatch.setattr(socket, "create_connection", guard)


@pytest.fixture
def root() -> Path:
    return ROOT


@pytest.fixture
def fixture_text():
    def load(name: str) -> str:
        return (FIXTURES / name).read_text(encoding="utf-8")
    return load


@pytest.fixture
def fixture_json(fixture_text):
    def load(name: str):
        return json.loads(fixture_text(name))
    return load


@pytest.fixture
def fake_http() -> FakeSession:
    return FakeSession()


@pytest.fixture
def fake_llm():
    def make(*script) -> FakeLLM:
        return FakeLLM(list(script))
    return make
