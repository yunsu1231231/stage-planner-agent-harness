// L1 — XSS 방지: 화면에 넣는 모든 값은 기본 이스케이프 (NF3002 보조)
import { test } from "node:test";
import assert from "node:assert/strict";
import { html, raw, esc, render } from "../js/dom.js";

test("render joins arrays without commas (화면 캡처에서 발견: 예시 버튼 사이 ',')", () => {
  const el = { innerHTML: "" };
  render(el, [html`<b>a</b>`, html`<b>${"<x>"}</b>`]);
  assert.equal(el.innerHTML, "<b>a</b><b>&lt;x&gt;</b>");
  render(el, "plain");
  assert.equal(el.innerHTML, "plain");
});

test("interpolated values are escaped", () => {
  const evil = `<img src=x onerror="alert(1)">`;
  const out = String(html`<p title="${evil}">${evil}</p>`);
  assert.ok(!out.includes("<img"));
  assert.ok(out.includes("&lt;img src=x onerror=&quot;alert(1)&quot;&gt;"));
});

test("raw() and nested html are not double-escaped", () => {
  const inner = html`<b>${"<i>"}</b>`;
  assert.equal(String(html`<div>${inner}${raw("<hr>")}</div>`), "<div><b>&lt;i&gt;</b><hr></div>");
});

test("arrays are joined and null/undefined/false render empty", () => {
  assert.equal(String(html`<ul>${["a", "<b>"].map((x) => html`<li>${x}</li>`)}</ul>`), "<ul><li>a</li><li>&lt;b&gt;</li></ul>");
  assert.equal(String(html`${null}${undefined}${false}${0}`), "0");
});

test("esc handles quotes and ampersand", () => {
  assert.equal(esc(`a&b"c'd`), "a&amp;b&quot;c&#39;d");
});
