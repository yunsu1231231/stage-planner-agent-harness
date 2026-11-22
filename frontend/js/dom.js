// 화면 출력 헬퍼 — innerHTML 을 쓰는 유일한 파일 (tests/frontend 가드가 강제).
// html`...` 은 끼워 넣는 값을 기본으로 이스케이프한다. 이미 안전한 조각만 raw()/중첩 html 로 통과.

class SafeHtml {
  constructor(s) { this.s = s; }
  toString() { return this.s; }
}

const ENTITIES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
export const esc = (v) => String(v).replace(/[&<>"']/g, (c) => ENTITIES[c]);

const part = (v) => {
  if (v === null || v === undefined || v === false) return "";
  if (v instanceof SafeHtml) return v.s;
  if (Array.isArray(v)) return v.map(part).join("");
  return esc(v);
};

export function html(strings, ...values) {
  let out = strings[0];
  values.forEach((v, i) => { out += part(v) + strings[i + 1]; });
  return new SafeHtml(out);
}

export const raw = (s) => new SafeHtml(String(s));

// 외부 링크는 http(s)만 허용 (javascript: 등 차단)
export const safeUrl = (u) => (/^https?:\/\//i.test(String(u || "")) ? String(u) : "#");

export function render(el, content) {
  el.innerHTML = String(content);
}

export const $ = (sel, root = document) => root.querySelector(sel);
