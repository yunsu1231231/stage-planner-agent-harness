# 기획 검증 스크립트 (명세 2.7)

제품 코드가 아니라 **구현 전 기획 검증용** 일회성 스크립트다. 결과는 `docs/03_planning_validation.md` 에 옮겨 적는다.

## 실행

```bash
cp .env.example .env    # 키 입력
.venv/Scripts/python scripts/validation/check_llm.py     # C1, C2
.venv/Scripts/python scripts/validation/check_kopis.py   # V1~V3, T2, T3-KOPIS
.venv/Scripts/python scripts/validation/check_kakao.py   # V4, T3-KAKAO (kopis 다음에 실행)
```

## 산출물
- `docs/validation/results.json` — 항목별 PASS/FAIL 과 수치
- `docs/validation/samples/` — 실제 응답 원본 (키는 `***` 로 마스킹). 이후 테스트 fixture로 재사용한다.
