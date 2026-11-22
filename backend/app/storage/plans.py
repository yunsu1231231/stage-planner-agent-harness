"""계획 저장소 — F3015 저장·조회(같은 날 시간 겹침 알림), F3016 수정·삭제."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .db import Database

FIELDS = ("performance_id", "title", "venue_name", "date", "start_time", "end_time", "price", "memo",
          "source_session_id")
EDITABLE = ("title", "venue_name", "date", "start_time", "end_time", "price", "memo")


def _now() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds")


class PlanRepository:
    def __init__(self, db: Database):
        self.db = db

    def _overlaps(self, conn, plan: dict[str, Any]) -> list[dict[str, Any]]:
        """같은 날짜에서 [start, end) 구간이 교차하는 다른 계획 (끝나는 순간 시작은 겹침 아님)."""
        rows = conn.execute(
            "SELECT * FROM plans WHERE date = ? AND start_time < ? AND ? < end_time AND id != ? ORDER BY start_time",
            (plan["date"], plan["end_time"], plan["start_time"], plan.get("id") or -1)).fetchall()
        return [dict(r) for r in rows]

    def create(self, plan: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        now = _now()
        values = [plan.get(f) for f in FIELDS]
        with self.db.connect() as conn:
            cur = conn.execute(f"INSERT INTO plans ({', '.join(FIELDS)}, created_at, updated_at) "
                               f"VALUES ({', '.join('?' * len(FIELDS))}, ?, ?)", (*values, now, now))
            saved = dict(conn.execute("SELECT * FROM plans WHERE id = ?", (cur.lastrowid,)).fetchone())
            return saved, self._overlaps(conn, saved)      # 겹쳐도 저장은 막지 않는다

    def get(self, plan_id: int) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone()
            return dict(row) if row else None

    def list(self, date: str | None = None) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM plans", ()
        if date:
            sql, args = sql + " WHERE date = ?", (date,)
        with self.db.connect() as conn:
            return [dict(r) for r in conn.execute(sql + " ORDER BY date, start_time, id", args).fetchall()]

    def update(self, plan_id: int, changes: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
        changes = {k: v for k, v in changes.items() if k in EDITABLE}
        with self.db.connect() as conn:
            if conn.execute("SELECT 1 FROM plans WHERE id = ?", (plan_id,)).fetchone() is None:
                return None
            if changes:
                sets = ", ".join(f"{k} = ?" for k in changes)
                conn.execute(f"UPDATE plans SET {sets}, updated_at = ? WHERE id = ?", (*changes.values(), _now(), plan_id))
            saved = dict(conn.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone())
            return saved, self._overlaps(conn, saved)

    def delete(self, plan_id: int) -> bool:
        with self.db.connect() as conn:
            return conn.execute("DELETE FROM plans WHERE id = ?", (plan_id,)).rowcount > 0
