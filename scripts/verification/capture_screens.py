"""검증용 화면 캡처 (명세 4장 '캡처하여 첨부') — Playwright + 설치된 Edge(headless), 실제 LLM·API.

캡처 전용 서버를 따로 띄운다 (실제 데이터와 분리):
  8010 정상 백엔드 · 8011 KOPIS 키를 뺀 백엔드(키 누락 안내) · 5510 프론트 정적 서버
산출물: docs/verification/screenshots/*.png, screenshots/index.json (장면 설명·확인 결과)
실행: .venv/Scripts/python scripts/verification/capture_screens.py   (LLM 약 15회)
"""
from __future__ import annotations

import functools
import http.server
import json
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import requests  # noqa: E402
import uvicorn  # noqa: E402
from playwright.sync_api import Page, sync_playwright  # noqa: E402

from app.api.app import create_app  # noqa: E402
from app.core.config import Settings  # noqa: E402

OUT = ROOT / "docs" / "verification" / "screenshots"
DATA = ROOT / "data" / "capture"
API, API_NOKEY, FRONT = "http://127.0.0.1:8010", "http://127.0.0.1:8011", "http://127.0.0.1:5510"
S1 = "이번 토요일 오후 2시 이후에 대학로에서 5만원 이하 연극 보고 6시 전에는 끝내고 싶어. 끝나고 갈 식당도 알려줘"
REPLAN = "11월 29일 일요일 저녁 7시 이후에 시작해서 9시 반 전에 끝나는 3만원 이하 대학로 뮤지컬 찾아줘"
TYPO = "여신님 보고계셔 러닝타임이 몇 분이야?"
LIMIT = "다음 주 수요일 오전 9시 이후에 시작해서 오전 11시 전에 끝나는 대학로 연극 있어?"

shots: list[dict] = []


# ---------------------------------------------------------------- 서버
def serve_api(settings: Settings, port: int, db: Path) -> None:
    app = create_app(settings=settings, db_path=db)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            return
        time.sleep(0.1)
    raise RuntimeError(f"API {port} 시작 실패")


def serve_front(port: int) -> None:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT / "frontend"))
    handler.log_message = lambda *a, **k: None
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()


# ---------------------------------------------------------------- 화면 조작
EXPAND = ".messages, .timeline { max-height: none !important; overflow: visible !important; }"


def shot(page: Page, name: str, title: str, covers: str, full_page: bool = True, element: str | None = None) -> None:
    """캡처 순간에만 스크롤 영역을 펼쳐 응답·타임라인 전체가 한 장에 담기게 한다 (화면 동작은 그대로)."""
    page.add_style_tag(content=EXPAND)
    path = OUT / f"{name}.png"
    (page.locator(element).screenshot(path=str(path)) if element else page.screenshot(path=str(path), full_page=full_page))
    shots.append({"file": f"{name}.png", "title": title, "covers": covers})
    print(f"  📷 {name}.png — {title}")


def open_chat(page: Page, api: str) -> None:
    page.add_init_script(f"localStorage.setItem('apiBase', '{api}'); sessionStorage.clear();")
    page.goto(f"{FRONT}/index.html")
    page.wait_for_load_state("networkidle")


def send(page: Page, message: str, timeout_s: int = 90) -> str:
    before = page.locator("#run-meta").inner_text()
    page.fill("#input", message)
    page.click("#send")
    page.wait_for_function("prev => { const t = document.querySelector('#run-meta').textContent; return t && t !== prev; }",
                           arg=before, timeout=timeout_s * 1000)
    page.wait_for_timeout(300)
    return page.locator("#run-meta").inner_text()


def new_chat(page: Page) -> None:
    page.click("#new-chat")
    page.wait_for_timeout(300)


# ---------------------------------------------------------------- 장면
def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)
    for f in list(DATA.glob("*.db*")) + list(OUT.glob("*.png")):
        f.unlink()
    base = Settings.from_env()
    serve_api(base, 8010, DATA / "capture.db")
    serve_api(replace(base, kopis_api_key=None), 8011, DATA / "capture_nokey.db")
    serve_front(5510)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, locale="ko-KR", device_scale_factor=1)
        page = ctx.new_page()

        print("1) API 문서")
        page.goto(f"{API}/docs")
        page.wait_for_selector(".opblock", timeout=30000)
        shot(page, "01_api_docs", "FastAPI 문서 — 대화·계획·실행 로그·시스템 경로 분리", "4.5 F3017")

        print("2) 대화 — 처리 중 → 추천")
        open_chat(page, API)
        page.fill("#input", S1)
        page.click("#send")
        page.wait_for_selector(".pending .spinner", timeout=5000)
        page.wait_for_timeout(1500)
        shot(page, "02_chat_processing", "처리 중 상태 — 스피너와 경과 초, 실행 과정 패널 '실행 중'", "4.5 F3019")
        page.wait_for_function("() => document.querySelector('#run-meta').textContent.startsWith('r-')", timeout=90000)
        page.wait_for_timeout(300)
        shot(page, "03_chat_recommendation", "추천 카드(회차·종료·가격·판단 근거·근거 Tool·주변 식당) + 실행 과정 타임라인(역할·메시지·검증)",
             "4.2 F3008·F3011, 4.5 F3019, 4.6 F3021")

        print("3) 카드에서 저장 → 겹치는 계획 추가")
        page.locator("[data-save]").first.click()
        page.wait_for_selector("[data-save-result] .badge", timeout=15000)
        saved = requests.get(f"{API}/api/plans", timeout=10).json()["plans"][0]
        requests.post(f"{API}/api/plans", timeout=10, json={
            "title": "친구와 저녁 약속", "venue_name": "혜화역", "date": saved["date"],
            "start_time": saved["start_time"], "end_time": "17:30", "memo": "겹침 확인용"})
        requests.post(f"{API}/api/plans", timeout=10, json={
            "title": "다음 날 전시", "venue_name": "국립현대미술관", "date": "2026-11-29",
            "start_time": "11:00", "end_time": "13:00"})
        shot(page, "04_chat_saved_card", "추천 카드의 '이 계획 저장' 결과 표시", "4.4 F3015", element=".cards")

        print("4) 재계획 타임라인")
        new_chat(page)
        send(page, REPLAN)
        shot(page, "05_chat_replan", "재계획 — 타임라인의 주황색 '↻ 재계획 #n' 구분과 조건 완화 안내", "4.2 F3009, 4.5 F3019")
        shot(page, "05b_timeline_replan_panel", "실행 과정 패널 (재계획 지점 확대)", "4.5 F3019", element="aside.panel")

        print("5) Worker LLM 재시도 (공연명 오타)")
        new_chat(page)
        send(page, TYPO)
        shot(page, "06_chat_worker_retry", "Worker 판단 [LLM] retry — 검색어 수정 후 같은 Tool 재호출", "4.6 F3021")

        print("6) 재계획 상한 → 이상 징후 판정")
        new_chat(page)
        send(page, LIMIT)
        shot(page, "07_chat_limit_reached", "재계획 상한 도달 — 사유·조정 제안, 검증(로깅 Agent) 이상 → 작업 목록 재구성",
             "4.2 F3009, NF3004, 4.6 F3020·F3021")
        limit_session = page.evaluate("sessionStorage.getItem('sessionId')")

        print("7) 키 누락 안내")
        page2 = ctx.new_page()
        open_chat(page2, API_NOKEY)
        page2.wait_for_selector("#banner .banner", timeout=10000)
        send(page2, S1, timeout_s=60)
        shot(page2, "08_key_missing", "API 키 누락 — 누락된 키 이름만 배너로 안내 (값 노출 없음), 응답 '설정 필요'", "4.5 F3019, NF3002")
        page2.close()

        print("8) 계획 관리 — 겹침 표시 → 수정")
        page.goto(f"{FRONT}/plans.html")
        page.wait_for_selector("table", timeout=10000)
        shot(page, "09_plans_overlap", "계획 관리 — 같은 날 시간 겹침 노란 강조·'겹침' 배지, 생성 일시", "4.4 F3015")
        row = page.locator("tr", has_text="친구와 저녁 약속")
        row.locator("[data-act=edit]").click()
        edit = page.locator("tr.selected")
        edit.locator("[name=start_time]").fill("19:00")
        edit.locator("[name=end_time]").fill("21:00")
        edit.locator("[data-act=save]").click()
        page.wait_for_selector("#banner .banner", timeout=10000)
        page.wait_for_timeout(300)
        shot(page, "10_plans_after_edit", "계획 수정 후 즉시 반영 — 시간 변경으로 겹침 해소, 결과 안내", "4.4 F3016")

        print("9) 실행 로그 — 이상 징후 판정·진단")
        for _ in range(40):          # 진단은 로깅 Agent 가 백그라운드로 수행 → 붙을 때까지 대기
            reps = requests.get(f"{API}/api/logs/{limit_session}/anomalies", timeout=10).json()["reports"]
            if reps and reps[-1].get("diagnosis"):
                break
            time.sleep(0.5)
        page.goto(f"{FRONT}/logs.html")
        page.wait_for_selector("table", timeout=10000)
        shot(page, "11_logs_sessions", "실행 로그 — 세션 목록(실행·이벤트·재계획·오류 수)", "4.3 F3014")
        page.click(f"[data-open='{limit_session}']")
        page.wait_for_selector("#detail .run-divider", timeout=10000)
        page.wait_for_timeout(300)
        shot(page, "12_logs_anomaly", "실행 로그 상세 — 규칙 판정 '이상 징후'(근거 seq) + LLM 원인 진단(별도) + 타임라인", "4.3, 4.6 F3020")
        page.locator("#detail details").first.evaluate("d => d.open = true")
        shot(page, "13_logs_raw_events", "원본 이벤트 (seq·type·node·payload 그대로 — 수정 기능 없음)", "4.3 F3013·F3014",
             element="#detail")
        browser.close()

    (OUT / "index.json").write_text(json.dumps(shots, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"완료: {len(shots)}장 → {OUT}")


if __name__ == "__main__":
    main()
