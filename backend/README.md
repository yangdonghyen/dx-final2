# Travel AI Backend

여행 AI 서비스의 FastAPI Backend 전용 Repository입니다. 현재 구현 범위는
**Task 01 Skeleton + Task 02의 22개 DB Model / 초기 Alembic Migration**입니다.
Frontend는 별도 Repository에서 개발합니다.

## 환경과 설치

- 검증 환경: Windows / Python **3.14.7**
- FastAPI, Pydantic Settings, SQLAlchemy 2, PyMySQL, Alembic
- 기존 MySQL 8.x / utf8mb4 Database 사용
- 직접 사용하는 패키지 버전은 `requirements.txt`에 고정했습니다.

Repository 루트에서 PowerShell로 실행합니다. 기존 `.venv`가 있으면 유지합니다.

```powershell
# 가상환경이 없을 때만 실행
python -m venv .venv

# pip가 없는 가상환경에서만 실행
.\.venv\Scripts\python.exe -m ensurepip --upgrade

.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 환경변수

DB와 외부 API 설정 없이 health와 Swagger를 실행할 수 있습니다.
`.env`가 필요해지면 기존 파일이 없는 경우에만 복사하고, 실제 값은 사용자가 입력합니다.

```powershell
if (-not (Test-Path -LiteralPath .env)) { Copy-Item -LiteralPath .env.example -Destination .env }
```

- `.env`는 프로젝트 루트에서 읽으며 OS 환경변수가 우선합니다.
- MySQL에는 `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_DATABASE`, `MYSQL_USER`,
  `MYSQL_PASSWORD`가 필요합니다. 기본 포트는 3306입니다.
- MySQL URL은 내부에서 `URL.create()`로 조합하며 외부 `MYSQL_URL` 입력은 받지 않습니다.
- 접속정보가 없거나 일부만 있으면 DB 사용 요청을 차단합니다. 추측한 값으로 접속하지 않습니다.
- `CORS_ALLOWED_ORIGINS`는 쉼표로 구분한 명시적 Origin입니다.
  예: `http://localhost:3000,http://localhost:8080`. 경로와 마지막 `/`는 넣지 않습니다.
  빈 값이면 교차 Origin을 허용하지 않으며 `*`는 모든 환경에서 거부합니다.
- JWT 설정은 읽기만 합니다. 토큰 발급·검증·Refresh Token Hash 함수는
  `NotImplementedError`를 발생시키는 자리이며 실제 인증은 후속 Task입니다.
- 외부 API 설정 항목은 준비되어 있지만 실제 Provider를 호출하지 않습니다.
- 실제 Secret을 코드/문서/Git에 넣지 않습니다. `.env` 및 `.env.*`는 제외하고
  `.env.example`만 추적하도록 `.gitignore`에 설정했습니다.

### Local EXAONE plan generation

After filling the required MySQL and JWT values in the untracked `.env`, use
the installed Ollama model name exactly as follows. `PLACE_PROVIDER=real`
also requires the existing Kakao REST API credential; without it a destination
wide real-place search cannot be verified.

```dotenv
PLAN_PROVIDER=real
PLACE_PROVIDER=real
EXAONE_BASE_URL=http://127.0.0.1:11434
EXAONE_MODEL=hf.co/LGAI-EXAONE/EXAONE-3.5-7.8B-Instruct-GGUF:Q4_K_M
AI_API_TIMEOUT_SECONDS=180
```

`ROUTE_PROVIDER=kakao` is optional but recommended only after its Kakao
credential is configured. When unavailable, route facts remain `UNKNOWN`; the
application does not invent travel times.

## 실행

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Android 실기기에서 같은 PC의 개발 서버를 사용할 때는 loopback 기본값 대신
LAN 인터페이스에 바인딩합니다. PC와 휴대폰은 같은 네트워크에 있어야 하며,
Windows 방화벽에서 Python/8000의 사설 네트워크 인바운드 허용 여부는 사용자가
확인합니다.

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

- Health: http://localhost:8000/api/v1/health → `200 {"status":"ok"}`
- Swagger: http://localhost:8000/docs
- OpenAPI: http://localhost:8000/openapi.json

Health는 애플리케이션 생존 여부만 확인하며 DB/외부 API를 호출하지 않습니다.
아직 Auth/User/Companion/Trip 등의 업무 Endpoint는 등록하지 않았습니다.

공통 오류 형식:

```json
{"error":{"code":"NOT_FOUND","message":"Not Found"}}
```

업무 오류, HTTP 오류, 요청 검증 오류 및 예상하지 못한 서버 오류를 같은 형태로 반환합니다.

## MySQL과 Alembic

MySQL은 사용자가 설치한 서비스/서버를 직접 시작하고, **이미 준비된 Database**의
접속정보를 설정합니다. 이 프로젝트는 MySQL 서비스를 설치·시작하거나 Database/User를
생성·삭제하지 않습니다. OS별 MySQL 서비스명은 사용자 환경에 따라 다릅니다.

SQLAlchemy Engine/Session은 명시적인 DB 사용 시 초기화하며,
애플리케이션 import/startup에서는 연결하지 않습니다. `get_db()`는 오류 시 rollback하고
항상 Session을 닫습니다. commit은 후속 Business Service가 트랜잭션 단위로 결정합니다.
`Base.metadata.create_all()` 등 자동 Table 생성은 사용하지 않습니다.

Task 02에서 도메인별 7개 Model 모듈과 `001_initial_schema` Revision을 추가했습니다.
`app/models/__init__.py`가 22개 Service Table을 Metadata에 등록합니다.
DB 없이 확인 가능한 명령:

```powershell
.\.venv\Scripts\python.exe -m alembic heads
.\.venv\Scripts\python.exe -m alembic history
.\.venv\Scripts\python.exe -m alembic upgrade head --sql
```

heads/history에는 `001_initial_schema`가 표시됩니다.
`--sql`은 SQL 출력만 수행하고 MySQL에 연결하지 않습니다. 초기 SQL에는
Service Table 22개, `alembic_version` 생성과 Revision 기록만 포함됩니다.
Master Data Seed는 포함하지 않습니다.

초기 Migration은 빈 DB와 DDL 권한 확인, 문서 대조, SQL 검토, 테스트 후
기존 MySQL 8.0.26 Database에 적용 완료했습니다. 생성된 Table은 총 23개입니다.
DB/User 생성·삭제나 수동 Table 생성은 수행하지 않았습니다.

후속 Schema 변경 시 Model을 수정하고 사용자가 준비한 개발 DB를 사용합니다.

```powershell
# 후속 Schema 변경용 절차
.\.venv\Scripts\python.exe -m alembic revision --autogenerate -m "describe schema change"
# 생성된 Migration을 검토한 후 적용
.\.venv\Scripts\python.exe -m alembic upgrade head
```

초기 Revision의 `downgrade()`는 삭제 금지 규칙에 따라 명시적으로 차단했습니다.
삭제 없는 성공으로 가장하지 않고 오류를 반환합니다. 복구가 필요하면 별도 계획을 검토해야 합니다.

현재 DB Schema를 다시 읽기 전용으로 검증하려면:

```powershell
.\.venv\Scripts\python.exe -m scripts.verify_db_schema
```

이 명령은 22개 테이블의 컬럼, 타입, 기본값/ON UPDATE, NULL, PK, FK,
UNIQUE, CHECK, ENUM, JSON, ON DELETE, InnoDB/utf8mb4와 Revision을 비교합니다.
Service Row 내용 조회나 DB 변경은 수행하지 않습니다.

## 테스트

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m compileall -q app alembic tests
```

테스트는 사용자 `.env`와 관련 OS 설정을 격리하고 실제 MySQL 연결을 차단합니다.
Health/Swagger/OpenAPI, CORS, 환경변수 우선순위, 공통 오류,
DB 설정 누락/지연 초기화/Session 정리, Security 자리의 차단 동작을 검증합니다.
Alembic Revision 생성과 SQL 출력은 임시 복사본에서만 검증합니다.
추가 테스트는 원본 DB 문서의 전체 컬럼/제약조건과 Model을 대조하고,
Migration이 같은 Schema를 생성하며 삭제 SQL/Seed를 포함하지 않는지 검사합니다.
Task 01의 빈 Metadata/Revision 가정은 Task 02의 22개 Table/초기 Revision으로 갱신했습니다.
pytest는 실제 MySQL을 사용하지 않습니다. 실제 DB 검증은 위 읽기 전용 명령으로 분리했습니다.

Task 02 검증 결과: pytest 90개 통과, 실제 DB의 197개 컬럼, PK 22개, FK 29개,
UNIQUE 18개, CHECK 4개, ENUM 컬럼 32개, JSON 컬럼 4개 일치.

현재 설치 조합의 TestClient에서 httpx 및 AnyIO 관련 의존성 deprecation 경고가
발생할 수 있습니다. 테스트 실패는 아니며 후속 의존성 갱신 때 확인해야 합니다.

## 구조와 문서 읽기 순서

`app/api/v1` → `app/services` → `app/repositories` → MySQL 구조를 사용합니다.
외부 Adapter는 `app/services/external`에, SQLAlchemy Model은 `app/models`에,
Pydantic Schema는 `app/schemas`에 분리합니다. API/Service/Repository 업무 로직은 아직 구현하지 않았습니다.

1. [핵심 기능](docs/01_planning/01_core_features.md)
2. [API 명세](docs/02_api/02_api_spec.md)
3. [DB 명세](docs/03_database/03_db_schema.md)
4. [외부 API](docs/04_external_api/04_external_apis.md)
5. [폴더 구조](docs/05_architecture/05_project_structure.md)
6. [Mock 데이터](docs/06_mock/06_mock_data.md)
7. [구현 계획](docs/07_implementation/07_implementation_plan.md)

## 재점검 중 발견한 문서 차이 및 보류 사항

원본 `docs/`, `mock_data/`, `prompts/` 파일은 변경하지 않았습니다.

- DB 문서 §4에는 Database 생성 SQL이 있지만 Task 01과 구조/구현 문서는 이를 금지합니다.
  사용자 지시대로 생성 SQL을 구현·실행하지 않았습니다.
- Task 01 당시 계정정보가 없어 생략했던 실제 연결/Migration 검증은 Task 02에서 완료했습니다.
- 구현 계획의 JWT Utility 항목과 달리 Task 01은 Security 최소 구조만 요구합니다.
  실제 인증은 구현하지 않았습니다.
- 구조 문서의 평탄한 `docs/` 경로와 `_draft_final` 파일명은 현재 실제 경로와 다릅니다.
  Task 01에서 지정한 실제 문서 경로를 사용했습니다.
- Mock 문서는 JSON 파일 7개가 준비되었다고 적었지만 현재 `mock_data/`는 비어 있습니다.
  Task 01 범위에서 생성하지 않았습니다.
- API 문서의 프로필 수정 응답 예시는 `profile_completed=true`지만 DB 문서는
  preferences와 최소 1개 interest도 완료조건으로 요구합니다. 예시의 사전조건이 명시되지 않아
  후속 Auth/User Task에서 확인이 필요합니다.
- 구현 계획 §13은 Task 02를 User/Auth Model 예시로 설명하지만 전용 Task 02 명세는
  22개 전체 Model을 명시하므로 이번 작업은 전용 명세 범위를 따랐습니다.
- Task 02의 일반적인 BIGINT PK 규칙에는 `interest_codes.interest_code` 예외가 있습니다.
  상세 DB 명세와 Task 02 §10에 따라 VARCHAR(50) PK를 유지했습니다.
- 현재 전달받은 폴더에는 `.git`이 없어 Git 상태/추적 여부는 확인할 수 없습니다.
  임의로 저장소를 초기화하지 않았습니다.

구현 참고: [Pydantic Settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/),
[SQLAlchemy Engine/URL](https://docs.sqlalchemy.org/en/20/core/engines.html),
[Alembic Tutorial](https://alembic.sqlalchemy.org/en/latest/tutorial.html).
