// F3019 실행 과정 표시 — 이벤트 → 화면 모델(buildTimeline, 순수) → HTML(renderTimeline)
import { html } from "./dom.js";

export const NODE_LABEL = { analyze: "요청 분석", plan: "계획 수립", execute: "Tool 실행", judge: "제약 판단", respond: "응답 생성" };
export const STRATEGY_LABEL = { initial: "최초 계획", expand_pool: "후보 확장", drop_genre: "장르 조건 해제", widen_region: "지역 확대" };
const TOOL_LABEL = { search_performances: "공연 후보 조회", get_performance_detail: "공연 상세 조회", search_nearby_places: "주변 장소 검색" };

export const NODE_LABEL_PW = { verify: "검증 (로깅 Agent)" };
Object.assign(NODE_LABEL, NODE_LABEL_PW);

function messageText(p) {
  const b = p.body || {};
  if (p.kind === "task_list") return `작업 목록 ${(b.tasks || []).length}건`;
  if (p.kind === "work_result") return `완료 ${b.done ?? 0} · 실패 ${b.failed ?? 0} · 재시도 ${b.retried ?? 0}${(b.replan_requests || []).length ? ` · 계획 변경 요청 ${b.replan_requests.length}` : ""}`;
  if (p.kind === "verification") return `검증 ${b.verdict}${(b.warnings || []).length ? ` (${b.warnings.map((w) => w.rule).join(", ")})` : ""}`;
  return p.kind || "";
}

export function buildTimeline(events = []) {
  const items = [];
  const pending = [];
  let round = 0;
  const summary = { status: null, llmCalls: null, durationMs: null, toolCalls: 0, toolFailures: 0, replans: 0 };

  for (const e of events) {
    const p = e.payload || {};
    const base = { seq: e.seq, round, node: e.node, ts: e.ts, runId: e.run_id };
    switch (e.type) {
      case "run.start": items.push({ ...base, kind: "start", text: p.message || "" }); break;
      case "node.enter": items.push({ ...base, kind: "step", label: NODE_LABEL[e.node] || e.node, role: p.role || null }); break;
      case "agent.message":
        items.push({ ...base, kind: "message", from: p.from, to: p.to, msgKind: p.kind, text: messageText(p) }); break;
      case "worker.decision":
        items.push({ ...base, kind: "worker", tool: p.tool, code: p.code, action: p.action, byLlm: !!p.llm,
          reason: p.reason || "", rejected: p.rejected || null,
          patchText: Object.entries(p.patch || {}).map(([k, v]) => `${k}=${v}`).join(", ") });
        break;
      case "verify.result":
        items.push({ ...base, kind: "verify", verdict: p.verdict, rules: (p.warnings || []).map((w) => w.rule), reason: p.reason || "" });
        break;
      case "node.exit": {
        const step = [...items].reverse().find((i) => i.kind === "step" && i.node === e.node && !i.exit);
        if (step) step.exit = p;
        break;
      }
      case "llm.decision":
        items.push({ ...base, kind: "decision", decision: p.decision, reason: p.reason || "" }); break;
      case "plan.created":
        items.push({ ...base, kind: "plan", version: p.plan_version, strategy: p.strategy,
          tools: (p.tasks || []).map((t) => t.tool) }); break;
      case "plan.corrected":
        items.push({ ...base, kind: "note",
          text: `계획 보정(${p.reason}): 추가 ${(p.added || []).join(", ") || "-"} / 제외 ${(p.removed || []).join(", ") || "-"}` });
        break;
      case "tool.request": {
        const item = { ...base, kind: "tool", tool: p.tool, label: TOOL_LABEL[p.tool] || p.tool, args: p.args || {},
          cached: !!p.cached, ok: null, durationMs: null, errorCode: null, summary: "" };
        items.push(item);
        pending.push(item);
        summary.toolCalls += 1;
        break;
      }
      case "tool.response": {
        const idx = pending.findIndex((i) => i.tool === p.tool);
        const item = idx >= 0 ? pending.splice(idx, 1)[0] : null;
        if (item) Object.assign(item, { ok: !!p.ok, durationMs: p.duration_ms ?? null, cached: !!p.cached,
          errorCode: p.error_code || null, summary: p.summary || "" });
        if (p.ok === false) summary.toolFailures += 1;
        break;
      }
      case "judge.result":
        items.push({ ...base, kind: "judge", eligible: p.eligible, excluded: p.excluded, unjudgeable: p.unjudgeable }); break;
      case "replan":
        round = p.count;
        summary.replans += 1;
        items.push({ ...base, round, kind: "replan", count: p.count, strategy: p.strategy,
          label: STRATEGY_LABEL[p.strategy] || p.strategy, reason: p.reason || "" });
        break;
      case "error": items.push({ ...base, kind: "error", code: p.code }); break;
      case "run.end":
        Object.assign(summary, { status: p.status, llmCalls: p.llm_calls ?? null, durationMs: p.duration_ms ?? null });
        items.push({ ...base, kind: "end", status: p.status });
        break;
      default: items.push({ ...base, kind: "other", type: e.type, payload: p });
    }
  }
  return { items, summary };
}

const sec = (ms) => (ms === null || ms === undefined ? "" : ms >= 1000 ? `${(ms / 1000).toFixed(1)}초` : `${ms}ms`);
const argText = (a) => Object.entries(a).map(([k, v]) => `${k}=${v}`).join(", ");

export function renderTimeline({ items, summary }) {
  const rows = items.map((i) => {
    switch (i.kind) {
      case "start": return html`<li class="tl tl-start">요청 시작 <span class="muted">${i.text}</span></li>`;
      case "message": return html`<li class="tl tl-message">✉ <b>${i.from} → ${i.to}</b> <span class="muted">${i.text}</span></li>`;
      case "worker": return html`<li class="tl tl-worker ${i.byLlm ? "llm" : ""}">Worker 판단 <span class="badge ${i.byLlm ? "info" : "ok"}">${i.byLlm ? "LLM" : "규칙"}</span>
          <b>${i.action}</b> <span class="muted">${i.tool} ${i.code}${i.patchText ? ` → ${i.patchText}` : ""}${i.rejected ? ` (거부: ${i.rejected})` : ""}</span><div class="small muted">${i.reason}</div></li>`;
      case "verify": return html`<li class="tl tl-verify"><span class="badge ${i.verdict === "anomaly" ? "error" : i.verdict === "normal" ? "ok" : "info"}">검증 ${i.verdict}</span>${i.rules.length ? html` <span class="muted">${i.rules.join(", ")}</span>` : ""}${i.reason ? html` <span class="muted small">${i.reason}</span>` : ""}</li>`;
      case "step": return html`<li class="tl tl-step">${i.role ? html`<span class="pill">${i.role}</span> ` : ""}<b>${i.label}</b>${i.exit && i.exit.intent ? html` <span class="pill">${i.exit.intent}</span>` : ""}${i.exit && i.exit.stop_reason ? html` <span class="pill warn">${i.exit.stop_reason}</span>` : ""}</li>`;
      case "decision": return html`<li class="tl tl-decision">LLM 판단 <b>${Array.isArray(i.decision) ? i.decision.join(" → ") : i.decision}</b><div class="muted">${i.reason}</div></li>`;
      case "plan": return html`<li class="tl tl-plan">작업 목록 v${i.version} (${STRATEGY_LABEL[i.strategy] || i.strategy}): ${i.tools.join(" → ")}</li>`;
      case "note": return html`<li class="tl tl-note">${i.text}</li>`;
      case "tool": return html`<li class="tl tl-tool ${i.ok === false ? "fail" : ""}">
          <span class="badge ${i.ok === false ? "error" : i.cached ? "info" : "ok"}">${i.ok === false ? i.errorCode : i.cached ? "캐시" : "성공"}</span>
          ${i.label} <span class="muted">${argText(i.args)}</span> <span class="dur">${sec(i.durationMs)}</span>
          <div class="muted small">${i.summary}</div></li>`;
      case "judge": return html`<li class="tl tl-judge">판단 결과: 충족 <b>${i.eligible}</b> · 제외 ${i.excluded} · 판단 불가 ${i.unjudgeable}</li>`;
      case "replan": return html`<li class="tl tl-replan">↻ 재계획 #${i.count} — ${i.label}<div class="small">${i.reason}</div></li>`;
      case "error": return html`<li class="tl tl-error">오류 ${i.code}</li>`;
      case "end": return html`<li class="tl tl-end">완료 (${i.status})</li>`;
      default: return html`<li class="tl tl-other muted">${i.type}</li>`;
    }
  });
  const s = summary;
  return html`<div class="tl-summary">
      <span>Tool ${s.toolCalls}회${s.toolFailures ? html` · <b class="warn-text">실패 ${s.toolFailures}</b>` : ""}</span>
      <span>재계획 ${s.replans}회</span>${s.llmCalls !== null ? html`<span>LLM ${s.llmCalls}회</span>` : ""}
      ${s.durationMs !== null ? html`<span>${sec(s.durationMs)}</span>` : ""}</div>
    <ol class="timeline">${rows}</ol>`;
}
