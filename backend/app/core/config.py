"""환경 설정 — .env 에서만 읽는다 (NF3001). 키 값은 밖으로 내보내지 않고, 설정 여부만 노출한다."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class Settings:
    llm_api_key: str | None
    llm_base_url: str | None
    llm_model: str
    kopis_api_key: str | None
    kakao_api_key: str | None

    @classmethod
    def from_env(cls, env_file: Path | None = ROOT / ".env") -> "Settings":
        if env_file is not None and env_file.exists():
            load_dotenv(env_file, override=False)

        def get(name: str) -> str | None:
            v = os.getenv(name, "").strip()
            return v or None
        return cls(llm_api_key=get("LLM_API_KEY"), llm_base_url=get("LLM_BASE_URL"),
                   llm_model=get("LLM_MODEL") or "gpt-4.1-mini",
                   kopis_api_key=get("KOPIS_API_KEY"), kakao_api_key=get("KAKAO_REST_API_KEY"))

    def flags(self) -> dict[str, bool]:
        """화면용: 키가 설정되었는지 여부만 (값은 절대 포함하지 않음, NF3002)."""
        return {"llm": bool(self.llm_api_key), "kopis": bool(self.kopis_api_key), "kakao": bool(self.kakao_api_key)}
