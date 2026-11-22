// L1 — F3019 실행 과정 표시 모델: 실행 순서, Tool 이력, 재계획 지점 구분, LLM 판단 이유
import { test } from "node:test";
import assert from "node:assert/strict";
import { buildTimeline } from "../js/timeline.js";

const ev = (seq, type, node, payload = {}) => ({ seq, type, node, payload, ts: `2026-11-22T18:00:${String(seq).padStart(2, "0")}.000+09:00` });

const EVENTS = [
  ev(1, "run.start", null, { message: "토요일" }),
  ev(2, "node.enter", "analyze"),
  ev(3, "llm.decision", "analyze", { decision: "plan_performance", reason: "추천 요청" }),
  ev(4, "node.exit", "analyze", { intent: "plan_performance" }),
  ev(5, "node.enter", "plan"),
  ev(6, "plan.corrected", "plan", { reason: "rule_check", added: ["get_performance_detail"], removed: [] }),
  ev(7, "plan.created", "plan", { plan_version: 0, strategy: "initial", tasks: [{ tool: "search_performances" }] }),
  ev(8, "node.exit", "plan"),
  ev(9, "tool.request", "execute", { tool: "search_performances", args: { date: "2026-11-28" }, cached: false }),
  ev(10, "tool.response", "execute", { tool: "search_performances", ok: true, duration_ms: 412, summary: "후보 3건", cached: false }),
  ev(11, "tool.request", "execute", { tool: "get_performance_detail", args: { performance_id: "PF1" }, cached: false }),
  ev(12, "tool.response", "execute", { tool: "get_performance_detail", ok: false, error_code: "UPSTREAM_ERROR", duration_ms: 90, summary: "UPSTREAM_ERROR: x" }),
  ev(13, "judge.result", "judge", { eligible: 0, excluded: 2, unjudgeable: 1 }),
  ev(14, "replan", "plan", { count: 1, strategy: "drop_genre", reason: "충족 후보 0개" }),
  ev(15, "tool.request", "execute", { tool: "search_performances", args: {}, cached: true }),
  ev(16, "tool.response", "execute", { tool: "search_performances", ok: true, duration_ms: 0, cached: true, summary: "후보 1건" }),
  ev(17, "run.end", null, { status: "ok", llm_calls: 3, duration_ms: 9000 }),
];

test("items follow execution order and pair tool request/response", () => {
  const t = buildTimeline(EVENTS);
  const tools = t.items.filter((i) => i.kind === "tool");
  assert.equal(tools.length, 3);
  assert.deepEqual(tools.map((x) => [x.tool, x.ok, x.durationMs, x.cached]), [
    ["search_performances", true, 412, false],
    ["get_performance_detail", false, 90, false],
    ["search_performances", true, 0, true],
  ]);
  assert.equal(tools[1].errorCode, "UPSTREAM_ERROR");
  const seqs = t.items.map((i) => i.seq);
  assert.deepEqual(seqs, [...seqs].sort((a, b) => a - b));
});

test("replan is a distinct marker and later items belong to the next round", () => {
  const t = buildTimeline(EVENTS);
  const marker = t.items.find((i) => i.kind === "replan");
  assert.deepEqual([marker.count, marker.strategy, marker.label], [1, "drop_genre", "장르 조건 해제"]);
  const last = t.items.filter((i) => i.kind === "tool").at(-1);
  assert.equal(last.round, 1);
  assert.equal(t.items.find((i) => i.kind === "tool").round, 0);
});

test("LLM decisions keep their reason and summary counts are computed", () => {
  const t = buildTimeline(EVENTS);
  const d = t.items.find((i) => i.kind === "decision");
  assert.equal(d.reason, "추천 요청");
  assert.ok(t.items.some((i) => i.kind === "note" && i.text.includes("get_performance_detail")));
  assert.deepEqual(t.summary, { status: "ok", llmCalls: 3, durationMs: 9000, toolCalls: 3, toolFailures: 1, replans: 1 });
});

test("unknown event types are kept, not dropped", () => {
  const t = buildTimeline([ev(1, "something.new", "x", { a: 1 })]);
  assert.equal(t.items[0].kind, "other");
});
