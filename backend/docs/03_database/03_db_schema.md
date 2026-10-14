# 03. Database Schema — Draft Final

## 1. 기준

- DB: MySQL 8.x
- Engine: InnoDB
- Charset: utf8mb4
- Naming: 복수형 snake_case
- 현재 사용자는 JWT로 식별
- 핵심 관심사 코드는 `interest_codes` 기준
- 사용자/동행자/여행 삭제는 기본적으로 Soft Delete
- AI 결과와 실제 검증 데이터를 분리
- JSON은 스냅샷·외부 메타데이터처럼 구조가 유동적인 데이터에만 사용

---

# 2. 최종 테이블 목록 — 22개

## 인증 / 사용자
1. `users`
2. `user_auths`
3. `refresh_tokens`
4. `user_preferences`
5. `interest_codes`
6. `user_interests`

## 동행자
7. `companions`
8. `companion_preferences`
9. `companion_interests`

## 여행
10. `trips`
11. `trip_preferences`
12. `trip_companions`
13. `trip_interests`

## 콘텐츠 / 장소
14. `trip_sources`
15. `places`
16. `source_places`

## 일정
17. `travel_plans`
18. `plan_items`
19. `plan_revisions`
20. `plan_validation_issues`

## 스마트 도슨트
21. `docent_analyses`
22. `docent_candidates`

---

# 3. 전체 ERD

```text
USERS
│
├── USER_AUTHS
├── REFRESH_TOKENS
├── USER_PREFERENCES
├── USER_INTERESTS ─────────────────────────┐
│                                           │
├── COMPANIONS                              │
│    ├── COMPANION_PREFERENCES              │
│    └── COMPANION_INTERESTS ───────────────┤
│                                           │
├── TRIPS                                   │
│    ├── TRIP_PREFERENCES                   │
│    ├── TRIP_INTERESTS ────────────────────┤
│    ├── TRIP_COMPANIONS ─────→ COMPANIONS  │
│    ├── TRIP_SOURCES                       │
│    │     └── SOURCE_PLACES ─────→ PLACES  │
│    │                                      │
│    └── TRAVEL_PLANS                       │
│          ├── PLAN_ITEMS ─────────→ PLACES │
│          ├── PLAN_REVISIONS               │
│          └── PLAN_VALIDATION_ISSUES       │
│                                           │
└── DOCENT_ANALYSES                         │
      └── DOCENT_CANDIDATES ──────→ PLACES │
                                            │
INTEREST_CODES ◀────────────────────────────┘
```

---

# 4. Database 생성

```sql
CREATE DATABASE IF NOT EXISTS travel_ai
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_0900_ai_ci;

USE travel_ai;
```

---

# 5. users

```sql
CREATE TABLE users (
    user_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    nickname VARCHAR(50) NULL,
    password_hash VARCHAR(255) NULL,
    age_group ENUM('UNDER_20','20S','30S','40S','50S','60S','70S_PLUS') NULL,
    profile_completed BOOLEAN NOT NULL DEFAULT FALSE,
    status ENUM('ACTIVE','WITHDRAWN','SUSPENDED') NOT NULL DEFAULT 'ACTIVE',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;
```

정책:
- 소셜 최초 로그인 직후에는 nickname이 아직 없을 수 있으므로 NULL 허용
- 초기 프로필 설정 완료 시 nickname은 필수
- nickname 중복 허용
- `profile_completed = TRUE` 기준:
  - nickname 입력
  - age_group 입력
  - user_preferences 입력
  - 최소 1개 이상의 user_interests 입력

---

# 6. user_auths

```sql
CREATE TABLE user_auths (
    auth_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    provider ENUM('LOCAL','KAKAO','NAVER') NOT NULL,
    provider_user_id VARCHAR(255) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_login_at DATETIME NULL,

    CONSTRAINT fk_user_auths_user
        FOREIGN KEY (user_id)
        REFERENCES users(user_id)
        ON DELETE CASCADE,

    CONSTRAINT uq_user_auths_provider_user
        UNIQUE (provider, provider_user_id),

    CONSTRAINT uq_user_auths_user_provider
        UNIQUE (user_id, provider)
) ENGINE=InnoDB;
```

정책:
- 같은 이메일이라는 이유로 Kakao/Naver 계정을 자동 통합하지 않음
- Provider Access Token 장기 저장 금지

---

# 7. refresh_tokens

```sql
CREATE TABLE refresh_tokens (
    refresh_token_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    token_hash VARCHAR(255) NOT NULL,
    expires_at DATETIME NOT NULL,
    revoked_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_refresh_tokens_user
        FOREIGN KEY (user_id)
        REFERENCES users(user_id)
        ON DELETE CASCADE,

    CONSTRAINT uq_refresh_tokens_hash
        UNIQUE (token_hash)
) ENGINE=InnoDB;
```

정책:
- Refresh Token 원문 저장 금지
- 로그아웃 시 `revoked_at` 기록

---

# 8. user_preferences

```sql
CREATE TABLE user_preferences (
    user_preference_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,

    walking_tolerance ENUM('VERY_LOW','LOW','NORMAL','HIGH') NULL,
    rest_frequency ENUM('LOW','NORMAL','HIGH') NULL,

    avoid_stairs BOOLEAN NOT NULL DEFAULT FALSE,
    avoid_hills BOOLEAN NOT NULL DEFAULT FALSE,
    taxi_allowed BOOLEAN NOT NULL DEFAULT TRUE,
    travel_style ENUM('SLOW', 'STANDARD', 'FOOD_FOCUSED') NULL,
    senior_mode BOOLEAN NOT NULL DEFAULT FALSE,

    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,

    CONSTRAINT fk_user_preferences_user
        FOREIGN KEY (user_id)
        REFERENCES users(user_id)
        ON DELETE CASCADE,

    CONSTRAINT uq_user_preferences_user
        UNIQUE (user_id)
) ENGINE=InnoDB;
```

---

# 9. interest_codes

```sql
CREATE TABLE interest_codes (
    interest_code VARCHAR(50) PRIMARY KEY,
    label_ko VARCHAR(50) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order INT NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;
```

초기값:

```sql
INSERT INTO interest_codes
    (interest_code, label_ko, sort_order)
VALUES
    ('FOOD', '맛집', 1),
    ('CAFE', '카페', 2),
    ('NATURE', '자연', 3),
    ('CULTURE', '문화', 4),
    ('HISTORY', '역사', 5),
    ('SHOPPING', '쇼핑', 6),
    ('EXHIBITION', '전시', 7),
    ('ACTIVITY', '체험', 8),
    ('CITY', '도시', 9),
    ('REST', '휴식', 10),
    ('SEA', '바다', 11);
```

AI는 이 테이블에 존재하는 코드만 반환한다.

---

# 10. user_interests

```sql
CREATE TABLE user_interests (
    user_interest_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    interest_code VARCHAR(50) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_user_interests_user
        FOREIGN KEY (user_id)
        REFERENCES users(user_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_user_interests_code
        FOREIGN KEY (interest_code)
        REFERENCES interest_codes(interest_code)
        ON DELETE RESTRICT,

    CONSTRAINT uq_user_interests_user_code
        UNIQUE (user_id, interest_code)
) ENGINE=InnoDB;
```

---

# 11. companions

```sql
CREATE TABLE companions (
    companion_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    name VARCHAR(50) NOT NULL,

    relation ENUM(
        'FATHER','MOTHER','SPOUSE','CHILD','FRIEND','OTHER'
    ) NOT NULL,

    age_group ENUM('UNDER_20','20S','30S','40S','50S','60S','70S_PLUS') NULL,

    status ENUM('ACTIVE','ARCHIVED') NOT NULL DEFAULT 'ACTIVE',

    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,

    CONSTRAINT fk_companions_user
        FOREIGN KEY (user_id)
        REFERENCES users(user_id)
        ON DELETE CASCADE
) ENGINE=InnoDB;
```

`DELETE /companions/{companion_id}`는 실제 삭제가 아니라 `ARCHIVED` 처리.

---

# 12. companion_preferences

```sql
CREATE TABLE companion_preferences (
    companion_preference_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    companion_id BIGINT NOT NULL,

    walking_tolerance ENUM('VERY_LOW','LOW','NORMAL','HIGH') NULL,
    rest_frequency ENUM('LOW','NORMAL','HIGH') NULL,

    avoid_stairs BOOLEAN NOT NULL DEFAULT FALSE,
    avoid_hills BOOLEAN NOT NULL DEFAULT FALSE,
    taxi_allowed BOOLEAN NOT NULL DEFAULT TRUE,

    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,

    CONSTRAINT fk_companion_preferences_companion
        FOREIGN KEY (companion_id)
        REFERENCES companions(companion_id)
        ON DELETE CASCADE,

    CONSTRAINT uq_companion_preferences_companion
        UNIQUE (companion_id)
) ENGINE=InnoDB;
```

---

# 13. companion_interests

```sql
CREATE TABLE companion_interests (
    companion_interest_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    companion_id BIGINT NOT NULL,
    interest_code VARCHAR(50) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_companion_interests_companion
        FOREIGN KEY (companion_id)
        REFERENCES companions(companion_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_companion_interests_code
        FOREIGN KEY (interest_code)
        REFERENCES interest_codes(interest_code)
        ON DELETE RESTRICT,

    CONSTRAINT uq_companion_interests_companion_code
        UNIQUE (companion_id, interest_code)
) ENGINE=InnoDB;
```

---

# 14. trips

```sql
CREATE TABLE trips (
    trip_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,

    title VARCHAR(100) NULL,
    departure VARCHAR(100) NULL,
    destination VARCHAR(100) NULL,

    start_date DATE NULL,
    end_date DATE NULL,

    budget_krw INT UNSIGNED NULL,

    transport_mode ENUM(
        'PUBLIC_TRANSIT','CAR','WALK','MIXED','OTHER'
    ) NULL,

    status ENUM(
        'DRAFT','PLANNED','IN_PROGRESS',
        'COMPLETED','CANCELLED','ARCHIVED'
    ) NOT NULL DEFAULT 'DRAFT',

    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,

    CONSTRAINT fk_trips_user
        FOREIGN KEY (user_id)
        REFERENCES users(user_id)
        ON DELETE CASCADE,

    CONSTRAINT chk_trips_dates
        CHECK (
            end_date IS NULL
            OR start_date IS NULL
            OR end_date >= start_date
        )
) ENGINE=InnoDB;
```

정책:
- destination은 콘텐츠 분석 후 정해질 수 있으므로 NULL 허용
- DELETE API는 `ARCHIVED`

---

# 15. trip_preferences

```sql
CREATE TABLE trip_preferences (
    trip_preference_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    trip_id BIGINT NOT NULL,

    walking_tolerance ENUM('VERY_LOW','LOW','NORMAL','HIGH') NULL,
    rest_frequency ENUM('LOW','NORMAL','HIGH') NULL,

    avoid_stairs BOOLEAN NOT NULL DEFAULT FALSE,
    avoid_hills BOOLEAN NOT NULL DEFAULT FALSE,
    taxi_allowed BOOLEAN NOT NULL DEFAULT TRUE,
    travel_style ENUM('SLOW','STANDARD','FOOD_FOCUSED') NULL,

    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,

    CONSTRAINT fk_trip_preferences_trip
        FOREIGN KEY (trip_id)
        REFERENCES trips(trip_id)
        ON DELETE CASCADE,

    CONSTRAINT uq_trip_preferences_trip
        UNIQUE (trip_id)
) ENGINE=InnoDB;
```

새 여행 생성 시 `user_preferences`를 기본값으로 복사한다.

---

# 15-1. trip_selected_places

사용자가 여행 생성 전에 직접 선택한 장소를 여행별로 저장한다.

```sql
CREATE TABLE trip_selected_places (
    trip_selected_place_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    trip_id BIGINT NOT NULL,
    place_id BIGINT NOT NULL,
    selected_order INT UNSIGNED NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_trip_selected_places_trip
        FOREIGN KEY (trip_id)
        REFERENCES trips(trip_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_trip_selected_places_place
        FOREIGN KEY (place_id)
        REFERENCES places(place_id)
        ON DELETE RESTRICT,

    CONSTRAINT uq_trip_selected_places_trip_place
        UNIQUE (trip_id, place_id),

    CONSTRAINT uq_trip_selected_places_trip_order
        UNIQUE (trip_id, selected_order)
) ENGINE=InnoDB;
```

---

# 16. trip_companions

```sql
CREATE TABLE trip_companions (
    trip_companion_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    trip_id BIGINT NOT NULL,
    companion_id BIGINT NULL,
    member_user_id BIGINT NULL,

    name_snapshot VARCHAR(50) NOT NULL,

    relation_snapshot ENUM(
        'FATHER','MOTHER','SPOUSE','CHILD','FRIEND','OTHER'
    ) NOT NULL,

    age_group_snapshot ENUM(
        'UNDER_20','20S','30S','40S','50S','60S','70S_PLUS'
    ) NULL,

    walking_tolerance ENUM('VERY_LOW','LOW','NORMAL','HIGH') NULL,
    rest_frequency ENUM('LOW','NORMAL','HIGH') NULL,

    avoid_stairs BOOLEAN NOT NULL DEFAULT FALSE,
    avoid_hills BOOLEAN NOT NULL DEFAULT FALSE,
    taxi_allowed BOOLEAN NOT NULL DEFAULT TRUE,

    interests_snapshot JSON NULL,

    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,

    CONSTRAINT fk_trip_companions_trip
        FOREIGN KEY (trip_id)
        REFERENCES trips(trip_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_trip_companions_companion
        FOREIGN KEY (companion_id)
        REFERENCES companions(companion_id)
        ON DELETE SET NULL,

    CONSTRAINT fk_trip_companions_member_user
        FOREIGN KEY (member_user_id)
        REFERENCES users(user_id)
        ON DELETE SET NULL,

    CONSTRAINT uq_trip_companions_trip_companion
        UNIQUE (trip_id, companion_id),

    CONSTRAINT uq_trip_companions_trip_member
        UNIQUE (trip_id, member_user_id)
) ENGINE=InnoDB;
```

snapshot을 두는 이유:
- 나중에 동행자 기본 프로필이 변경되어도 과거 여행 당시 조건 보존
- `interests_snapshot`은 이력 목적이라 JSON 허용

`member_user_id`:
- 초대 링크로 참여한 앱 사용자일 때만 채운다 (`companion_id`는 NULL)
- 여행 소유자의 `companion_ids` 수정으로 지워지지 않는다

---

# 16-1. trip_share_links

```sql
CREATE TABLE trip_share_links (
    trip_share_link_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    trip_id BIGINT NOT NULL,
    created_by_user_id BIGINT NOT NULL,

    token_hash VARCHAR(64) NOT NULL,
    link_type ENUM('VIEW','INVITE') NOT NULL,

    expires_at DATETIME NULL,
    revoked_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_trip_share_links_trip
        FOREIGN KEY (trip_id)
        REFERENCES trips(trip_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_trip_share_links_user
        FOREIGN KEY (created_by_user_id)
        REFERENCES users(user_id)
        ON DELETE CASCADE,

    CONSTRAINT uq_trip_share_links_token_hash
        UNIQUE (token_hash)
) ENGINE=InnoDB;
```

- 원본 token은 저장하지 않고 SHA-256 hash만 저장 (`refresh_tokens`와 같은 원칙)
- `VIEW`: 보기 전용 공유 링크, 만료 없음
- `INVITE`: 동행자 초대 링크, 7일 후 만료, 참여 시 `trip_companions.member_user_id` 생성

---

# 17. trip_interests

```sql
CREATE TABLE trip_interests (
    trip_interest_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    trip_id BIGINT NOT NULL,
    interest_code VARCHAR(50) NOT NULL,

    source_type ENUM(
        'PROFILE','CONTENT_AI','USER'
    ) NOT NULL,

    is_confirmed BOOLEAN NOT NULL DEFAULT FALSE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    confirmed_at DATETIME NULL,

    CONSTRAINT fk_trip_interests_trip
        FOREIGN KEY (trip_id)
        REFERENCES trips(trip_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_trip_interests_code
        FOREIGN KEY (interest_code)
        REFERENCES interest_codes(interest_code)
        ON DELETE RESTRICT,

    CONSTRAINT uq_trip_interests_trip_code
        UNIQUE (trip_id, interest_code)
) ENGINE=InnoDB;
```

---

# 18. trip_sources

YouTube 콘텐츠 입력 데이터.

`trip_source_tags`는 만들지 않고 tags를 JSON으로 저장한다.

```sql
CREATE TABLE trip_sources (
    source_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    trip_id BIGINT NOT NULL,

    source_type ENUM('YOUTUBE') NOT NULL,
    external_id VARCHAR(255) NOT NULL,
    source_url VARCHAR(1000) NOT NULL,

    title VARCHAR(500) NULL,
    description TEXT NULL,
    tags JSON NULL,

    channel_id VARCHAR(255) NULL,
    channel_title VARCHAR(255) NULL,

    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    metadata_collected_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_trip_sources_trip
        FOREIGN KEY (trip_id)
        REFERENCES trips(trip_id)
        ON DELETE CASCADE,

    CONSTRAINT uq_trip_sources_trip_external
        UNIQUE (trip_id, source_type, external_id)
) ENGINE=InnoDB;
```

DELETE API는 `is_active = FALSE`.

---

# 19. places

공통 장소 마스터.

`place_details`는 별도 테이블로 두지 않고 통합한다.

```sql
CREATE TABLE places (
    place_id BIGINT AUTO_INCREMENT PRIMARY KEY,

    name VARCHAR(255) NOT NULL,
    category VARCHAR(100) NULL,
    region VARCHAR(100) NULL,
    address VARCHAR(500) NULL,

    latitude DECIMAL(10,7) NULL,
    longitude DECIMAL(10,7) NULL,

    kakao_place_id VARCHAR(255) NULL,
    tour_content_id VARCHAR(255) NULL,

    phone VARCHAR(100) NULL,
    website VARCHAR(1000) NULL,

    opening_hours JSON NULL,
    closed_days TEXT NULL,
    parking_info TEXT NULL,
    description TEXT NULL,

    verification_status ENUM(
        'VERIFIED','PARTIAL','UNKNOWN'
    ) NOT NULL DEFAULT 'UNKNOWN',

    details_updated_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,

    CONSTRAINT uq_places_kakao
        UNIQUE (kakao_place_id),

    CONSTRAINT uq_places_tour
        UNIQUE (tour_content_id),

    CONSTRAINT chk_places_latitude
        CHECK (
            latitude IS NULL
            OR latitude BETWEEN -90 AND 90
        ),

    CONSTRAINT chk_places_longitude
        CHECK (
            longitude IS NULL
            OR longitude BETWEEN -180 AND 180
        )
) ENGINE=InnoDB;
```

장소 식별 우선순위:
1. Kakao Place ID
2. TourAPI Content ID
3. 이름 + 좌표

`GET /places/search`가 외부 API에서 새 장소를 발견하면,
Backend는 내부 `places`에 먼저 조회/Upsert한 뒤 내부 `place_id`를 반환한다.

`name`에는 UNIQUE를 걸지 않는다.

---

# 20. source_places

YouTube 메타데이터/AI 분석에서 추출된 장소 후보.

```sql
CREATE TABLE source_places (
    source_place_id BIGINT AUTO_INCREMENT PRIMARY KEY,

    source_id BIGINT NOT NULL,
    place_id BIGINT NULL,

    candidate_name VARCHAR(255) NOT NULL,
    rank_no INT UNSIGNED NOT NULL,

    extraction_method ENUM(
        'METADATA_AI','MANUAL'
    ) NOT NULL,

    verification_status ENUM(
        'VERIFIED','PARTIAL','UNKNOWN'
    ) NOT NULL DEFAULT 'UNKNOWN',

    user_confirmed BOOLEAN NOT NULL DEFAULT FALSE,

    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_source_places_source
        FOREIGN KEY (source_id)
        REFERENCES trip_sources(source_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_source_places_place
        FOREIGN KEY (place_id)
        REFERENCES places(place_id)
        ON DELETE SET NULL,

    CONSTRAINT uq_source_places_source_rank
        UNIQUE (source_id, rank_no)
) ENGINE=InnoDB;
```

숫자 confidence는 저장하지 않는다.

---

# 21. travel_plans

MVP에서는 여행당 현재 Plan 1개만 유지하고 Revision으로 버전을 관리한다.

```sql
CREATE TABLE travel_plans (
    plan_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    trip_id BIGINT NOT NULL,

    status ENUM(
        'DRAFT','CONFIRMED','ARCHIVED'
    ) NOT NULL DEFAULT 'DRAFT',

    current_version INT UNSIGNED NOT NULL DEFAULT 1,

    generated_at DATETIME NULL,
    last_validated_at DATETIME NULL,
    confirmed_at DATETIME NULL,

    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,

    CONSTRAINT fk_travel_plans_trip
        FOREIGN KEY (trip_id)
        REFERENCES trips(trip_id)
        ON DELETE CASCADE,

    CONSTRAINT uq_travel_plans_trip
        UNIQUE (trip_id)
) ENGINE=InnoDB;
```

---

# 22. plan_items

```sql
CREATE TABLE plan_items (
    item_id BIGINT AUTO_INCREMENT PRIMARY KEY,

    plan_id BIGINT NOT NULL,
    place_id BIGINT NULL,

    visit_date DATE NOT NULL,
    sequence_no INT UNSIGNED NOT NULL,

    item_type ENUM(
        'PLACE','MEAL','REST','FREE_TIME'
    ) NOT NULL,

    title VARCHAR(255) NOT NULL,

    start_time TIME NULL,
    end_time TIME NULL,

    transport_mode_from_previous ENUM(
        'WALK','PUBLIC_TRANSIT','CAR','TAXI','OTHER'
    ) NULL,

    travel_minutes_from_previous INT UNSIGNED NULL,
    travel_distance_meters_from_previous INT UNSIGNED NULL,

    recommendation_reason TEXT NULL,
    user_note VARCHAR(255) NULL,

    validation_status ENUM(
        'VALID','WARNING','UNKNOWN'
    ) NOT NULL DEFAULT 'UNKNOWN',

    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,

    CONSTRAINT fk_plan_items_plan
        FOREIGN KEY (plan_id)
        REFERENCES travel_plans(plan_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_plan_items_place
        FOREIGN KEY (place_id)
        REFERENCES places(place_id)
        ON DELETE SET NULL,

    CONSTRAINT uq_plan_items_order
        UNIQUE (plan_id, visit_date, sequence_no),

    CONSTRAINT chk_plan_items_time
        CHECK (
            end_time IS NULL
            OR start_time IS NULL
            OR end_time >= start_time
        )
) ENGINE=InnoDB;
```

REST / FREE_TIME은 `place_id = NULL` 가능.

---

# 23. plan_revisions

```sql
CREATE TABLE plan_revisions (
    revision_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    plan_id BIGINT NOT NULL,

    revision_no INT UNSIGNED NOT NULL,

    revision_type ENUM(
        'USER_EDIT',
        'AI_REGENERATE',
        'USER_FATIGUE',
        'WEATHER_CHANGE',
        'OTHER'
    ) NOT NULL,

    instruction TEXT NULL,
    snapshot JSON NOT NULL,

    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_plan_revisions_plan
        FOREIGN KEY (plan_id)
        REFERENCES travel_plans(plan_id)
        ON DELETE CASCADE,

    CONSTRAINT uq_plan_revisions_plan_no
        UNIQUE (plan_id, revision_no)
) ENGINE=InnoDB;
```

JSON은 이력/복구용 snapshot에만 사용.

---

# 24. plan_validation_issues

```sql
CREATE TABLE plan_validation_issues (
    validation_issue_id BIGINT AUTO_INCREMENT PRIMARY KEY,

    plan_id BIGINT NOT NULL,
    item_id BIGINT NULL,

    issue_type ENUM(
        'PLACE_NOT_FOUND',
        'OPENING_HOURS_UNKNOWN',
        'PLACE_CLOSED',
        'TRAVEL_TIME_UNKNOWN',
        'TIME_CONFLICT',
        'WEATHER_WARNING',
        'ACCESSIBILITY_WARNING',
        'OTHER'
    ) NOT NULL,

    severity ENUM(
        'INFO','WARNING','CRITICAL'
    ) NOT NULL,

    message VARCHAR(1000) NOT NULL,

    resolved_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_validation_issues_plan
        FOREIGN KEY (plan_id)
        REFERENCES travel_plans(plan_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_validation_issues_item
        FOREIGN KEY (item_id)
        REFERENCES plan_items(item_id)
        ON DELETE SET NULL
) ENGINE=InnoDB;
```

`resolved_at IS NULL`이면 미해결 상태.

---

# 25. docent_analyses

사진 원본은 DB에 저장하지 않는다.

```sql
CREATE TABLE docent_analyses (
    analysis_id BIGINT AUTO_INCREMENT PRIMARY KEY,

    user_id BIGINT NOT NULL,
    trip_id BIGINT NULL,

    status ENUM(
        'PROCESSING','COMPLETED','FAILED'
    ) NOT NULL DEFAULT 'PROCESSING',

    selected_place_id BIGINT NULL,

    expires_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME NULL,

    CONSTRAINT fk_docent_analyses_user
        FOREIGN KEY (user_id)
        REFERENCES users(user_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_docent_analyses_trip
        FOREIGN KEY (trip_id)
        REFERENCES trips(trip_id)
        ON DELETE SET NULL,

    CONSTRAINT fk_docent_analyses_selected_place
        FOREIGN KEY (selected_place_id)
        REFERENCES places(place_id)
        ON DELETE SET NULL
) ENGINE=InnoDB;
```

---

# 26. docent_candidates

```sql
CREATE TABLE docent_candidates (
    candidate_id BIGINT AUTO_INCREMENT PRIMARY KEY,

    analysis_id BIGINT NOT NULL,
    place_id BIGINT NULL,

    candidate_name VARCHAR(255) NOT NULL,
    candidate_region VARCHAR(100) NULL,

    rank_no INT UNSIGNED NOT NULL,

    verification_status ENUM(
        'VERIFIED','PARTIAL','UNKNOWN'
    ) NOT NULL DEFAULT 'UNKNOWN',

    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_docent_candidates_analysis
        FOREIGN KEY (analysis_id)
        REFERENCES docent_analyses(analysis_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_docent_candidates_place
        FOREIGN KEY (place_id)
        REFERENCES places(place_id)
        ON DELETE SET NULL,

    CONSTRAINT uq_docent_candidates_rank
        UNIQUE (analysis_id, rank_no)
) ENGINE=InnoDB;
```

Gemini의 임의 confidence 확률은 저장하지 않는다.

---

# 27. 주요 흐름

## 로그인

```text
Kakao/Naver
→ user_auths
→ users
→ refresh_tokens
```

## 기본 프로필

```text
users
├── user_preferences
└── user_interests
       └── interest_codes
```

## 동행자

```text
companions
├── companion_preferences
└── companion_interests
       └── interest_codes
```

## 여행

```text
trips
├── trip_preferences
├── trip_companions
├── trip_interests
└── trip_sources
```

## 콘텐츠

```text
trip_sources
→ source_places
→ places
```

## 일정

```text
trip
+ preferences
+ companions
+ interests
+ places
→ EXAONE
→ travel_plans
→ plan_items
→ Validation
→ plan_validation_issues
```

## 재구성

```text
현재 일정
→ plan_revisions snapshot
→ EXAONE / 사용자 수정
→ plan_items 갱신
→ Validation
→ current_version + 1
```

## 스마트 도슨트

```text
사진
→ Gemini
→ docent_analyses
→ docent_candidates
→ Kakao/TourAPI 검증
→ 사용자 선택
→ selected_place_id
→ EXAONE 설명
```

---

# 28. 삭제 정책

| 대상 | API 동작 | DB 처리 |
|---|---|---|
| User | 회원탈퇴 | `status = WITHDRAWN` |
| Companion | DELETE | `status = ARCHIVED` |
| Trip | DELETE | `status = ARCHIVED` |
| Trip Source | DELETE | `is_active = FALSE` |
| Plan Item | 일정에서 삭제 | 실제 삭제 가능 + Revision 저장 |
| Refresh Token | 로그아웃 | `revoked_at` 기록 |
| Docent Image | 분석 | 영구 저장하지 않음 |

---

# 29. API ↔ DB 매핑

| API 영역 | DB |
|---|---|
| Auth | users, user_auths, refresh_tokens |
| User | users, user_preferences, user_interests |
| Companion | companions, companion_preferences, companion_interests |
| Trip | trips, trip_preferences, trip_companions, trip_interests |
| YouTube | trip_sources, source_places |
| Place | places |
| Plan | travel_plans, plan_items, plan_revisions, plan_validation_issues |
| Smart Docent | docent_analyses, docent_candidates, places |

---

# 30. 전체 검토 후 수정 사항

## 제거한 테이블

### `trip_source_tags`
YouTube tag는 검색 핵심 관계 데이터가 아니므로 `trip_sources.tags JSON`으로 흡수.

### `place_details`
`places`와 1:1이고 MVP에서 분리 이점이 작아 `places`에 통합.

## 추가/유지한 테이블

### `trip_interests`
YouTube/사용자/프로필 기반으로 이번 여행에 실제 적용할 관심사를 저장하기 위해 필요.

### `plan_validation_issues`
일정 검증이 주요 기능이므로 검증 결과를 지속적으로 관리하기 위해 유지.

### `source_places`
콘텐츠에서 발견한 장소 후보의 출처와 사용자 확인 여부를 추적하기 위해 유지.

### `docent_analyses`, `docent_candidates`
스마트 도슨트의 `identify → 사용자 선택 → explain` 흐름을 위해 필요.

## 구조 변경

- 여행당 `travel_plans`는 MVP에서 1개
- 버전은 `plan_revisions`로 관리
- Validation 해결 여부는 Boolean이 아니라 `resolved_at`
- 동행자 여행 당시 조건은 snapshot 저장
- YouTube tags는 JSON
- 장소 상세정보는 `places`로 통합
- AI 관심사 코드는 `interest_codes`에 존재하는 코드만 저장
- Gemini 장소 추정에 숫자 confidence 저장 금지

---

# 31. oauth_login_states

```sql
CREATE TABLE oauth_login_states (
    oauth_login_state_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    provider ENUM('NAVER') NOT NULL,
    state_hash VARCHAR(255) NOT NULL,
    expires_at DATETIME NOT NULL,
    consumed_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_oauth_login_states_hash UNIQUE (state_hash)
) ENGINE=InnoDB;
```

OAuth authorization-code 흐름의 state는 hash와 짧은 만료 시간으로만 저장하며 한 번 소비하면 재사용하지 않는다.

---

# 32. 인덱스 정책

초기에는 다음만 기본 적용한다.

- PRIMARY KEY
- UNIQUE
- FOREIGN KEY 관련 인덱스

실제 조회 패턴을 확인한 뒤 다음 복합 인덱스를 검토한다.

```text
trips(user_id, status, start_date)
companions(user_id, status)
trip_sources(trip_id, is_active)
plan_validation_issues(plan_id, resolved_at)
docent_analyses(user_id, created_at)
```

선택도가 낮은 `status` 단독 인덱스는 초기부터 강제하지 않는다.

---

# 33. Codex 고정 규칙

1. MySQL 8.x / InnoDB / utf8mb4 사용
2. 복수형 snake_case 사용
3. 로그인 사용자는 JWT로 식별
4. Request Body의 user_id로 사용자를 판단하지 않음
5. Kakao/Naver는 `provider + provider_user_id`로 식별
6. Provider Access Token 장기 저장 금지
7. Refresh Token은 hash 저장
8. nickname은 소셜 최초 로그인 직후 NULL 허용, 프로필 완료 시 필수이며 중복 허용
9. 관심사 코드는 `interest_codes` 기준
10. AI가 임의 interest code를 저장하면 안 됨
11. 사용자 기본 성향과 여행별 성향 분리
12. 동행자 기본 프로필과 여행 snapshot 분리
13. tags는 JSON
14. 별도 `place_details` 생성 금지
15. 장소명 UNIQUE 금지
16. 여행당 현재 Plan은 1개
17. 일정 수정 전 Revision snapshot 저장
18. 일정 생성/수정/재구성 후 Validation 실행
19. Validation 해결 여부는 `resolved_at`
20. Gemini confidence 확률 저장 금지
21. 스마트 도슨트 이미지 원본 DB 저장 금지
22. Companion/Trip 삭제는 Soft Delete
23. Trip Source 삭제는 `is_active = FALSE`
24. 외부 API 실패 시 AI 추측값으로 채우지 않음
25. FK / UNIQUE / CHECK 제약을 임의 제거하지 않음

