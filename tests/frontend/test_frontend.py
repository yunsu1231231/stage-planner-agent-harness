"""프론트엔드 하네스 (F3018, F3019) — JS 단위 테스트 실행, 프론트↔백엔드 API 계약, 화면 구성 가드."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FRONT = ROOT / "frontend"
JS = sorted((FRONT / "js").glob("*.js"))


def test_js_unit_tests_pass():
    node = shutil.which("node")
    if not node:
        pytest.skip("node 없음")
    files = [str(p) for p in sorted((FRONT / "tests").glob("*.test.mjs"))]
    proc = subprocess.run([node, "--test", *files], cwd=FRONT, capture_output=True)
    out = (proc.stdout + proc.stderr).decode("utf-8", "replace")
    assert proc.returncode == 0, out[-3000:]


def _frontend_api_calls() -> set[tuple[str, str]]:
    """js 에서 api("METHOD", `/api/...`) 형태 호출을 모은다 → (method, 경로 템플릿)."""
    calls = set()
    for f in JS:
        for method, path in re.findall(r"""api\(\s*["'](GET|POST|PATCH|PUT|DELETE)["']\s*,\s*[`"'](/api/[^`"'?]*)""",
                                       f.read_text(encoding="utf-8")):
            calls.add((method.lower(), re.sub(r"\$\{[^}]+\}", "{param}", path)))
    return calls


def test_frontend_calls_only_existing_api_routes():
    """계약 테스트: 백엔드 경로가 바뀌면 화면이 조용히 깨지는 것을 막는다."""
    from fastapi.testclient import TestClient

    from app.api.app import create_app
    from app.core.config import Settings
    from app.tools.factory import build_registry
    app = create_app(settings=Settings(None, None, "m", None, None), llm=None, registry=build_registry(None, None),
                     db_path=ROOT / "data" / "_contract_test.db")
    spec = TestClient(app).get("/openapi.json").json()["paths"]
    app.state.plans.db.close()
    (ROOT / "data" / "_contract_test.db").unlink(missing_ok=True)
    routes = {(m, re.sub(r"\{[^}]+\}", "{param}", p)) for p, ops in spec.items() for m in ops}
    calls = _frontend_api_calls()
    assert len(calls) >= 9, f"프론트 API 호출을 거의 찾지 못함: {calls}"
    missing = sorted(calls - routes)
    assert not missing, f"백엔드에 없는 API 를 호출: {missing}"


def test_only_dom_helper_touches_innerhtml():
    """모든 동적 값은 dom.js 의 html`` 이스케이프를 거쳐야 한다."""
    offenders = [f.name for f in JS if f.name != "dom.js" and "innerHTML" in f.read_text(encoding="utf-8")]
    assert not offenders, f"innerHTML 직접 사용: {offenders}"


@pytest.mark.parametrize("page,script", [("index.html", "chat.js"), ("plans.html", "plans.js"), ("logs.html", "logs.js")])
def test_pages_exist_link_each_other_and_load_their_module(page, script):
    text = (FRONT / page).read_text(encoding="utf-8")
    assert f'type="module" src="js/{script}"' in text
    for other in ("index.html", "plans.html", "logs.html"):
        assert f'href="{other}"' in text, f"{page} 에 {other} 링크 없음"
    assert (FRONT / "js" / script).exists()


def test_frontend_never_mentions_key_values_or_raw_errors():
    for f in JS:
        text = f.read_text(encoding="utf-8")
        assert ".stack" not in text and "console.error(e)" not in text, f.name
