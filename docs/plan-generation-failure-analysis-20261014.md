# 신규 일정 생성·Preview 반복 실패 구조 분석 (2026-10-14)

범위: `backend/app/services/external/ai/exaone_plan_provider.py`, `plan_generation_service.py`, `plan_regeneration_preview_service.py`, `plan_travel_time.py`.
코드는 수정하지 않았고, EXAONE·DB·프로세스도 건드리지 않았습니다. 표기는 **[코드]** 실제 코드로 확인, **[로그]** 사용자 제공 로그·기존 세션 로그, **[추론]** 근거 기반 판단입니다.

---

## 1. 현재 구조 — 호출 흐름과 위치

### 신규 생성 `POST /api/v1/trips/{id}/plans/generate` → `PlanGenerationService._generate`

| 단계 | 함수 | 실패 시 |
|---|---|---|
| 후보 수집 | `_input` → `_candidate_places` (DB → Kakao → 관광지·식당 backfill → `_balanced_candidate_pool`, 최대 15곳) | 404/422 |
| EXAONE 요청 | `ExaonePlanGenerationProvider._generate` (temperature 0, JSON format schema, **최대 2회**) | 504/502 |
| 응답 파싱·정규화 | `_parse`: 날짜·순서·ID·유형·제목·시간·중복·겹침 검사. 제목/유형은 후보 기준으로 교정, 중복 ID는 `_repair_duplicates`로 교체 | **항목 하나만 틀려도 응답 전체 거부** → 재시도 → `EXAONE_INVALID_RESPONSE` 502 |
| 날짜·식사 보정 | `_normalize_draft_dates`, `_prepare_draft` (`_repair_meal_slots`, `_repair_missing_meals`, `_recover_lunch_from_rest`, 관광지 보충) | 복구형 |
| 동선·휴식·먼 식사 | `_optimize_routes`, `_attach_rest_cafes`, `_replace_far_meals` | 복구형 |
| 초안 구조 검증 | `_validate_draft` | 502 |
| 이동시간 보정 | `_adjust_route_timing(repair=True)` → `shift_day_for_travel` / `_repair_route_day` (순서 교체 → 단축 → 식당 교체 → 선택 장소 제외) | 422 `ROUTE_TIME_CONFLICT` |
| 영업시간 | `_adjust_opening_hours_timing`, `_validate_temporal_draft` | 422 |
| 경로 재검증 | `_validate_route_timing`, `_validate_activity_diversity` | 422 |
| 식사 완결성 | `_require_complete_meal_schedule` | 이제 WARNING만 |
| 저장·최종 검증 | `PlanValidationService.validate` (CRITICAL이면 502) | 502 |

### Preview `POST /plans/{id}/regeneration-previews` → `PlanRegenerationPreviewService.create`

`_input` → `regenerate_preview_plan` (같은 `_generate`, `allow_overlap_repair=True`, 프롬프트 + `REGENERATION_PROMPT`) → `_normalize_draft_dates` → `_prepare_draft(…)` (**preferences 미전달**) → `_validate_draft` → `_adjust_route_timing(repair=True)` → `_validate_no_time_overlap` → 영업시간·경로·다양성·Anchor 검증 → `_validate_feedback_goal` (미달 시 EXAONE 재호출, 최대 2회) → `previews.create`.

**[코드]** Preview가 쓰지 않는 단계: `_optimize_routes`, `_attach_rest_cafes`, `_replace_far_meals`, 영업시간 보정, 식사 완결성 경고. 한 요청에서 EXAONE은 최대 **4회**(스키마 재시도 2 × 피드백 재시도 2)까지 호출될 수 있습니다.

---

## 2. 반복 실패의 근본 원인 TOP 5

### ① AI가 이동시간 정보 없이 시간표를 만들고, 백엔드가 사후에 고친다 (구조 문제)
- **[코드]** 프롬프트는 "이동시간·경로를 추정하지 말라"고 하면서, 모든 항목에 `start_time`/`end_time`을 요구합니다(`PLAN_SYSTEM_PROMPT`, `PLAN_FORMAT`).
- 그 결과 장소 사이 간격은 근거 없는 값이 되고, 백엔드가 실제 경로로 밀어내는 과정(`shift_day_for_travel`)에서 식사 시간대·하루 종료 충돌이 생깁니다.
- **[로그]** plan 36: 14:00 식사가 15:39 도착 계산(99분 초과, `repair=False`), trip 82·89·91의 `ROUTE_TIME_CONFLICT`, `MISSING_LUNCH`, `MEAL_TIME_SHIFTED`가 모두 같은 패턴입니다.

### ② 출력 계약이 생성 단계에서 강제되지 않고, 같은 조건으로 재시도한다
- **[코드]** `PLAN_FORMAT`에서 `place_id`는 **item_type과 무관하게** `enum[후보 ID…, null]`입니다. 그래서 REST에 장소 ID를 붙이는 것이 문법상 허용됩니다. 금지는 프롬프트 문장과 파서에만 있어요.
- **[코드]** 재시도는 temperature 0에 같은 payload를 쓰고, 오류 코드 한 줄만 덧붙입니다.
- **[로그]** trip 93·94 모두 `non_place_item_has_place_id`가 **2회 연속** 발생했습니다. 결정적 생성이라 같은 실수를 반복할 가능성이 높아요 **[추론]**. 매 호출 77~100초가 그대로 낭비됩니다.

### ③ 파서가 '항목 단위 복구' 대신 '응답 전체 거부'를 한다 — 뒤의 복구 로직에 도달하지 못함
- **[코드]** `_parse`는 `unknown_place_id`, `non_place_item_has_place_id`, `overlapping_times`, `invalid_time`, `invalid_sequence`에서 즉시 예외를 냅니다. 3일 일정 중 항목 하나만 틀려도 전체를 버려요.
- 그런데 그 뒤에는 그 항목을 대체할 수 있는 결정적 복구들이 이미 있습니다(`_repair_meal_slots`, `_repair_missing_meals`, 관광지 보충, `_attach_rest_cafes`, `_repair_route_day`). 순서상 실행될 기회가 없어요.
- **trip 94 대조 [코드]:** `REST + place_id=211(애월해안도로)`에 제목이 후보명과 다르면, 현재 정규화 규칙에서는
  - 제목 정확 일치가 아니고
  - `_is_explicit_non_place_title`(휴식/자유시간 등 고정 단어) 에도 해당하지 않으므로
  - **여전히 `non_place_item_has_place_id`로 거부**됩니다.
  - 즉 최근 수정은 trip 94와 같은 응답(예: "애월해안도로 드라이브 휴식")을 해결하지 못합니다. 실제 제목 문자열은 로그에 남아 있지 않아 정확한 재현은 불가해요.

### ④ 신규 생성과 Preview 파이프라인이 갈라져 있어, 한쪽 수정이 다른 쪽에 전달되지 않는다
- **[코드]** Preview는 `_prepare_draft`에 preferences를 넘기지 않습니다. 그래서 SLOW REST 보호가 꺼진 상태로 식사 복구가 돌아요.
- **[코드]** Preview는 겹침을 파서에서 넘기지만(`allow_overlap_repair`), **겹침을 고치는 단계가 없습니다.**
  - `shift_day_for_travel`은 이동시간이 확인된 구간이 밀릴 때만 뒤 항목을 이동합니다. 원래부터 겹친 두 항목은 그대로예요.
  - 결국 `_validate_no_time_overlap`에서 `TIME_CONFLICT` 422가 납니다 **[추론, 코드 경로 기준]**.
- **[로그]** 실제로 이전에 Preview는 `repair=False`라 신규 생성에서 고친 보정이 적용되지 않았습니다(오늘 수정). 같은 종류의 누락이 반복된 사례예요.

### ⑤ 실제 실패 응답을 재현할 수단이 없다
- **[코드]** `MAX_RAW_RESPONSE_LOG_CHARS = 8000`이 정의돼 있지만 **어디서도 쓰지 않습니다.** AI 원문은 저장되지 않아요.
- 로그에는 코드와 일부 진단값(제목, place_id)만 남습니다.
- 그래서 수정 → 단위 테스트(합성 데이터) 통과 → 실제 호출(수분) → 다른 실패가 반복됩니다. 수정이 실제 실패 응답을 고치는지 사전 확인이 불가능해요.

---

## 3. 프롬프트·파서·검증 불일치 (구체 사례)

| # | 항목 | 프롬프트 | 파서·검증 | 문제 |
|---|---|---|---|---|
| 1 | REST/FREE_TIME의 place_id | "반드시 null" | 거부(제목 정확 일치·고정 단어만 예외) | **스키마는 허용**(`place_id` enum이 유형과 독립) → 생성 단계에서 막지 못함 |
| 2 | "쉬러 가는 장소" | 후보 장소에서 쉬면 PLACE/MEAL로 출력 | 장소 ID가 있으면 유형을 카테고리로 덮어씀 | 사용자 관심사 REST + SLOW가 "REST로 표현"을 유도. **활동 목적을 표현할 필드가 없음** |
| 3 | 제목 일치 | "후보명을 정확히" | PLACE/MEAL은 제목이 달라도 ID 기준으로 **조용히 교정**, REST는 **정확 일치만** 허용 | 같은 위반에 대한 처리 기준이 유형별로 반대 |
| 4 | item_type | 모델이 출력 | 장소가 있으면 `_canonical_item_type`으로 덮어씀 | 모델이 정한 유형은 REST/FREE_TIME 판정에만 쓰이는데, 그게 바로 실패 원인 |
| 5 | 식사 시간대 | 점심 11:30-13:30, 저녁 17:30-19:30 | 규칙·검증은 11:00-14:00 / 17:00-20:00 (`PlanQualityRules`) | 모델은 더 좁은 창으로 계획, 서버는 넓은 창으로 검증·이동 |
| 6 | 이동시간 | 추정 금지 | 시작·종료시간은 필수 | 시간표 자체가 이동시간 가정을 내포 → 원인 ① |
| 7 | Anchor 유형 | "Anchor는 PLACE 항목으로" (REGENERATION_PROMPT) | 식당 Anchor는 MEAL로 교정 | 식당 Anchor에 대해 모순 |
| 8 | 시간 겹침 | 겹치지 말 것 | 신규 생성: 즉시 거부 / Preview: 통과시키지만 보정기 없음 | 두 경로의 기준이 다르고 Preview는 결국 422 |
| 9 | 누락된 날짜 | 모든 날짜 포함 | 빠진 날은 FREE_TIME 09-18로 **관대하게** 채움 | 다른 위반은 전체 거부인데 날짜 누락만 허용 — 엄격도 불균형 |

---

## 4. A안 / B안 비교

- **A안 (현행):** EXAONE이 장소·순서·시작/종료시간 생성 → 백엔드 검증·보정
- **B안:** EXAONE은 **장소 ID·순서·방문 목적·희망 체류시간(분)**만 제안 → 백엔드가 실제 이동시간·식사창·영업시간으로 시간표 작성

| 기준 | A안 | B안 |
|---|---|---|
| 안정성 | 낮음. 시간 관련 실패(겹침, 식사창, 하루 종료, 이동 충돌)가 구조적으로 계속 발생 | 높음. 시간은 결정적 계산이라 같은 입력이면 같은 결과, 시간 관련 오류는 모델 재호출 없이 처리 |
| 생성 속도 | 출력 토큰 800~1,200, 77~280초 | 출력 축소(시간 필드 제거) **[추론]** 30~40% 토큰 감소. 재시도 감소 효과가 더 큼 |
| 구현 난이도 | 추가 작업 없음 | 중간. 시간표 작성기 1개 신규, 나머지는 기존 함수 재사용 |
| 영향 범위 | – | Provider 스키마·파서, `_generate`·Preview 앞단. **DB·API 응답·Flutter 계약은 그대로** (최종 `plan_items`에 시간이 저장되는 구조 유지) |
| 위험 | 현재 문제 지속 | 모델이 순서만 제안하므로 "선호 시간대"(예: 일출 장소 아침) 표현이 약해짐 → 선택적 `time_hint` 필드로 보완. 장소당 체류시간 기본값 정책 필요 |
| Preview 적합성 | 기존 시간 보존 요구와 충돌이 잦음 | 유지 항목은 기존 시간 고정, 변경 항목만 재배치하는 방식이 자연스러움 |

---

## 5. 추천 설계 (B안 기반, 단계적)

### 출력 계약 (모델)
```json
{"days":[{"visit_date":"2026-10-26","stops":[
  {"order":1,"place_id":211,"intent":"VISIT|MEAL|REST_AT_PLACE","stay_minutes":120,"time_hint":"MORNING|LUNCH|AFTERNOON|DINNER|null"},
  {"order":2,"kind":"REST","minutes":60}
]}]}
```
- `place_id`가 있는 항목과 없는 휴식 항목을 **스키마 단계에서 분리**합니다(`anyOf`). 그러면 "REST + place_id" 자체가 생성될 수 없어요.
- `item_type`은 모델 출력이 아니라 **백엔드가 카테고리로 결정**합니다(이미 `_canonical_item_type`이 그렇게 동작).
- **`intent`**에 방문 목적을 담습니다. 예: 애월해안도로 + `REST_AT_PLACE` → item_type은 카테고리 기준 PLACE, 추천 사유와 UI에 "드라이브하며 휴식"으로 표시.
- 장소 ID 검증은 그대로 유지: 후보 밖 ID → 해당 항목만 제거하고 기록. Anchor 누락 → 실패. 제목은 출력하지 않으므로 제목 불일치 문제 자체가 사라집니다.

### 재사용 가능한 기존 코드
| 역할 | 기존 함수 |
|---|---|
| 후보 수집·다양화 | `_input`, `_candidate_places`, `_balanced_candidate_pool`, `_activity_backfill`, `_meal_backfill` |
| 장소 유형 판정 | `ExaonePlanGenerationProvider._canonical_item_type`, `is_restaurant`, `is_cafe`, `_is_food_or_cafe` |
| 중복 ID 교체 | `_repair_duplicates` |
| 체류시간 기준 | `REPAIR_MIN_*` 상수, `PlanQualityRules.max_place_minutes`/`min_place_minutes`, `_repair_minimum_minutes` |
| 시간표 배치(이동시간 반영) | `shift_day_for_travel`, `fit_day_for_travel`, `CachedRouteProvider`, `_route_estimate`, `_rest_cafe_leg` |
| 식사 배치 | `_repair_meal_slots`, `_repair_missing_meals`, `_recover_lunch_from_rest`, `_replace_far_meals`, `PlanQualityRules.lunch/dinner` |
| 휴식 장소 | `_attach_rest_cafes` |
| 경로 충돌 복구 | `_repair_route_day` |
| 영업시간 | `adjust_day_for_opening_hours`, `opening_hours_match`, `_validate_temporal_draft` |
| 최종 검증·경고 | `_validate_route_timing`, `_validate_activity_diversity`, `review_plan`, `PlanValidationService` |
| 변경 추적 | `PlanChangeTrace` |
| Preview 저장·승인 | `PlanRegenerationPreviewService._diff`, `_proposed_item`, Approve/Cancel 서비스 (변경 불필요) |

신규로 필요한 것은 사실상 **"순서+체류시간 → 시작/종료시간" 배치 함수 1개**입니다. 09:00 시작, 이동시간은 `_route_estimate`, 식사는 시간대에 맞춰 정렬하고, 이후 위 단계에 그대로 넘깁니다.

---

## 6. 단계별 개선 계획

| 단계 | 내용 | 효과 | 위험 |
|---|---|---|---|
| **0. 재현 기반 (먼저)** | AI 원문 Fixture 저장(옵트인) + Replay 테스트 하네스 (7장) | 이후 모든 수정을 실제 실패 응답으로 검증 | 낮음 |
| **1. 최소 수정** | ① `PLAN_FORMAT`을 PLACE/MEAL 항목과 REST/FREE_TIME 항목의 `anyOf`로 분리해 REST의 place_id를 문법으로 차단 ② 파서의 항목 단위 실패(`non_place…`, 후보 밖 ID)를 응답 전체 거부 대신 **해당 항목을 FREE_TIME으로 강등하고 기록**(Anchor 관련이면 기존처럼 실패) ③ 프롬프트 식사 시간대를 규칙(11-14 / 17-20)과 일치 ④ Preview `_prepare_draft`에 preferences 전달 | trip 93·94 유형 즉시 해소, 재시도 감소 | 강등된 칸은 기존 보충 로직(관광지 보충, 휴식 카페)이 채움. 미검증 장소 확정 없음 |
| **2. Preview 정합** | 겹침을 넘기는 대신 **결정적 겹침 해소**(뒤 항목을 앞 항목 종료로 이동 → 기존 shift·repair) 추가, 또는 겹침 넘기기를 제거하고 신규 생성과 동일 기준 사용. 신규 생성과 Preview의 후처리 체인을 **하나의 함수로 통합** | 한쪽 수정이 양쪽에 적용 | 기존 Preview 테스트 다수 영향 |
| **3. B안 전환** | 출력 계약을 `stops(order, place_id, intent, stay_minutes, time_hint)`로 변경, 시간표 작성기 도입, 기존 보정 체인 재사용 | 시간 관련 실패의 구조적 제거, 출력 토큰 감소 | Provider·파서·관련 테스트 대규모 수정. A/B를 설정 플래그로 병행 운영 권장 |

---

## 7. 회귀 테스트·실제 검증 전략

- **AI 원문 보존 현황 [코드]:** 현재 원문은 저장되지 않습니다(`MAX_RAW_RESPONSE_LOG_CHARS` 미사용). trip 93·94 원문은 **없습니다**.
- **안전한 수집**
  - 설정 플래그(예: `PLAN_AI_FIXTURE_DIR`, 기본 off)를 켰을 때만 `message.content`를 저장해요.
  - 함께 저장: 후보 스냅샷(place_id, name, category, 좌표, is_anchor), 날짜, 오류 코드
  - 저장 위치: `.gitignore`된 로컬 폴더
  - 저장 제외: 사용자 ID, 동행자 이름, 토큰, payload 원문. 프롬프트는 해시만 남겨요.
- **Replay 테스트:** Fixture를 `ExaonePlanGenerationProvider._parse`에 그대로 넣고, 그 뒤 `PlanGenerationService` 후처리 체인을 다시 실행해요.
  - 가짜 Provider로 원문을 그대로 돌려줘요.
  - 경로는 `CachedRouteProvider`에 기록된 경로 값을 재생해요(경로 응답도 Fixture로 함께 저장).
  - 결과: 모델 재호출 없이 몇 초 안에 같은 실패를 재현할 수 있어요.
- **수정 전 실패 / 수정 후 통과:** 각 Fixture마다 기대 결과(실패 코드 또는 통과·경고 목록)를 기록합니다. CI에서 전 Fixture를 돌려요.
- **계약 테스트:** 프롬프트에 적힌 규칙(식사 시간대, REST place_id, 필수 필드)을 상수로 뽑아 프롬프트·`PLAN_FORMAT`·파서·`PlanQualityRules`가 같은 값을 쓰는지 검사해요. 불일치 3장 #1·#5·#8 같은 문제를 자동으로 잡을 수 있어요.
- **실제 검증:** Replay가 통과한 뒤에만 실제 EXAONE을 고정 시나리오(제주 3일 SLOW 등)로 1회 호출해요. 실패하면 그 원문이 곧 다음 Fixture가 돼요.

---

## 8. 수정 시 보존해야 할 기능

- 후보 밖 장소 거부, 미검증 장소 자동 확정 금지, 제목 기반 ID 교정은 **정확히 한 곳 일치할 때만**
- Anchor 보존(교정·교체·단축 대상 제외), `selected_place_ids` 생략/`[]` 계약
- 실제 경로 이동시간만 사용(추정 금지), 도보 확인은 300m 이내에서만
- 식사 시간대·영업시간·하루 종료 검증, 식사 누락은 경고로 저장
- SLOW REST 시간 보호
- Preview: 승인 전 DB 불변, Approve/Cancel, base_version 검증, 사유 목표 검증
- 응답 스키마·Flutter 계약(`plan_items` 시간 필드, warnings), `PlanChangeTrace` 로그

## 불확실한 사항
- trip 93·94의 실제 제목 문자열과 나머지 항목 구성은 확인할 수 없어요(원문 미보존). 3장 #2의 해석은 사용자 제공 로그 기준이에요.
- Preview의 겹침 넘기기가 실제로 `TIME_CONFLICT`로 끝나는지는 코드 경로상 판단이에요. 실제 사례 로그로는 확인하지 못했어요.
- B안의 속도 개선 폭은 출력 토큰 감소 기준의 추정이에요. 실제 측정이 필요해요.
