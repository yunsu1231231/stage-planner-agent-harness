// L1 — 표시용 포맷·상태 안내·계획 겹침 표시
import { test } from "node:test";
import assert from "node:assert/strict";
import { won, statusInfo, missingKeys, markOverlaps, conditionChips } from "../js/format.js";

test("won formats price and handles null", () => {
  assert.equal(won(40000), "40,000원");
  assert.equal(won(0), "무료");
  assert.equal(won(null), "가격 확인 필요");
});

test("status info gives a level for every API status", () => {
  for (const s of ["ok", "partial", "clarify", "no_match", "limit_reached", "saved", "config_missing", "error", "chat"]) {
    const info = statusInfo(s);
    assert.ok(info.label && ["ok", "info", "warn", "error"].includes(info.level), s);
  }
  assert.equal(statusInfo("config_missing").level, "error");
  assert.equal(statusInfo("ok", "fact_query").label, "조회 완료");      // 화면 캡처에서 발견: 사실 조회인데 '추천 완료'
  assert.equal(statusInfo("unknown-status").level, "info");
});

test("missing keys are listed by human name only", () => {
  assert.deepEqual(missingKeys({ llm: true, kopis: false, kakao: false }), ["KOPIS_API_KEY (공연 정보)", "KAKAO_REST_API_KEY (주변 장소)"]);
  assert.deepEqual(missingKeys({ llm: true, kopis: true, kakao: true }), []);
});

test("markOverlaps flags same-day half-open interval overlaps", () => {
  const plans = [
    { id: 1, date: "2026-11-28", start_time: "15:00", end_time: "16:40" },
    { id: 2, date: "2026-11-28", start_time: "16:00", end_time: "17:00" },
    { id: 3, date: "2026-11-28", start_time: "17:00", end_time: "18:00" },
    { id: 4, date: "2026-11-29", start_time: "15:00", end_time: "16:00" },
  ];
  const marked = markOverlaps(plans);
  assert.deepEqual(marked.map((p) => p.overlapsWith), [[2], [1], [], []]);
});

test("condition chips keep source and skip empty values", () => {
  const chips = conditionChips({ date: { value: "2026-11-28", source: "user" }, genre: { value: "연극", source: "memory" }, age: null });
  assert.deepEqual(chips, [
    { label: "날짜", value: "2026-11-28", source: "user" },
    { label: "장르", value: "연극", source: "memory" },
  ]);
});
