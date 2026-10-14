# ROUTE_TIME_CONFLICT 여행 생성 실패 수정 보고서 (2026-10-13)

대상: `C:\dev\dx-final-upload\backend`. DB 초기화, migration 변경, 기존 작업 삭제는 하지 않았습니다.

## 1. 최초 충돌의 정확한 원인

재현 방법: trip 82(부산, 2026-10-26~27, CAR)를 실제 EXAONE·Kakao·MySQL로 생성하되, 세션의 commit을 막고 마지막에 rollback했습니다. DB에는 아무것도 저장하지 않았습니다.

수정 전 재현 흐름 (2026-10-27):

| 단계 | 내용 |
|---|---|
| EXAONE 초안 | 4번째 항목에 15:30 식당을 넣음. 식사 시간대 밖이라 서버가 관광지(송정해수욕장)로 교체(`MEAL_OUTSIDE_WINDOW`) |
| 점심 보충 | 점심이 없어 서버가 기존 13:30~15:00 칸에 신선식당을 넣음(`MISSING_LUNCH`). 13:30은 식사 규칙(11:00~14:00) 안이지만 이동시간 검사 기준(11:30~13:30)의 **끝 시각** |
| 직전 장소 | 홉슈크림(카페) 12:00~13:00 |
| 검증 이동시간 | 카페 → 신선식당 31분 |
| 도착 시각 | 13:00 + 31분 = 13:31 (재실행에서는 13:37) |
| 판정 | `plan_travel_time.shift_day_for_travel`이 고정값 11:30~13:30으로 판정 → `MEAL_WINDOW` 충돌 |
| 자동 보정 | `_repair_route_day`가 REORDER → TRIM → 식당 교체 → 관광지 삭제 순으로 시도. 실패하면 422 |

결론적으로 EXAONE 초안의 잘못이 아니라 서버 쪽 시간 계산 문제가 겹친 것이었습니다.

확정된 원인 네 가지:

1. **식사 시간대 기준 불일치 (주원인).** `plan_travel_time.py`의 `MEAL_WINDOWS`는 11:30~13:30 / 17:30~19:30으로 하드코딩돼 있습니다. 반면 점심 보충, 식사 재배치, 최종 식사 검증(`PlanQualityRules`)은 설정값 11:00~14:00 / 17:00~20:00을 씁니다. 그래서 규칙상 정상인 13:31~13:59 점심이 이동시간 검사에서만 거절됐습니다.
2. **앞 일정이 당겨지지 않음.** TRIM 보정이 관광지 체류를 줄여도 그 뒤 일정(카페)의 시작은 그대로였습니다. 바로 앞 항목이 아니면 줄인 시간이 빈 시간으로 남아 충돌 해소에 쓰이지 않았습니다.
3. **지연 누적.** 한 구간에서 생긴 지연(shift)이 이후 모든 항목에 그대로 더해졌습니다. 초안에 있던 여유 시간이 지연을 흡수하지 못해, 뒤쪽 식사까지 불필요하게 밀렸습니다.
4. **저녁 칸 없음 (보정 후 드러난 다음 실패).** 송정해수욕장이 17:30까지 이어져 저녁이 필요한 날로 판정됐습니다. 하지만 저녁 칸도 저녁 식당 후보도 없어(경로 비교 예산 소진, 근처 식당 없음) `MEAL_SCHEDULE_INCOMPLETE (MISSING_DINNER)`로 실패했습니다. 수정 전 재현 1회차는 TRIM으로 이동시간 충돌을 넘긴 뒤 이 원인으로 실패했습니다.

검증한 결과 아니었던 것: 이동시간·대기시간 중복 합산(REST 시간만 따로 더함, 정상), 추정 이동시간 혼합(검증된 Kakao 경로만 사용, 없으면 미적용), dx-all 병합 코드와 데이터 모델 불일치(없음).

## 2. 문제 발생 파일 및 함수

- `app/services/plan_travel_time.py`: `MEAL_WINDOWS`, `shift_day_for_travel`, `_shorten`, `fit_day_for_travel`
- `app/services/plan_generation_service.py`: `_adjust_route_timing`, `_repair_route_day`, `_repair_missing_meals`

## 3. 수정한 코드와 이유

| 파일·함수 | 변경 | 이유 |
|---|---|---|
| `plan_travel_time.shift_day_for_travel` | `meal_windows` 인자 추가. 생성 서비스는 `PlanQualityRules`의 창을 넘김 | 이동시간 검사와 식사 규칙·최종 검증의 기준을 하나로 통일. 검사를 없앤 것이 아니고, 14:00/20:00을 넘으면 여전히 충돌 |
| 같은 함수 | 지연은 다음 항목과 겹칠 때만 전파. 초안의 여유 시간이 흡수 | 지연 누적 방지. 여유가 없으면 기존처럼 연쇄적으로 재계산 |
| `plan_travel_time._shorten` / `fit_day_for_travel` | 관광지를 줄이면 충돌 지점 전까지의 유연한 일정도 같은 만큼 앞당김. 식사·식당·Anchor에서 멈추고 그 이상은 당기지 않음 | 줄인 시간이 실제로 충돌 해소에 쓰이도록. 당긴 뒤 운영시간은 `attempt()`에서 다시 검사 |
| `TravelShiftConflict.detail` + `_conflict_detail` | 구조화 로그 추가 | 아래 7번 참고 |
| `_repair_missing_meals` | 하루가 식사 시간대까지 이어지는데 칸이 없으면 마지막 장소 뒤에 60분 식사 칸을 열고 검증된 식당으로 채움 | MISSING_DINNER 자동 해소 |
| 같은 함수 | 경로 비교 예산이 바닥나 한 곳도 측정하지 못했을 때만, 5km 이내 가장 가까운 식당을 선택. 이후 이동시간 검사와 최종 검증은 그대로 적용 | 예산 소진이 곧 식사 누락으로 이어지지 않게 |
| `_end_day_before_meal` (신규) | 식당을 못 찾으면 마지막 관광지(Anchor·식당·카페 제외)를 식사 시간대 시작 시각에 끝나도록 줄임. 최소 60분 이상, 원래 길이의 70% 이상 유지 | 저녁이 없는 짧은 마지막 날로 정리. 조건이 안 맞으면 그대로 두어 최종 검증이 거절 |

유지한 것: 반복 보정 상한(`MAX_FIT_ROUNDS = 8`)은 그대로라 무한 반복이 없습니다. Anchor는 줄이지도, 옮기지도, 삭제하지도 않습니다. 운영시간, 이벤트 날짜, 22:00 하루 종료, 최종 식사 검증, 검증 전 저장 금지도 그대로입니다. `selected_place_ids` 생략/[] 계약과 Preview/Approve(`repair=False`)의 엄격한 경로도 유지했습니다. 다만 Preview도 같은 식사 시간대 설정을 쓰게 됐습니다.

## 4. 자동 보정 전후 시간 비교 (실제 EXAONE 초안, trip 82)

| 날짜 | 항목 | 초안 | 수정 전 | 수정 후 (저장 결과, 이동시간 모두 KNOWN) |
|---|---|---|---|---|
| 10-26 | 광안리해수욕장 | 09:00~12:00 | | 09:00~12:00 |
| | 스타벅스 광안비치점 | 12:00~13:00 | | 12:01~13:01 (이동 1분) |
| | 진미회집 (점심) | 13:30~15:30 | 이동시간 충돌 → TRIM | 13:30~15:30 |
| | 다대포해수욕장 | 15:30~16:30 | | 16:03~17:03 (이동 33분) |
| 10-27 | 해운대해수욕장 | 09:00~12:00 | | 09:00~12:00 |
| | 홉슈크림 | 12:00~13:00 | | 12:06~13:06 (이동 6분) |
| | 신선식당 (점심) | 13:30~15:00 | 13:37 도착 → **ROUTE_TIME_CONFLICT** | 13:37~15:07 (이동 31분, 14:00 이내) |
| | 송정해수욕장 | 15:30~17:30 | 17:30 이후 저녁 없음 → **MISSING_DINNER** | 15:37~17:07 (이동 30분, 저녁 전 종료로 단축) |

## 5. 테스트 결과

- 백엔드 단위 테스트 `pytest tests/unit`: **715 성공 / 3 실패**. 3개는 이번 작업 전부터 실패하던 테스트입니다(`test_plan_validation_service::test_validation_marks_valid_items`, `test_trip_service` 2개).
- 신규 `tests/unit/test_route_time_meal_windows.py` 14개, 모두 성공:
  - 2026-10-27 실제 사례 재현(카페 뒤 13:40 점심 허용, 이후 일정 재계산)
  - 점심 초과 → 카페 단축으로 복구
  - 저녁 초과 → 앞 관광지 단축, 이후 시간 재계산
  - 앞당김(compaction)으로만 복구 가능한 경우
  - 다음 장소 운영시간(12:00 개관)보다 앞당기지 않음
  - 고정 Anchor 불변(다른 검증 식당으로 대체)
  - 복구 불가 시 422와 구조화 로그
  - Preview 경로는 여전히 거절
  - 3일 일정에서 충돌한 날만 보정
  - 저녁 칸 자동 추가 / 식당 없으면 마지막 관광지 단축 / Anchor면 그대로 / 예산 소진 시 최근접 식당
- 기존 테스트 수정:
  - `test_route_time_repair.py`: 보정 전략 시나리오가 11:30~13:30 기준이라 그 창을 명시적으로 고정
  - `test_route_time_shift.py`: "지연이 여유 시간을 무시하고 끝까지 전파" 기대를 "여유가 있으면 흡수"로 변경, 여유가 없을 때 연쇄 전파 테스트 추가

## 6. 실제 여행 생성 성공 여부

- 실제 EXAONE 3.5 7.8B + Kakao 경로 + MySQL 조회로 trip 82 생성을 롤백 트랜잭션에서 실행: **성공** (`PlanGenerateResponse`, 위 4번 표). 저장 직전까지 모든 검증을 통과했고, 그 뒤 rollback해서 DB에는 남지 않았습니다.
- 실기기 앱에서의 생성: **미검증**. 앱에서 같은 여행으로 다시 생성해 주세요.

## 7. 진단 로그

이동시간 충돌 시 아래 형식으로 남습니다(이름 대신 ID·시각·분만 기록, 키·토큰 없음).

```
route_time_shift_failed visit_date=2026-10-27 kind=MEAL_WINDOW detail={'sequence': 3, 'place_id': 146, 'item_type': 'MEAL', 'original_start': '13:30', 'original_end': '15:00', 'travel_minutes': 31, 'meal_window': '11:00-14:00', 'computed_arrival': '14:10', 'overflow_minutes': 10} repair=True
route_time_repaired visit_date=... strategy=TRIM trimmed_minutes=10 changed_place_ids=[]
route_time_repair_failed visit_date=... kind=MEAL_WINDOW place='신선식당' tried=['REORDER', 'TRIM', 'REPLACE_RESTAURANT', 'DROP_OPTIONAL'] detail={...}
plan_missing_meal_route_selection ... window=DINNER ... selection=verified_route|distance_fallback|none
plan_draft_repaired trip_id=82 reason=DAY_END_BEFORE_DINNER visit_date=2026-10-27 sequence=4 place_id=402 from_end=17:30 to_end=17:00
```

422 응답의 `details`에는 `visit_date`, `conflict`(MEAL_WINDOW/DAY_END), `place_name`, `tried`가 들어갑니다.

한글 깨짐: 로그 파일(UTF-8)과 Flutter 로그캣에서는 식당 이름이 정상입니다(`진미회집`, `신선식당`). 깨져 보였던 것은 Windows 콘솔(cp949)로 출력할 때의 표시 문제입니다. 깨지면 FastAPI 실행 전에 `$env:PYTHONIOENCODING='utf-8'`를 설정하세요.

## 8. 남아 있는 오류 및 제약사항

- **경로 API 예산:** 한 번 생성할 때 `route_budget_denied=22`(요청당 경로 호출 상한 초과)가 나옵니다. 이번 결과는 저장된 구간이 모두 KNOWN이었지만, 일정이 길어지면 일부 구간이 UNKNOWN(이동시간 미검증)으로 남을 수 있습니다.
- **저녁 식당 후보 부족:** 송정 근처에 쓸 수 있는 저녁 식당 후보가 없었습니다(`plan_candidate_meal_backfill found=0`). 그래서 저녁을 넣지 않고 관광 종료를 17:00으로 당겼습니다.
- **EXAONE 출력 품질:** 초안이 15:30에 식당을 두거나 점심을 빼먹는 문제는 여전히 서버 보정에 의존합니다. 생성에는 약 52~81초가 걸렸습니다.
- **서버 재시작:** 수정 중 FastAPI `--reload`가 휴대폰 WebSocket 연결 때문에 재시작하지 못하고 멈췄습니다. 그래서 멈춘 프로세스를 종료하고, Claude 터미널 패널(탭 "FastAPI")에서 같은 명령으로 다시 실행했습니다(현재 HTTP 200). 이후 코드 변경 때 다시 멈추면 Ctrl+C 후 재실행하세요.
- 기존에 실패하던 백엔드 테스트 3개는 그대로입니다.
