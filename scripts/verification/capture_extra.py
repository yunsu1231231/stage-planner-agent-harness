"""셀프 체크리스트 보완 캡처 — #7(Tool 실패 후 다음 요청 정상), #20(화면에서 계획 삭제), #22(Tool 실패 안내 화면).

8012 카카오 키 무효 백엔드 · 8013 정상 백엔드(LLM 미사용 장면) · 5512 프론트. LLM 약 5회.
실행: .venv/Scripts/python scripts/verification/capture_extra.py
"""
from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "verification"))
sys.path.insert(0, str(ROOT / "backend"))

import requests  # noqa: E402
from capture_screens import DATA, OUT, S1, serve_api, serve_front  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from app.core.config import Settings  # noqa: E402

API_BAD, API_OK, FRONT = "http://127.0.0.1:8012", "http://127.0.0.1:8013", "http://127.0.0.1:5512"
EXPAND = ".messages, .timeline { max-height: none !important; overflow: visible !important; } .topbar { position: static !important; }"


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    for f in DATA.glob("extra_*.db*"):
        f.unlink()
    base = Settings.from_env()
    serve_api(replace(base, kakao_api_key="INVALID-KEY-FOR-VERIFICATION"), 8012, DATA / "extra_bad.db")
    serve_api(base, 8013, DATA / "extra_ok.db")
    serve_front(5512)
    index = json.loads((OUT / "index.json").read_text(encoding="utf-8"))
    index = [s for s in index if not s["file"].startswith(("14_", "15_", "16_"))]
    record: dict = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, locale="ko-KR")

        # ---- #22 Tool 실패 안내 → #7 이어서 다른 요청
        page = ctx.new_page()
        page.add_init_script(f"localStorage.setItem('apiBase', '{API_BAD}'); sessionStorage.clear();")
        page.goto(f"{FRONT}/index.html")
        for i, msg in enumerate([S1, "안녕! 너는 뭘 할 수 있어?"]):
            before = page.locator("#run-meta").inner_text()
            page.fill("#input", msg)
            page.click("#send")
            page.wait_for_function("prev => { const t = document.querySelector('#run-meta').textContent; return t && t !== prev; }",
                                   arg=before, timeout=90000)
            page.wait_for_timeout(300)
            page.add_style_tag(content=EXPAND)
            name = "14_chat_tool_failure" if i == 0 else "15_chat_after_failure"
            page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
            badges = page.locator(".msg.bot .badge").all_inner_texts()
            record[name] = {"run_id": page.locator("#run-meta").inner_text(), "status_badges": badges}
            print(f"  📷 {name}.png  badges={badges}")
        index.append({"file": "14_chat_tool_failure.png", "title": "Tool 실패 안내 — 카카오 키 무효로 주변 장소 AUTH_FAILED, 추천은 유지(일부 정보 실패)·카드에 '주변 장소 조회 실패'",
                      "covers": "4.5 F3019, NF3003"})
        index.append({"file": "15_chat_after_failure.png", "title": "Tool 실패 직후 같은 세션의 다음 요청도 정상 처리 (서비스 중단 없음)",
                      "covers": "F3007, NF3003"})

        # ---- #20 화면에서 계획 삭제 → 목록 즉시 반영
        for body in ({"title": "삭제할 계획", "date": "2026-11-28", "start_time": "15:00", "end_time": "16:40"},
                     {"title": "남길 계획", "date": "2026-11-28", "start_time": "19:00", "end_time": "21:00"}):
            requests.post(f"{API_OK}/api/plans", json=body, timeout=10)
        page2 = ctx.new_page()
        page2.add_init_script(f"localStorage.setItem('apiBase', '{API_OK}');")
        page2.on("dialog", lambda d: d.accept())          # window.confirm('삭제할까요?') 수락
        page2.goto(f"{FRONT}/plans.html")
        page2.wait_for_selector("table", timeout=10000)
        page2.locator("tr", has_text="삭제할 계획").locator("[data-act=delete]").click()
        page2.wait_for_selector("#banner .banner", timeout=10000)
        page2.wait_for_timeout(300)
        page2.screenshot(path=str(OUT / "16_plans_after_delete.png"), full_page=True)
        rows = page2.locator("tbody tr").all_inner_texts()
        record["16_plans_after_delete"] = {"rows": rows, "api_total": requests.get(f"{API_OK}/api/plans", timeout=10).json()["total"]}
        print(f"  📷 16_plans_after_delete.png  rows={len(rows)}")
        index.append({"file": "16_plans_after_delete.png", "title": "계획 관리 화면에서 삭제 → 목록에 즉시 반영, '삭제했습니다' 안내",
                      "covers": "4.4 F3016"})
        browser.close()

    (OUT / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "extra_record.json").write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
