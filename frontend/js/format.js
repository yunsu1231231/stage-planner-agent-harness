// 표시용 포맷 — 순수 함수 (DOM 없음, node:test 로 검증)

export const won = (n) => {
  if (n === null || n === undefined) return "가격 확인 필요";
  if (n === 0) return "무료";
  return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ",") + "원";
};

const STATUS = {
  ok: { label: "추천 완료", level: "ok" },
  partial: { label: "일부 정보 실패", level: "warn" },
  clarify: { label: "추가 정보 필요", level: "info" },
  no_match: { label: "맞는 공연 없음", level: "warn" },
  limit_reached: { label: "재계획 상한 도달", level: "warn" },
  saved: { label: "저장 완료", level: "ok" },
  config_missing: { label: "설정 필요", level: "error" },
  error: { label: "처리 실패", level: "error" },
  chat: { label: "대화", level: "info" },
};
export const statusInfo = (s, intent = null) => {
  if (s === "ok" && intent === "fact_query") return { label: "조회 완료", level: "ok" };
  return STATUS[s] || { label: String(s), level: "info" };
};

const KEY_NAMES = { llm: "LLM_API_KEY (언어 모델)", kopis: "KOPIS_API_KEY (공연 정보)", kakao: "KAKAO_REST_API_KEY (주변 장소)" };
export const missingKeys = (config = {}) => Object.keys(KEY_NAMES).filter((k) => config[k] === false).map((k) => KEY_NAMES[k]);

// 같은 날짜에서 [start, end) 가 교차하면 겹침 — 백엔드 규칙과 동일
export const markOverlaps = (plans) => plans.map((p) => ({
  ...p,
  overlapsWith: plans
    .filter((o) => o.id !== p.id && o.date === p.date && p.start_time < o.end_time && o.start_time < p.end_time)
    .map((o) => o.id),
}));

const COND_LABELS = [
  ["date", "날짜"], ["earliest_start", "시작 이후"], ["end_by", "종료 전"], ["budget_max", "예산"],
  ["age", "나이"], ["region", "지역"], ["genre", "장르"], ["place_category", "주변 장소"],
];
const PLACE = { restaurant: "식당", cafe: "카페", parking: "주차장" };
const fmtCond = (k, v) => (k === "budget_max" ? won(v) : k === "age" ? `만 ${v}세` : k === "place_category" ? PLACE[v] || v : v);

export const conditionChips = (conditions = {}) => COND_LABELS
  .filter(([k]) => conditions[k] && conditions[k].value !== null && conditions[k].value !== undefined)
  .map(([k, label]) => ({ label, value: fmtCond(k, conditions[k].value), source: conditions[k].source }));
