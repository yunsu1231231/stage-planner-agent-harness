"""실행 로그 저장소 — F3013 세션 단위 append, F3014 목록·상세·삭제. 수정 메서드는 의도적으로 없다."""
from __future__ import annotations

import json
import uuid
from typing import Any

from .db import Database


class LogRepository:
    def __init__(self, db: Database):
        self.db = db

    def append(self, event: dict[str, Any]) -> None:
        """받은 이벤트를 가공 없이 그대로 덧붙인다."""
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO execution_events (event_id, session_id, run_id, seq, ts, type, node, payload) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (event.get("event_id") or uuid.uuid4().hex, event["session_id"], event["run_id"], event["seq"],
                 event["ts"], event["type"], event.get("node"),
                 json.dumps(event.get("payload", {}), ensure_ascii=False, default=str)))

    def list_sessions(self) -> list[dict[str, Any]]:
        sql = """
        SELECT session_id, MIN(ts) AS first_at, MAX(ts) AS last_at,
               COUNT(DISTINCT run_id) AS run_count, COUNT(*) AS event_count,
               SUM(type = 'replan') AS replan_total, SUM(type = 'error') AS error_count,
               SUM(type = 'tool.response' AND json_extract(payload, '$.ok') = 0) AS tool_failure_count
        FROM execution_events GROUP BY session_id ORDER BY MAX(id) DESC"""
        with self.db.connect() as conn:
            return [dict(r) for r in conn.execute(sql).fetchall()]

    def get_session(self, session_id: str, run_id: str | None = None) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM execution_events WHERE session_id = ?", [session_id]
        if run_id:
            sql += " AND run_id = ?"
            args.append(run_id)
        with self.db.connect() as conn:
            rows = conn.execute(sql + " ORDER BY id", args).fetchall()
        return [{"event_id": r["event_id"], "session_id": r["session_id"], "run_id": r["run_id"], "seq": r["seq"],
                 "ts": r["ts"], "type": r["type"], "node": r["node"], "payload": json.loads(r["payload"])}
                for r in rows]

    def delete_session(self, session_id: str) -> int:
        with self.db.connect() as conn:
            return conn.execute("DELETE FROM execution_events WHERE session_id = ?", (session_id,)).rowcount
