"""V1~V3, T2, T3: KOPIS 공연목록 → 공연상세 → 공연시설상세 실호출 검증.

실행: .venv/Scripts/python scripts/validation/check_kopis.py
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import date, timedelta

import requests

from _common import env, record, save_sample

KEY = env("KOPIS_API_KEY")
BASES = ["https://www.kopis.or.kr/openApi/restful", "http://www.kopis.or.kr/openApi/restful"]
TIMEOUT = 10
# 검증 발견: KOPIS WAF가 python-requests 기본 User-Agent를 "Request Blocked"(400)로 차단한다.
# 브라우저로 위장하지 않고, 우리 클라이언트임을 밝히는 User-Agent를 사용한다.
HEADERS = {"User-Agent": "ai-planner/0.1 (SSAFY AI core project)"}


def call(path: str, params: dict, key: str | None = KEY) -> tuple[requests.Response, str]:
    """https 우선, 실패 시 http 로 재시도. (어느 쪽이 되는지도 검증 결과로 남긴다)"""
    last_exc = None
    for base in BASES:
        try:
            r = requests.get(f"{base}/{path}", params={"service": key, **params},
                             headers=HEADERS, timeout=TIMEOUT)
            # 검증 발견: 응답 헤더에 charset이 없어 requests가 ISO-8859-1로 추정 → 한글 깨짐. 본문은 UTF-8.
            r.encoding = "utf-8"
            return r, base
        except requests.RequestException as e:
            last_exc = e
    raise last_exc  # type: ignore[misc]


def items(xml_text: str) -> list[ET.Element]:
    return ET.fromstring(xml_text).findall("db")


def text(el: ET.Element, tag: str) -> str:
    v = el.findtext(tag)
    return (v or "").strip()


def main() -> None:
    if not KEY:
        record("V1", False, "KOPIS_API_KEY 가 .env 에 없음")
        return

    today = date.today()
    stdate, eddate = today.strftime("%Y%m%d"), (today + timedelta(days=7)).strftime("%Y%m%d")

    # ---- V1: 공연목록 (서울, 공연중) ----
    r, base = call("pblprfr", {"stdate": stdate, "eddate": eddate, "cpage": 1, "rows": 20,
                                "signgucode": "11", "prfstate": "02"})
    save_sample("kopis_list.xml", r.text, KEY)
    ctype = r.headers.get("Content-Type", "")
    try:
        lst = items(r.text)
    except ET.ParseError:
        record("V1", False, f"XML 파싱 실패 (status={r.status_code}, content-type={ctype})")
        return
    record("V1", r.ok and len(lst) > 0, f"{len(lst)}건 수신", status=r.status_code,
           content_type=ctype, base_url=base, fields=[c.tag for c in lst[0]] if lst else [])
    if not lst:
        return

    # ---- V2 + T2: 공연상세 20건 → 필드 존재/빈 값 비율 ----
    stats = {"prfruntime": 0, "dtguidance": 0, "pcseguidance": 0, "mt10id": 0}
    runtime_ok = schedule_ok = price_ok = 0
    first_detail = None
    for i, p in enumerate(lst):
        pid = text(p, "mt20id")
        dr, _ = call(f"pblprfr/{pid}", {})
        if i == 0:
            save_sample("kopis_detail.xml", dr.text, KEY)
        d = items(dr.text)
        if not d:
            continue
        d = d[0]
        if first_detail is None:
            first_detail = d
        for k in stats:
            if text(d, k):
                stats[k] += 1
        if re.search(r"\d+\s*분|\d+\s*시간", text(d, "prfruntime")):
            runtime_ok += 1
        if re.search(r"\d{1,2}:\d{2}", text(d, "dtguidance")):
            schedule_ok += 1
        if re.search(r"[\d,]+\s*원|무료", text(d, "pcseguidance")):
            price_ok += 1

    n = len(lst)
    record("V2", first_detail is not None, "공연상세 수신",
           fields=[c.tag for c in first_detail] if first_detail is not None else [])
    record("T2", True, f"샘플 {n}건 필드 채움/파싱 가능 비율",
           non_empty={k: f"{v}/{n}" for k, v in stats.items()},
           parseable={"runtime": f"{runtime_ok}/{n}", "schedule_time": f"{schedule_ok}/{n}",
                      "price": f"{price_ok}/{n}"},
           examples={k: text(first_detail, k) for k in stats} if first_detail is not None else {})

    # ---- V3: 공연시설상세 (좌표) ----
    venue_id = text(first_detail, "mt10id") if first_detail is not None else ""
    if venue_id:
        fr, _ = call(f"prfplc/{venue_id}", {})
        save_sample("kopis_venue.xml", fr.text, KEY)
        f = items(fr.text)
        la, lo = (text(f[0], "la"), text(f[0], "lo")) if f else ("", "")
        record("V3", bool(la and lo), f"좌표 la={la}, lo={lo}", address=text(f[0], "adres") if f else "")
    else:
        record("V3", False, "공연상세에 mt10id 없음")

    # ---- T3: 실패 케이스 실제 응답 ----
    cases = {}
    r_bad_key, _ = call("pblprfr", {"stdate": stdate, "eddate": eddate, "cpage": 1, "rows": 5}, key="INVALID_KEY")
    save_sample("kopis_fail_bad_key.xml", r_bad_key.text)
    cases["bad_key"] = {"status": r_bad_key.status_code, "body_head": r_bad_key.text[:200]}

    r_bad_id, _ = call("pblprfr/PF000000000", {})
    save_sample("kopis_fail_bad_id.xml", r_bad_id.text, KEY)
    cases["bad_id"] = {"status": r_bad_id.status_code, "body_head": r_bad_id.text[:200]}

    r_empty, _ = call("pblprfr", {"stdate": stdate, "eddate": eddate, "cpage": 1, "rows": 5,
                                   "shprfnm": "존재하지않는공연명가나다라"})
    save_sample("kopis_fail_no_result.xml", r_empty.text, KEY)
    cases["no_result"] = {"status": r_empty.status_code, "body_head": r_empty.text[:200]}

    r_range, _ = call("pblprfr", {"stdate": stdate, "eddate": (today + timedelta(days=120)).strftime("%Y%m%d"),
                                   "cpage": 1, "rows": 5})
    save_sample("kopis_fail_long_range.xml", r_range.text, KEY)
    cases["long_range_120d"] = {"status": r_range.status_code, "body_head": r_range.text[:200]}

    record("T3-KOPIS", True, "실패 케이스 응답 수집 (실패 코드 매핑에 사용)", cases=cases)


if __name__ == "__main__":
    main()
