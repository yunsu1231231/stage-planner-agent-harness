// 백엔드 API 호출 — 오류는 사용자에게 보여도 되는 문장으로만 바꾼다 (NF3002)

const stored = (() => { try { return localStorage.getItem("apiBase"); } catch { return null; } })();
export const API_BASE = stored || "http://127.0.0.1:8000";

export class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export async function api(method, path, body = null, params = null) {
  const qs = params ? "?" + new URLSearchParams(Object.entries(params).filter(([, v]) => v !== null && v !== undefined && v !== "")) : "";
  let res;
  try {
    res = await fetch(API_BASE + path + (qs === "?" ? "" : qs), {
      method,
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(0, "NETWORK", `서버(${API_BASE})에 연결할 수 없습니다. 백엔드가 실행 중인지 확인해 주세요.`);
  }
  if (res.status === 204) return null;
  let data = null;
  try { data = await res.json(); } catch { /* 본문 없음 */ }
  if (!res.ok) {
    const err = data && data.error;
    const fallback = res.status === 422 ? "입력값 형식을 확인해 주세요." : "요청을 처리하지 못했습니다.";
    throw new ApiError(res.status, (err && err.code) || `HTTP_${res.status}`, (err && err.message) || fallback);
  }
  return data;
}
