"""Tool 입력 스키마 (Pydantic). LLM에는 이 JSON Schema 가 그대로 전달된다."""
from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_DATE = r"^\d{4}-\d{2}-\d{2}$"


class SearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date: str | None = Field(None, pattern=_DATE, description="관람 날짜 YYYY-MM-DD. 생략하면 오늘")
    region: str | None = Field(None, description="지역 이름. 예: 대학로, 종로구, 강남, 홍대, 서울")
    genre: str | None = Field(None, description="장르 이름. 예: 연극, 뮤지컬, 클래식, 국악, 대중음악, 무용")
    limit: int = Field(20, ge=1, le=50, description="가져올 후보 수 (최대 50)")

    @field_validator("date")
    @classmethod
    def _real_date(cls, v: str | None) -> str | None:
        if v is not None:
            date.fromisoformat(v)          # 2026-02-30 같은 값 거부
        return v


class DetailInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    performance_id: str = Field(..., pattern=r"^PF\w+$",
                                description="search_performances 결과의 performance_id (예: PF306989)")


class NearbyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    venue_id: str | None = Field(None, pattern=r"^FC\w+$",
                                 description="get_performance_detail 결과의 venue_id (예: FC001091)")
    x: str | None = Field(None, description="경도. venue_id 가 없을 때 사용")
    y: str | None = Field(None, description="위도. venue_id 가 없을 때 사용")
    category: Literal["restaurant", "cafe", "parking"] = Field("restaurant", description="찾을 장소 종류")
    radius_m: int = Field(500, ge=1, le=2000, description="검색 반경(미터)")
    size: int = Field(5, ge=1, le=15, description="가져올 장소 수")

    @field_validator("x", "y", mode="before")
    @classmethod
    def _num_to_str(cls, v: Any) -> Any:
        return str(v) if isinstance(v, (int, float)) else v

    @model_validator(mode="after")
    def _venue_or_coords(self) -> "NearbyInput":
        if not self.venue_id and not (self.x and self.y):
            raise ValueError("venue_id 또는 x, y 좌표 중 하나는 필요합니다")
        return self
