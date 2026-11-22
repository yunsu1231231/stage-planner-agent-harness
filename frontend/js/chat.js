// 대화 화면 (F3018, F3019): 대화 · 추천 카드(저장) · 실행 과정 타임라인 · 처리 중 표시 · 키 누락/오류 안내
import { api, API_BASE, ApiError } from "./api.js";
import { $, html, render, safeUrl } from "./dom.js";
import { conditionChips, missingKeys, statusInfo, won } from "./format.js";
import { buildTimeline, renderTimeline } from "./timeline.js";

const EXAMPLES = [
  "이번 토요일 2시 이후 대학로에서 5만원 이하 연극 보고 6시 전에 끝내고 싶어. 끝나고 갈 식당도",
  "같은 날 뮤지컬로 바꿔줘",
  "1번으로 저장해줘",
  "7시 전에 끝나야 해",
  "안녕! 뭘 할 수 있어?",
];

const state = { sessionId: sessionStorage.getItem("sessionId"), busy: false, recs: new Map() };
const messagesEl = $("#messages");
const input = $("#input");

$("#api-base").textContent = `API ${API_BASE}`;
render($("#examples"), EXAMPLES.map((e) => html`<button type="button" data-example="${e}">${e}</button>`));

// ---------------------------------------------------------------- 설정 점검 (키 누락 안내)
async function checkHealth() {
  try {
    const h = await api("GET", "/api/health");
    const missing = missingKeys(h.config);
    render($("#banner"), missing.length
      ? html`<div class="banner error">설정이 필요합니다: ${missing.join(", ")} — 프로젝트 루트의 <code>.env</code> 에 키를 넣고 서버를 다시 시작하세요.</div>`
      : "");
  } catch (e) {
    render($("#banner"), html`<div class="banner error">${e.message}</div>`);
  }
}

// ---------------------------------------------------------------- 메시지
function append(node) {
  messagesEl.append(node);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return node;
}

function bubble(cls, content) {
  const div = document.createElement("div");
  div.className = `msg ${cls}`;
  render(div, content);
  return div;
}

function recCard(r, key) {
  const places = r.places || [];
  return html`<div class="card">
    <h3>${r.title}</h3>
    <div><span class="when">${r.date} ${r.start_time}~${r.end_time}</span> · ${r.runtime_min}분 · ${won(r.min_price)}</div>
    <div class="muted small">${r.venue_name || ""}${r.age_limit ? html` · ${r.age_limit}` : ""}${r.other_times && r.other_times.length ? html` · 다른 회차 ${r.other_times.join(", ")}` : ""}</div>
    <div class="criteria">판단 근거: ${r.criteria}</div>
    <div class="criteria">근거 Tool 결과: ${(r.evidence || []).join(", ")}</div>
    ${places.length ? html`<ul class="places">${places.slice(0, 3).map((p) => html`<li><a href="${safeUrl(p.url)}" target="_blank" rel="noopener">${p.name}</a> <span class="muted">${p.distance_m != null ? `${p.distance_m}m` : ""} · ${p.address || ""}</span></li>`)}</ul>` : ""}
    <div class="actions"><button class="primary small" data-save="${key}">이 계획 저장</button><span class="small" data-save-result="${key}"></span></div>
  </div>`;
}

function botContent(res) {
  const st = statusInfo(res.status);
  const chips = conditionChips(res.conditions || {});
  const recs = res.recommendations || [];
  recs.forEach((r, i) => state.recs.set(`${res.run_id}:${i}`, r));
  const excluded = [...(res.excluded || []), ...(res.unjudgeable || [])];
  return html`
    <div><span class="badge ${st.level}">${st.label}</span>${res.replan_count ? html` <span class="pill warn">재계획 ${res.replan_count}회</span>` : ""}</div>
    ${chips.length ? html`<div class="chips">${chips.map((c) => html`<span class="chip ${c.source === "memory" ? "memory" : ""}" title="${c.source === "memory" ? "이전 대화에서 유지된 조건" : "이번 요청에서 추출"}">${c.label}: ${c.value}</span>`)}</div>` : ""}
    <div class="reply">${res.reply}</div>
    ${(res.notices || []).length ? html`<ul class="notices">${res.notices.map((n) => html`<li>${n.message}</li>`)}</ul>` : ""}
    ${recs.length ? html`<div class="cards">${recs.map((r, i) => recCard(r, `${res.run_id}:${i}`))}</div>` : ""}
    ${(res.suggestions || []).length ? html`<ul class="notices">${res.suggestions.map((s) => html`<li>제안: ${s}</li>`)}</ul>` : ""}
    ${excluded.length ? html`<details class="excluded"><summary>제외·판단 불가 ${excluded.length}건 (사유 보기)</summary><ul>${excluded.map((e) => html`<li><b>${e.title || e.performance_id}</b> — ${e.reason}</li>`)}</ul></details>` : ""}`;
}

// ---------------------------------------------------------------- 전송
async function send(message) {
  if (state.busy || !message.trim()) return;
  state.busy = true;
  $("#send").disabled = true;
  input.value = "";
  append(bubble("user", html`${message}`));
  const pending = append(bubble("bot", html`<div class="pending"><span class="spinner"></span><span>요청을 분석하고 공연 정보를 조회하는 중… <b data-elapsed>0</b>초</span></div>`));
  const t0 = Date.now();
  const timer = setInterval(() => { const el = pending.querySelector("[data-elapsed]"); if (el) el.textContent = Math.floor((Date.now() - t0) / 1000); }, 500);
  render($("#timeline"), html`<div class="pending"><span class="spinner"></span>실행 중…</div>`);

  try {
    const res = await api("POST", "/api/chat", { session_id: state.sessionId, message });
    state.sessionId = res.session_id;
    sessionStorage.setItem("sessionId", res.session_id);
    render(pending, botContent(res));
    const tl = buildTimeline(res.timeline || []);
    render($("#timeline"), renderTimeline(tl));
    $("#run-meta").textContent = `${res.run_id}`;
    if (res.status === "config_missing") render($("#banner"), html`<div class="banner error">${res.reply}</div>`);
  } catch (e) {
    pending.classList.add("error");
    render(pending, html`${e instanceof ApiError ? e.message : "알 수 없는 오류가 발생했습니다."}`);
    render($("#timeline"), html`<p class="muted small">실행 과정을 받지 못했습니다.</p>`);
  } finally {
    clearInterval(timer);
    state.busy = false;
    $("#send").disabled = false;
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }
}

// ---------------------------------------------------------------- 카드에서 바로 저장 (F3015)
async function saveRec(key) {
  const r = state.recs.get(key);
  const out = document.querySelector(`[data-save-result="${key}"]`);
  const btn = document.querySelector(`[data-save="${key}"]`);
  if (!r || !out) return;
  btn.disabled = true;
  try {
    const res = await api("POST", "/api/plans", {
      performance_id: r.performance_id, title: r.title, venue_name: r.venue_name, date: r.date,
      start_time: r.start_time, end_time: r.end_time, price: r.min_price, source_session_id: state.sessionId,
    });
    const ov = res.overlaps || [];
    render(out, ov.length
      ? html`<span class="badge warn">저장됨 · 시간 겹침</span> ${ov.map((o) => `${o.title}(${o.start_time}~${o.end_time})`).join(", ")}`
      : html`<span class="badge ok">저장됨</span> <a href="plans.html">계획 관리에서 보기</a>`);
  } catch (e) {
    btn.disabled = false;
    render(out, html`<span class="badge error">${e.message}</span>`);
  }
}

// ---------------------------------------------------------------- 이벤트
$("#composer").addEventListener("submit", (ev) => { ev.preventDefault(); send(input.value); });
input.addEventListener("keydown", (ev) => { if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); send(input.value); } });
document.addEventListener("click", (ev) => {
  const t = ev.target.closest("[data-example],[data-save]");
  if (!t) return;
  if (t.dataset.example) { input.value = t.dataset.example; input.focus(); }
  if (t.dataset.save) saveRec(t.dataset.save);
});
$("#new-chat").addEventListener("click", async () => {
  if (state.sessionId) { try { await api("DELETE", `/api/chat/sessions/${state.sessionId}`); } catch { /* 무시 */ } }
  state.sessionId = null;
  sessionStorage.removeItem("sessionId");
  state.recs.clear();
  render(messagesEl, "");
  render($("#timeline"), html`<p class="muted small">새 대화를 시작했습니다.</p>`);
  $("#run-meta").textContent = "";
});

append(bubble("bot", html`안녕하세요! 날짜, 희망 시간, 지역, 예산을 알려 주시면 <b>실제 공연 중인 작품</b> 중에서 조건에 맞는 공연을 찾아 드릴게요.`));
checkHealth();
