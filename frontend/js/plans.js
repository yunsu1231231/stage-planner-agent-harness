// 계획 관리 화면 (F3015, F3016): 목록·상세 · 겹침 표시 · 인라인 수정 · 삭제 → 결과 즉시 반영
import { api, API_BASE } from "./api.js";
import { $, html, render } from "./dom.js";
import { markOverlaps, won } from "./format.js";

const state = { plans: [], editing: null };
$("#api-base").textContent = `API ${API_BASE}`;

function flash(level, message) {
  render($("#banner"), html`<div class="banner ${level}">${message}</div>`);
}

async function load() {
  try {
    const res = await api("GET", "/api/plans", null, { date: $("#filter-date").value || null });
    state.plans = markOverlaps(res.plans);
    draw();
  } catch (e) {
    flash("error", e.message);
  }
}

function row(p) {
  if (state.editing === p.id) {
    return html`<tr class="selected" data-id="${p.id}">
      <td><input type="date" name="date" value="${p.date}"></td>
      <td><input type="time" name="start_time" value="${p.start_time}"> ~ <input type="time" name="end_time" value="${p.end_time}"></td>
      <td><input name="title" value="${p.title}"></td>
      <td>${p.venue_name || ""}</td><td>${won(p.price)}</td>
      <td><input name="memo" value="${p.memo || ""}" placeholder="메모"></td>
      <td><div class="row-actions"><button class="primary" data-act="save" data-id="${p.id}">저장</button><button data-act="cancel">취소</button></div></td>
    </tr>`;
  }
  const overlapNames = p.overlapsWith.map((id) => state.plans.find((x) => x.id === id)?.title).filter(Boolean);
  return html`<tr class="${p.overlapsWith.length ? "overlap" : ""}" data-id="${p.id}">
    <td>${p.date}</td>
    <td>${p.start_time} ~ ${p.end_time}${overlapNames.length ? html`<div><span class="badge warn" title="${overlapNames.join(", ")}">겹침 ${overlapNames.length}</span></div>` : ""}</td>
    <td><b>${p.title}</b><div class="muted small">생성 ${p.created_at.replace("T", " ").slice(0, 16)}${p.updated_at !== p.created_at ? html` · 수정 ${p.updated_at.replace("T", " ").slice(0, 16)}` : ""}</div></td>
    <td>${p.venue_name || ""}</td><td>${won(p.price)}</td><td>${p.memo || ""}</td>
    <td><div class="row-actions"><button data-act="edit" data-id="${p.id}">수정</button><button class="danger" data-act="delete" data-id="${p.id}">삭제</button></div></td>
  </tr>`;
}

function draw() {
  $("#count").textContent = `${state.plans.length}건`;
  render($("#plans"), state.plans.length
    ? html`<table><thead><tr><th>날짜</th><th>시간</th><th>공연</th><th>공연장</th><th>가격</th><th>메모</th><th></th></tr></thead>
        <tbody>${state.plans.map(row)}</tbody></table>`
    : html`<div class="panel empty">저장된 계획이 없습니다. <a href="index.html">대화</a>에서 추천을 받아 저장해 보세요.</div>`);
}

async function save(id) {
  const tr = document.querySelector(`tr[data-id="${id}"]`);
  const val = (n) => tr.querySelector(`[name="${n}"]`).value;
  const body = { date: val("date"), start_time: val("start_time"), end_time: val("end_time"), title: val("title"), memo: val("memo") || null };
  try {
    const res = await api("PATCH", `/api/plans/${id}`, body);
    state.editing = null;
    await load();
    const ov = res.overlaps || [];
    flash(ov.length ? "warn" : "ok", ov.length
      ? `수정했습니다. 같은 날 시간이 겹치는 계획: ${ov.map((o) => `${o.title}(${o.start_time}~${o.end_time})`).join(", ")}`
      : "수정했습니다.");
  } catch (e) {
    flash("error", e.message);
  }
}

async function remove(id) {
  const p = state.plans.find((x) => x.id === id);
  if (!window.confirm(`'${p ? p.title : id}' 계획을 삭제할까요?`)) return;
  try {
    await api("DELETE", `/api/plans/${id}`);
    await load();
    flash("ok", "삭제했습니다.");
  } catch (e) {
    flash("error", e.message);
  }
}

document.addEventListener("click", (ev) => {
  const b = ev.target.closest("[data-act]");
  if (!b) return;
  const id = Number(b.dataset.id);
  if (b.dataset.act === "edit") { state.editing = id; draw(); }
  if (b.dataset.act === "cancel") { state.editing = null; draw(); }
  if (b.dataset.act === "save") save(id);
  if (b.dataset.act === "delete") remove(id);
});
$("#filter-date").addEventListener("change", load);
$("#clear-filter").addEventListener("click", () => { $("#filter-date").value = ""; load(); });
$("#reload").addEventListener("click", load);
load();
