"""F3008 제약 적합성 판단 — 순수 함수, LLM 없음 (docs/04 4.4).

종료 = 회차 시작 + 러닝타임. 시작 ≥ 희망 시각, 종료 ≤ 제한 시각, 최저가 ≤ 예산, 관람 연령.
외부 API로 확인할 수 없는 값(회차·가격)은 지어내지 않고 '판단 불가' + 역산 기준을 제시한다.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

WEEKDAYS = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]


def hm(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def fmt(minutes: int) -> str:
    minutes = max(minutes, 0)
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def won(n: int) -> str:
    return f"{n:,}원"


def weekday_ko(d: str) -> str:
    return WEEKDAYS[date.fromisoformat(d).weekday()]


def parse_age(raw: str | None) -> int | None:
    s = raw or ""
    if "전체" in s:
        return 0
    if m := re.search(r"(\d+)\s*개월", s):
        return int(m.group(1)) // 12
    if m := re.search(r"(\d+)\s*세", s):
        return int(m.group(1))
    return None


def _base(pid: str, d: dict[str, Any]) -> dict[str, Any]:
    return {"performance_id": pid, "title": d.get("title"), "venue_id": d.get("venue_id"),
            "venue_name": d.get("venue_name")}


def evaluate(pid: str, detail_result: dict[str, Any], cond: dict[str, Any]) -> dict[str, Any]:
    """detail_result: get_performance_detail 의 ToolResult(dict). → eligible / excluded / unjudgeable"""
    if not detail_result.get("ok"):
        err = detail_result.get("error") or {}
        partial = err.get("partial") or {}
        code = err.get("code", "UPSTREAM_ERROR")
        reason = ("러닝타임 정보가 없어 시간 조건을 판단하지 않았습니다." if code == "NO_RUNTIME"
                  else "상세 정보를 가져오지 못해 판단하지 않았습니다.")
        return {"performance_id": pid, "title": partial.get("title"), "venue_name": partial.get("venue_name"),
                "result": "unjudgeable", "reason_code": code, "reason": reason}

    d = detail_result["data"]
    base = _base(pid, d)
    runtime = d["runtime_min"]
    target = cond.get("date")
    earliest, end_by, budget, age = (cond.get("earliest_start"), cond.get("end_by"),
                                     cond.get("budget_max"), cond.get("age"))

    def excluded(code: str, reason: str) -> dict[str, Any]:
        return {**base, "result": "excluded", "reason_code": code, "reason": reason}

    if target and d.get("start_date") and d.get("end_date") and not (d["start_date"] <= target <= d["end_date"]):
        return excluded("NOT_ON_DATE", f"공연 기간({d['start_date']}~{d['end_date']})에 {target}이 없습니다.")

    limit_age = parse_age(d.get("age_limit"))
    if age is not None and limit_age is not None and age < limit_age:
        return excluded("AGE_LIMIT", f"관람 연령 {d.get('age_limit')} — {age}세는 관람할 수 없습니다.")

    if d.get("schedule") is None:
        latest = fmt(hm(end_by) - runtime) if end_by else None
        reason = (f"회차 시각 정보가 없어 판단하지 않았습니다. {end_by}까지 끝나려면 늦어도 {latest}에 시작하는 회차여야 합니다."
                  if latest else "회차 시각 정보가 없어 판단하지 않았습니다.")
        return {**base, "result": "unjudgeable", "reason_code": "NO_SCHEDULE", "reason": reason,
                "latest_start": latest, "runtime_min": runtime}

    day = weekday_ko(target) if target else None
    times = d["schedule"].get(day, []) if day else sorted({t for ts in d["schedule"].values() for t in ts})
    if not times:
        return excluded("NO_SHOW_ON_DAY", f"{day}에는 회차가 없습니다 ({d.get('schedule_raw')}).")

    price = d.get("min_price")
    if budget is not None:
        if price is None:
            return {**base, "result": "unjudgeable", "reason_code": "NO_PRICE",
                    "reason": "가격 정보가 없어 예산 조건을 판단하지 않았습니다."}
        if price > budget:
            return excluded("OVER_BUDGET", f"최저가 {won(price)} > 예산 {won(budget)}")

    reasons, ok_times = [], []
    for st in times:
        s, e = hm(st), hm(st) + runtime
        if earliest and s < hm(earliest):
            reasons.append(f"{st} 시작 < 희망 {earliest}")
        elif end_by and e > hm(end_by):
            reasons.append(f"{st} 시작 + {runtime}분 = {fmt(e)} 종료 > 제한 {end_by}")
        else:
            ok_times.append(st)
    if not ok_times:
        return excluded("TIME_MISMATCH", "; ".join(reasons))

    st = ok_times[0]
    et = fmt(hm(st) + runtime)
    parts = [f"{st} 시작 + {runtime}분 = {et} 종료"]
    if end_by:
        parts[0] += f" ≤ {end_by}"
    if earliest:
        parts.append(f"시작 {st} ≥ 희망 {earliest}")
    if budget is not None:
        parts.append(f"최저가 {won(price)} ≤ 예산 {won(budget)}")
    return {**base, "result": "eligible", "date": target, "start_time": st, "end_time": et, "runtime_min": runtime,
            "min_price": price, "age_limit": d.get("age_limit"), "other_times": ok_times[1:],
            "criteria": ", ".join(parts), "evidence": [f"get_performance_detail({pid})"]}


def suggest_adjustments(details: list[dict[str, Any]], cond: dict[str, Any]) -> list[str]:
    """충족 후보가 없을 때 '가장 가까운' 완화안 — 종료 제한, 예산 (확인된 값만으로 계산)."""
    target, earliest, end_by, budget = cond.get("date"), cond.get("earliest_start"), cond.get("end_by"), cond.get("budget_max")
    day = weekday_ko(target) if target else None
    best_end: tuple[int, str] | None = None
    best_price: tuple[int, str] | None = None
    for d in details:
        if not d or d.get("schedule") is None or not d.get("runtime_min"):
            continue
        if target and d.get("start_date") and not (d["start_date"] <= target <= d.get("end_date", target)):
            continue
        times = d["schedule"].get(day, []) if day else []
        starts = [hm(t) for t in times if not earliest or hm(t) >= hm(earliest)]
        if not starts:
            continue
        end = min(starts) + d["runtime_min"]
        price_ok = budget is None or (d.get("min_price") is not None and d["min_price"] <= budget)
        time_ok = not end_by or end <= hm(end_by)
        if end_by and not time_ok and price_ok and (best_end is None or end < best_end[0]):
            best_end = (end, d.get("title") or "")
        if budget is not None and time_ok and d.get("min_price") is not None and d["min_price"] > budget:
            if best_price is None or d["min_price"] < best_price[0]:
                best_price = (d["min_price"], d.get("title") or "")
    tips = []
    if best_end:
        tips.append(f"종료 제한을 {fmt(best_end[0])}로 늦추면 '{best_end[1]}'을(를) 볼 수 있습니다.")
    if best_price:
        tips.append(f"예산을 {won(best_price[0])}으로 올리면 '{best_price[1]}'을(를) 볼 수 있습니다.")
    return tips
