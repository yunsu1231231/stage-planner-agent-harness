"""D1, D2, P1: 설계 시험 (명세 2.7 '설계 시험').

04 Agent 설계를 실제 KOPIS/카카오 데이터로 손으로 따라가 본다. LLM은 쓰지 않는다
(analyze 결과는 시나리오에 미리 적어 둔 조건으로 대신한다).

- D1: S1을 analyze → plan → execute → judge → enrich 순서로 따라가며 모든 Tool 입력이
      앞 단계 결과로 채워지는지 확인
- D2: S2(재계획 기대), S3(상한 도달 기대)로 재계획 사다리·상한·캐시 재사용 확인
- P1: 공연 시각(dtguidance)·러닝타임·가격 텍스트 패턴 수집 → 파서 설계·테스트 fixture

실행: .venv/Scripts/python scripts/validation/design_trial.py
산출물: docs/validation/design_trial.json, docs/validation/samples/kopis_detail_pool.json
"""
from __future__ import annotations

import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

from _common import ROOT, SAMPLES, env, record

KOPIS = "https://www.kopis.or.kr/openApi/restful"
UA = {"User-Agent": "ai-planner/0.1 (SSAFY AI core project)"}
KEY, KAKAO = env("KOPIS_API_KEY"), env("KAKAO_REST_API_KEY")
POOL_FILE = SAMPLES / "kopis_detail_pool.json"
OUT = ROOT / "docs" / "validation" / "design_trial.json"
MAX_DETAIL_PER_STEP = 15
REPLAN_LIMIT = 3
WEEKDAYS = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]

# ---------------------------------------------------------------- 호출 계측 (tool_cache 재현)
calls = {"search_performances": 0, "get_performance_detail": 0, "venue": 0, "kakao": 0}
cache_hits = {"get_performance_detail": 0}
detail_cache: dict[str, dict] = json.loads(POOL_FILE.read_text(encoding="utf-8")) if POOL_FILE.exists() else {}
fresh_details: set[str] = set()


SESSION = requests.Session()
SESSION.headers.update(UA)
latencies: list[float] = []
retries = {"count": 0}
bad_bodies: list[dict] = []


def kopis(path: str, **params) -> list[ET.Element]:
    # 검증 발견: 연속 호출 시 KOPIS가 연결을 끊음(ConnectionReset) + 응답 3~9초 → 세션 재사용 + 백오프 재시도
    for attempt in range(3):
        t0 = time.perf_counter()
        try:
            r = SESSION.get(f"{KOPIS}/{path}", params={"service": KEY, **params}, timeout=15)
            latencies.append(time.perf_counter() - t0)
            r.encoding = "utf-8"
            return ET.fromstring(r.text).findall("db")
        except ET.ParseError:
            # 검증 발견: 부하 시 XML이 아닌 응답이 옴 → 본문 앞부분을 남기고 재시도
            bad_bodies.append({"path": path.split("/")[0], "status": r.status_code,
                               "body_head": r.text[:200].replace(KEY or "", "***")})
            retries["count"] += 1
            time.sleep(2 * (attempt + 1))
        except requests.RequestException as e:
            bad_bodies.append({"path": path.split("/")[0], "exception": type(e).__name__})
            retries["count"] += 1
            time.sleep(2 * (attempt + 1))
    return []


def t(el: ET.Element, tag: str) -> str:
    return (el.findtext(tag) or "").strip()


# ---------------------------------------------------------------- Tool (시험용 최소 구현)
def search_performances(d: str, region: dict, genre: str | None, page: int, rows: int = 20) -> list[dict]:
    calls["search_performances"] += 1
    ymd = d.replace("-", "")
    params = {"stdate": ymd, "eddate": ymd, "cpage": page, "rows": rows, "prfstate": "02", **region}
    if genre:
        params["shcate"] = genre
    return [{"performance_id": t(e, "mt20id"), "title": t(e, "prfnm"), "genre": t(e, "genrenm"),
             "venue_name": t(e, "fcltynm")} for e in kopis("pblprfr", **params) if t(e, "mt20id")]


def get_performance_detail(pid: str) -> dict:
    # tool_cache는 세션(=이 프로세스) 안에서만 유효. 이전 실행의 pool 파일은 fixture 수집용일 뿐 캐시로 쓰지 않는다.
    if pid in fresh_details:
        cache_hits["get_performance_detail"] += 1
        return detail_cache[pid]
    calls["get_performance_detail"] += 1
    fresh_details.add(pid)
    dbs = kopis(f"pblprfr/{pid}")
    if not dbs:
        detail_cache[pid] = {"performance_id": pid, "error": "NOT_FOUND"}
    else:
        e = dbs[0]
        detail_cache[pid] = {k: t(e, k) for k in ("mt20id", "prfnm", "prfpdfrom", "prfpdto", "fcltynm", "mt10id",
                                                  "prfruntime", "prfage", "pcseguidance", "dtguidance", "genrenm")}
    return detail_cache[pid]


# ---------------------------------------------------------------- 파서 (P1 — 설계 후보)
def parse_runtime(s: str) -> int | None:
    h = re.search(r"(\d+)\s*시간", s)
    m = re.search(r"(\d+)\s*분", s)
    if not h and not m:
        return None
    return (int(h.group(1)) * 60 if h else 0) + (int(m.group(1)) if m else 0)


def parse_price(s: str) -> int | None:
    if "무료" in s:
        return 0
    nums = [int(x.replace(",", "")) for x in re.findall(r"(\d[\d,]*)\s*원", s)]
    return min(nums) if nums else None


def parse_schedule(s: str) -> dict[str, list[str]] | None:
    """'화요일 ~ 금요일(19:30), 토요일 ~ 일요일(14:00,18:00), HOL(14:00)' → {요일: [시각]}"""
    out: dict[str, list[str]] = {}
    for days, times in re.findall(r"([^(),]+?)\s*\(([^)]*)\)", s):
        days = days.strip()
        ts = re.findall(r"\d{1,2}:\d{2}", times)
        if not ts:
            continue
        rng = re.match(r"(\S+요일)\s*~\s*(\S+요일)", days)
        if rng and rng.group(1) in WEEKDAYS and rng.group(2) in WEEKDAYS:
            a, b = WEEKDAYS.index(rng.group(1)), WEEKDAYS.index(rng.group(2))
            keys = WEEKDAYS[a:b + 1] if a <= b else WEEKDAYS[a:] + WEEKDAYS[:b + 1]
        elif days in WEEKDAYS:
            keys = [days]
        elif days.upper().startswith("HOL"):
            keys = ["HOL"]
        else:
            keys = []  # 해석 불가 표기 → 판단 불가로 남긴다
        for k in keys:
            out.setdefault(k, []).extend(ts)
    return out or None


def hm(x: str) -> int:
    h, m = x.split(":")
    return int(h) * 60 + int(m)


def fmt(mins: int) -> str:
    return f"{mins // 60:02d}:{mins % 60:02d}"


# ---------------------------------------------------------------- judge (04 문서 4.4 계산식)
def judge(c: dict, cond: dict) -> dict:
    d = get_performance_detail(c["performance_id"])
    base = {"performance_id": c["performance_id"], "title": d.get("prfnm") or c["title"]}
    if d.get("error"):
        return {**base, "result": "unjudgeable", "reason_code": d["error"]}
    runtime, price, sched = parse_runtime(d["prfruntime"]), parse_price(d["pcseguidance"]), parse_schedule(d["dtguidance"])
    if runtime is None:
        return {**base, "result": "unjudgeable", "reason_code": "NO_RUNTIME"}
    end_by = hm(cond["end_by"]) if cond.get("end_by") else None
    if sched is None:
        latest = fmt(end_by - runtime) if end_by else None
        return {**base, "result": "unjudgeable", "reason_code": "NO_SCHEDULE",
                "reason": f"회차 미상 → 늦어도 {latest} 시작이어야 함" if latest else "회차 미상"}
    times = sched.get(WEEKDAYS[date.fromisoformat(cond["date"]).weekday()], [])
    if not times:
        return {**base, "result": "excluded", "reason_code": "NO_SHOW_ON_DAY", "reason": f"해당 요일 회차 없음 ({d['dtguidance']})"}
    if cond.get("budget_max") is not None and price is not None and price > cond["budget_max"]:
        return {**base, "result": "excluded", "reason_code": "OVER_BUDGET", "reason": f"{price:,}원 > {cond['budget_max']:,}원"}
    reasons = []
    for st in sorted(set(times)):
        s, e = hm(st), hm(st) + runtime
        if cond.get("earliest_start") and s < hm(cond["earliest_start"]):
            reasons.append(f"{st} 시작 < 희망 {cond['earliest_start']}")
            continue
        if end_by is not None and e > end_by:
            reasons.append(f"{st}+{runtime}분={fmt(e)} 종료 > 제한 {cond['end_by']}")
            continue
        return {**base, "result": "eligible", "start": st, "end": fmt(e), "runtime_min": runtime, "min_price": price,
                "price_unknown": price is None, "venue_id": d["mt10id"], "venue_name": d["fcltynm"],
                "criteria": f"{st}+{runtime}분={fmt(e)} ≤ {cond.get('end_by')}, 가격 {price}"}
    return {**base, "result": "excluded", "reason_code": "TIME_MISMATCH", "reason": "; ".join(reasons)}


# ---------------------------------------------------------------- 재계획 사다리 (04 문서 4.2)
LADDER = [
    ("initial", lambda q: q),
    ("expand_pool", lambda q: {**q, "page": q["page"] + 1}),
    ("drop_genre", lambda q: {**q, "genre": None, "page": 1}),
    ("widen_region", lambda q: {**q, "region": {"signgucode": "11"}, "page": 1}),
]


def run_scenario(sid: str, cond: dict, query: dict) -> dict:
    before = dict(calls)
    hits_before = cache_hits["get_performance_detail"]
    seen: set[str] = set()
    steps, final = [], None
    for plan_version, (strategy, mutate) in enumerate(LADDER):
        if plan_version > 0:
            query = mutate(query)
        cands = [c for c in search_performances(cond["date"], query["region"], query["genre"], query["page"])
                 if c["performance_id"] not in seen][:MAX_DETAIL_PER_STEP]
        seen.update(c["performance_id"] for c in cands)
        evals = [judge(c, cond) for c in cands]
        eligible = [e for e in evals if e["result"] == "eligible"]
        steps.append({"plan_version": plan_version, "strategy": strategy, "candidates": len(cands),
                      "eligible": len(eligible),
                      "excluded": sum(e["result"] == "excluded" for e in evals),
                      "unjudgeable": sum(e["result"] == "unjudgeable" for e in evals),
                      "exclusion_samples": [e for e in evals if e["result"] != "eligible"][:3]})
        if eligible:
            final = {"status": "ok", "recommendations": eligible[:3]}
            break
        if plan_version == REPLAN_LIMIT:
            final = {"status": "limit_reached", "recommendations": []}
    return {"scenario": sid, "conditions": cond, "steps": steps, **final,
            "replan_count": len(steps) - 1,
            "tool_calls": {k: calls[k] - before[k] for k in calls},
            "detail_cache_hits": cache_hits["get_performance_detail"] - hits_before}


def enrich(rec: dict) -> dict:
    """D1 후반부: 추천 공연의 venue_id → 시설 좌표 → 카카오 주변 식당 (입력이 앞 단계 결과로 채워지는지)."""
    calls["venue"] += 1
    v = kopis(f"prfplc/{rec['venue_id']}")
    x, y = (t(v[0], "lo"), t(v[0], "la")) if v else ("", "")
    if not (x and y):
        return {"venue_id": rec["venue_id"], "error": "NO_COORD"}
    calls["kakao"] += 1
    r = requests.get("https://dapi.kakao.com/v2/local/search/category.json",
                     params={"category_group_code": "FD6", "x": x, "y": y, "radius": 500, "sort": "distance", "size": 3},
                     headers={"Authorization": f"KakaoAK {KAKAO}"}, timeout=10)
    docs = r.json().get("documents", []) if r.ok else []
    return {"venue_id": rec["venue_id"], "x": x, "y": y,
            "places": [{"name": p["place_name"], "address": p["road_address_name"], "distance_m": int(p["distance"]),
                        "url": p["place_url"]} for p in docs]}


def next_weekday(wd: int) -> str:
    today = date.today()
    return (today + timedelta(days=(wd - today.weekday()) % 7 or 7)).isoformat()


def main() -> None:
    if not KEY or not KAKAO:
        record("D1", False, "KOPIS/KAKAO 키 없음")
        return
    jongno = {"signgucode": "11", "signgucodesub": "1111"}
    scenarios = [
        ("S1", {"date": next_weekday(5), "earliest_start": "14:00", "end_by": "18:00", "budget_max": 50000},
         {"region": jongno, "genre": "AAAA", "page": 1}),  # 토요일 대학로 연극
        ("S2", {"date": next_weekday(6), "earliest_start": "19:00", "end_by": "21:00", "budget_max": 30000},
         {"region": jongno, "genre": "GGGA", "page": 1}),  # 일요일 저녁 뮤지컬, 짧고 싼 것
        ("S3", {"date": next_weekday(2), "earliest_start": "09:00", "end_by": "11:00", "budget_max": None},
         {"region": jongno, "genre": "AAAA", "page": 1}),  # 평일 오전 11시 전 종료
    ]
    started = datetime.now()
    results = [run_scenario(*s) for s in scenarios]

    # D1: S1 enrich
    s1 = results[0]
    s1["enrich"] = [enrich(r) for r in s1["recommendations"][:2]] if s1["recommendations"] else []

    # D2-cache: S1을 같은 조건으로 한 번 더 → 상세 호출 0, 전부 캐시 재사용이어야 함
    rerun = run_scenario("S1-rerun", scenarios[0][1], dict(scenarios[0][2]))

    POOL_FILE.write_text(json.dumps(detail_cache, ensure_ascii=False, indent=1), encoding="utf-8")

    # P1: 패턴 수집
    pool = [d for d in detail_cache.values() if not d.get("error")]
    sched_fail = [d["dtguidance"] for d in pool if parse_schedule(d["dtguidance"]) is None]
    run_fail = [d["prfruntime"] for d in pool if parse_runtime(d["prfruntime"]) is None]
    price_fail = [d["pcseguidance"] for d in pool if parse_price(d["pcseguidance"]) is None]
    patterns = {
        "pool_size": len(pool),
        "schedule_unparsed": f"{len(sched_fail)}/{len(pool)}", "schedule_unparsed_samples": sched_fail[:10],
        "runtime_unparsed": f"{len(run_fail)}/{len(pool)}", "runtime_unparsed_samples": run_fail[:10],
        "price_unparsed": f"{len(price_fail)}/{len(pool)}", "price_unparsed_samples": price_fail[:10],
        "schedule_examples": sorted({d["dtguidance"] for d in pool}, key=len)[-8:],
        "price_examples": sorted({d["pcseguidance"] for d in pool}, key=len)[-5:],
    }
    lat = sorted(latencies)
    latency = {"kopis_calls": len(lat), "retries": retries["count"],
               "p50_s": round(lat[len(lat) // 2], 2) if lat else None,
               "p90_s": round(lat[int(len(lat) * 0.9)], 2) if lat else None,
               "max_s": round(lat[-1], 2) if lat else None,
               "failures": bad_bodies[:10], "failure_count": len(bad_bodies)}
    print("latency", latency)
    OUT.write_text(json.dumps({"scenarios": results, "rerun": rerun, "patterns": patterns, "latency": latency,
                               "elapsed_s": round((datetime.now() - started).total_seconds(), 1)},
                              ensure_ascii=False, indent=1), encoding="utf-8")

    for r in results + [rerun]:
        print(f"{r['scenario']}: status={r['status']} replan={r['replan_count']} "
              f"steps={[(s['strategy'], s['candidates'], s['eligible']) for s in r['steps']]} "
              f"calls={r['tool_calls']} cache_hits={r['detail_cache_hits']}")
    d1_ok = s1["status"] == "ok" and bool(s1["enrich"]) and all(e.get("places") for e in s1["enrich"])
    record("D1", d1_ok, "S1 전 단계 Tool 입력이 앞 단계 결과로 채워짐" if d1_ok else "S1 흐름 끊김 — design_trial.json 확인")
    record("D2", results[2]["status"] == "limit_reached" and rerun["tool_calls"]["get_performance_detail"] == 0,
           f"S2={results[1]['status']}(replan {results[1]['replan_count']}), S3={results[2]['status']}, "
           f"재실행 상세 호출 {rerun['tool_calls']['get_performance_detail']}회/캐시 {rerun['detail_cache_hits']}회")
    record("P1", True, f"상세 {len(pool)}건 패턴 수집: 회차 해석 실패 {patterns['schedule_unparsed']}, "
                       f"러닝타임 {patterns['runtime_unparsed']}, 가격 {patterns['price_unparsed']}")


if __name__ == "__main__":
    main()
