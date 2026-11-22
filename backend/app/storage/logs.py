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
            runs = [r[0] for r in conn.execute("SELECT run_id FROM anomaly_reports WHERE session_id = ?", (session_id,))]
            conn.executemany("DELETE FROM anomaly_diagnoses WHERE run_id = ?", [(r,) for r in runs])
            conn.execute("DELETE FROM anomaly_reports WHERE session_id = ?", (session_id,))
            return conn.execute("DELETE FROM execution_events WHERE session_id = ?", (session_id,)).rowcount

    # ---------------------------------------------------------------- F3020 판정·진단 (각각 한 번 기록)
    def save_report(self, report: dict[str, Any]) -> None:
        body = {k: report.get(k) for k in ("checked", "warnings", "reason", "event_count", "final")}
        with self.db.connect() as conn:
            conn.execute("INSERT OR IGNORE INTO anomaly_reports (run_id, session_id, verdict, report, created_at) "
                         "VALUES (?, ?, ?, ?, datetime('now'))",
                         (report["run_id"], report.get("session_id"), report["verdict"],
                          json.dumps(body, ensure_ascii=False)))

    def save_diagnosis(self, run_id: str, text: str) -> None:
        with self.db.connect() as conn:
            conn.execute("INSERT OR IGNORE INTO anomaly_diagnoses (run_id, text, created_at) VALUES (?, ?, datetime('now'))",
                         (run_id, text))

    def get_reports(self, session_id: str) -> list[dict[str, Any]]:
        sql = """SELECT r.run_id, r.verdict, r.report, r.created_at, d.text AS diagnosis_text, d.created_at AS diagnosed_at
                 FROM anomaly_reports r LEFT JOIN anomaly_diagnoses d ON d.run_id = r.run_id
                 WHERE r.session_id = ? ORDER BY r.rowid"""
        with self.db.connect() as conn:
            rows = conn.execute(sql, (session_id,)).fetchall()
        out = []
        for r in rows:
            body = json.loads(r["report"])
            out.append({"run_id": r["run_id"], "verdict": r["verdict"], "created_at": r["created_at"], **body,
                        "diagnosis": ({"text": r["diagnosis_text"], "created_at": r["diagnosed_at"]}
                                      if r["diagnosis_text"] else None)})
        return out
