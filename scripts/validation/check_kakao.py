"""V4, T3: 카카오 로컬 API 실호출 검증.

좌표는 KOPIS 공연시설 샘플(check_kopis.py 결과)에서 읽고, 없으면 대학로(혜화역) 좌표를 쓴다.
실행: .venv/Scripts/python scripts/validation/check_kakao.py
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import requests

from _common import SAMPLES, env, record, save_sample

KEY = env("KAKAO_REST_API_KEY")
BASE = "https://dapi.kakao.com/v2/local/search"
DEFAULT_XY = ("127.0019", "37.5822")  # 혜화역 부근 (경도, 위도)


def venue_xy() -> tuple[str, str, str]:
    p = SAMPLES / "kopis_venue.xml"
    if p.exists():
        try:
            db = ET.fromstring(p.read_text(encoding="utf-8")).find("db")
            if db is not None and db.findtext("lo") and db.findtext("la"):
                return db.findtext("lo").strip(), db.findtext("la").strip(), "KOPIS 공연시설 좌표"
        except ET.ParseError:
            pass
    return (*DEFAULT_XY, "기본 좌표(혜화역)")


def call(kind: str, params: dict, key: str | None = KEY) -> requests.Response:
    return requests.get(f"{BASE}/{kind}.json", params=params,
                        headers={"Authorization": f"KakaoAK {key}"}, timeout=10)


def main() -> None:
    if not KEY:
        record("V4", False, "KAKAO_REST_API_KEY 가 .env 에 없음")
        return

    x, y, src = venue_xy()
    r = call("category", {"category_group_code": "FD6", "x": x, "y": y, "radius": 500, "sort": "distance", "size": 5})
    save_sample("kakao_category_fd6.json", r.text, KEY)
    docs = r.json().get("documents", []) if r.ok else []
    record("V4", r.ok and len(docs) > 0, f"식당 {len(docs)}건 ({src})", status=r.status_code,
           fields=list(docs[0].keys()) if docs else [],
           example={k: docs[0].get(k) for k in ("place_name", "road_address_name", "distance", "place_url")} if docs else {})

    cases = {}
    rb = call("category", {"category_group_code": "FD6", "x": x, "y": y, "radius": 500}, key="INVALID_KEY")
    save_sample("kakao_fail_bad_key.json", rb.text)
    cases["bad_key"] = {"status": rb.status_code, "body": rb.text[:200]}

    re_ = call("keyword", {"query": "존재하지않는장소가나다라마바사", "x": x, "y": y, "radius": 500})
    save_sample("kakao_fail_no_result.json", re_.text, KEY)
    cases["no_result"] = {"status": re_.status_code, "meta": re_.json().get("meta") if re_.ok else re_.text[:200]}

    ri = call("category", {"category_group_code": "FD6", "x": "abc", "y": y, "radius": 500})
    save_sample("kakao_fail_bad_input.json", ri.text, KEY)
    cases["bad_input"] = {"status": ri.status_code, "body": ri.text[:200]}

    record("T3-KAKAO", True, "실패 케이스 응답 수집", cases=json.loads(json.dumps(cases, ensure_ascii=False)))


if __name__ == "__main__":
    main()
