"""KOPIS 지역·장르 코드 매핑. 모르는 이름은 None → INVALID_INPUT (임의 추정 금지).

검증 상태 (실호출, tests/tools/test_live.py): 서울 11, 부산 26, 종로구 1111, 마포구 1144, 서초구 1165,
강남구 1168 / 연극 AAAA, 뮤지컬 GGGA, 클래식 CCCA — 응답의 area·genre 가 일치함을 확인.
그 외 코드는 KOPIS 문서/행정표준코드 기준.
"""
from __future__ import annotations

GENRES: dict[str, str] = {
    "연극": "AAAA",
    "뮤지컬": "GGGA",
    "클래식": "CCCA", "서양음악": "CCCA", "서양음악(클래식)": "CCCA",
    "국악": "CCCC", "한국음악": "CCCC", "한국음악(국악)": "CCCC",
    "대중음악": "CCCD", "콘서트": "CCCD",
    "무용": "BBBC", "무용(서양/한국무용)": "BBBC",
    "대중무용": "BBBE",
    "서커스": "EEEB", "마술": "EEEB", "서커스/마술": "EEEB",
    "복합": "EEEA",
}

SIDO: dict[str, str] = {
    "서울": "11", "부산": "26", "대구": "27", "인천": "28", "광주": "29", "대전": "30", "울산": "31",
    "세종": "36", "경기": "41", "충북": "43", "충남": "44", "전남": "46", "경북": "47", "경남": "48", "제주": "50",
}

SEOUL_GU: dict[str, str] = {
    "종로구": "1111", "중구": "1114", "용산구": "1117", "성동구": "1120", "광진구": "1121", "동대문구": "1123",
    "중랑구": "1126", "성북구": "1129", "강북구": "1130", "도봉구": "1132", "노원구": "1135", "은평구": "1138",
    "서대문구": "1141", "마포구": "1144", "양천구": "1147", "강서구": "1150", "구로구": "1153", "금천구": "1154",
    "영등포구": "1156", "동작구": "1159", "관악구": "1162", "서초구": "1165", "강남구": "1168", "송파구": "1171",
    "강동구": "1174",
}

# 생활 지명 → 구
AREA_ALIASES: dict[str, str] = {
    "대학로": "종로구", "혜화": "종로구", "동숭동": "종로구", "종로": "종로구",
    "강남": "강남구", "강남역": "강남구", "압구정": "강남구", "삼성동": "강남구",
    "홍대": "마포구", "홍대입구": "마포구", "합정": "마포구", "마포": "마포구",
    "잠실": "송파구", "송파": "송파구", "신촌": "서대문구", "여의도": "영등포구",
    "성수": "성동구", "이태원": "용산구", "한남": "용산구", "용산": "용산구",
    "명동": "중구", "충무로": "중구", "예술의전당": "서초구", "서초": "서초구",
}

_SIDO_ALIASES = {"서울시": "서울", "서울특별시": "서울", "부산시": "부산", "경기도": "경기", "제주도": "제주"}


def _norm(name: str) -> str:
    return name.replace(" ", "").strip()


def resolve_genre(name: str) -> str | None:
    return GENRES.get(_norm(name))


def resolve_region(name: str) -> dict[str, str] | None:
    """지역 이름 → KOPIS 파라미터 {signgucode[, signgucodesub]} . 모르면 None."""
    n = _norm(name)
    n = _SIDO_ALIASES.get(n, n)
    if n in SIDO:
        return {"signgucode": SIDO[n]}
    gu = AREA_ALIASES.get(n) or (n if n in SEOUL_GU else None) or (n + "구" if n + "구" in SEOUL_GU else None)
    if gu:
        return {"signgucode": "11", "signgucodesub": SEOUL_GU[gu]}
    return None
