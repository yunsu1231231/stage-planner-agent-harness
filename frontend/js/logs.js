// 실행 로그 화면 (F3014, F3019): 세션 목록 → 실행(run)별 타임라인 + 원본 이벤트 · 삭제 (수정 없음)
import { api, API_BASE } from "./api.js";
import { $, html, render } from "./dom.js";
import { buildTimeline, renderTimeline } from "./timeline.js";

const state = { sessions: [], selected: null, events: [] };
$("#api-base").textContent = `API ${API_BASE}`;

const when = (ts) => (ts || "").replace("T", " ").slice(0, 19);

async function loadSessions() {
  try {
    state.sessions = (await api("GET", "/api/logs")).sessions;
    drawSessions();
  } catch (e) {
    render($("#banner"), html`<div class="banner error">${e.message}</div>`);
  }
}

function drawSessions() {
  render($("#sessions"), state.sessions.length
    ? html`<table><thead><tr><th>세션</th><th>마지막 실행</th><th>실행</th><th>이벤트</th><th>재계획</th><th>오류·실패</th></tr></thead><tbody>
        ${state.sessions.map((s) => html`<tr class="${s.session_id === state.selected ? "selected" : ""}">
          <td><a href="#" data-open="${s.session_id}">${s.session_id}</a></td><td>${when(s.last_at)}</td>
          <td>${s.run_count}</td><td>${s.event_count}</td>
          <td>${s.replan_total ? html`<span class="badge warn">${s.replan_total}</span>` : 0}</td>
          <td>${s.error_count + s.tool_failure_count ? html`<span class="badge error">${s.error_count} · ${s.tool_failure_count}</span>` : 0}</td></tr>`)}
      </tbody></table>`
    : html`<div class="panel empty">저장된 실행 로그가 없습니다.</div>`);
}

async function open(sessionId) {
  state.selected = sessionId;
  drawSessions();
  let reports = {};
  try {
    state.events = (await api("GET", `/api/logs/${sessionId}`)).events;
    const r = await api("GET", `/api/logs/${sessionId}/anomalies`);
    reports = Object.fromEntries(r.reports.map((x) => [x.run_id, x]));
  } catch (e) {
    render($("#detail"), html`<div class="banner error">${e.message}</div>`);
    return;
  }
  const runs = [...new Set(state.events.map((e) => e.run_id))];
  $("#detail-title").textContent = `세션 ${sessionId}`;
  render($("#detail"), html`
    <div class="toolbar"><span class="muted small">실행 ${runs.length}회 · 이벤트 ${state.events.length}개 (발생 순서)</span>
      <button class="danger" data-delete="${sessionId}">이 세션 로그 삭제</button></div>
    ${runs.map((runId, i) => {
      const evs = state.events.filter((e) => e.run_id === runId);
      return html`<div class="run-divider">실행 ${i + 1} · ${runId} · ${when(evs[0] && evs[0].ts)}</div>
        ${verdictBox(reports[runId])}
        ${renderTimeline(buildTimeline(evs))}
        <details><summary class="small muted">원본 이벤트 ${evs.length}개 보기</summary>
          <table><thead><tr><th>seq</th><th>type</th><th>node</th><th>payload</th></tr></thead><tbody>
          ${evs.map((e) => html`<tr><td>${e.seq}</td><td>${e.type}</td><td>${e.node || ""}</td><td><pre class="payload">${JSON.stringify(e.payload, null, 1)}</pre></td></tr>`)}
          </tbody></table></details>`;
    })}`);
}

// F3020: 규칙 판정(정상·이상·판정 불가)과 LLM 진단을 구분해 표시
const VERDICT = { normal: ["ok", "이상 없음"], anomaly: ["error", "이상 징후"], undeterminable: ["info", "판정 불가"] };
function verdictBox(r) {
  if (!r) return html`<div class="small muted">이상 징후 판정 없음 (실행이 끝나지 않았거나 판정 전)</div>`;
  const [level, label] = VERDICT[r.verdict] || ["info", r.verdict];
  return html`<div class="banner ${level === "ok" ? "ok" : level === "error" ? "error" : "info"} small">
    <b>규칙 판정: ${label}</b> · 점검 ${Object.entries(r.checked || {}).map(([k, v]) => `${k}=${v}`).join(", ")}
    ${r.reason ? html`<div>${r.reason}</div>` : ""}
    ${(r.warnings || []).length ? html`<ul>${r.warnings.map((w) => html`<li>${w.rule}: ${w.detail} (근거 seq ${w.evidence_seqs.join(", ")})</li>`)}</ul>` : ""}
    ${r.diagnosis ? html`<div><b>원인 진단 (LLM, 판정과 별도)</b>: ${r.diagnosis.text}</div>` : ""}
  </div>`;
}

async function remove(sessionId) {
  if (!window.confirm(`세션 ${sessionId} 의 실행 로그를 삭제할까요?`)) return;
  try {
    await api("DELETE", `/api/logs/${sessionId}`);
    state.selected = null;
    $("#detail-title").textContent = "세션을 선택하세요";
    render($("#detail"), "");
    await loadSessions();
  } catch (e) {
    render($("#banner"), html`<div class="banner error">${e.message}</div>`);
  }
}

document.addEventListener("click", (ev) => {
  const o = ev.target.closest("[data-open]");
  if (o) { ev.preventDefault(); open(o.dataset.open); }
  const d = ev.target.closest("[data-delete]");
  if (d) remove(d.dataset.delete);
});
$("#reload").addEventListener("click", loadSessions);
loadSessions();
