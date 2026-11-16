# 신이어 서비스 서버

C는 회원·모임·일정·참가 신청·정책을, T(`siniear-call`)는 통화 실행·원문·요약·검색을 담당한다.
현재 상태 확인 API와 **Group/Meeting 앱 API C01–C14**, 개발용 인증 경계, 합성 계정 seed,
SQLAlchemy 모델·Alembic 마이그레이션을 구현했다. 실제 로그인·실명 인증·통화 도구·알림 발송은 후속 작업이다.

## 작업 기록과 커밋

작업마다 관련 GitHub Issue를 확인하고 없으면 생성한다. [작업 템플릿](.github/ISSUE_TEMPLATE/task.md)과
[버그 템플릿](.github/ISSUE_TEMPLATE/bug_report.md)에 배경·범위·완료 조건을 적고, 완료 시 검증 결과를 남긴다.
커밋은 `type(scope): 한국어 요약` 형식으로 작성하며 scope는 선택, 제목은 72자 이내를 권장한다.
유형은 `feat`, `refactor`, `fix`, `docs`, `rm`, `test`, `chore`, `revert`를 사용하고,
footer에 `Refs: #번호`를 기록한다. 다른 저장소의 Issue는 전체 URL로 연결한다.
호환성을 깨는 변경에는 `!`와 `BREAKING CHANGE:`를 함께 쓴다.
공통 작업공간의 상세 규칙은 루트 `docs/COMMIT_CONVENTION.md`에 있다. 이 파일은 이 저장소에 포함되지 않는다.
[규칙 확정 및 템플릿 도입 기록](https://github.com/CreatePath/siniear-service/issues/1)을 참고한다.

## 개발 환경 실행

Python 3.12, uv 0.13.8, Docker Desktop Linux 엔진과 Compose를 사용한다.
두 저장소를 같은 부모 폴더 아래에 둔다. 아래 명령은 `siniear-service`에서 실행한다.
최초 한 번 `.env.example`을 `.env`로 복사하고 `DB_PASSWORD`를 설정한다. 기존 `.env`는 덮어쓰지 않는다.
Compose는 서비스 저장소의 `.env`만 사용하며 통화 저장소의 `.env`는 별도 실행용이다.

```powershell
docker compose up --build --detach --wait --wait-timeout 120
docker compose exec service alembic upgrade head
docker compose exec service python -m scripts.seed_dev
docker compose ps
```

마이그레이션은 C에서만 실행한다. 앱 시작 시 자동 DDL·seed는 실행하지 않는다.
seed는 가상 계정 5개만 추가하며 반복 실행해도 중복하지 않고 기존 프로필·동의를 덮어쓰지 않는다.
가상 번호는 합성 데이터이며 실제 발신에 사용하지 않는다. 그룹·일정은 API로 생성한다.

| 대상 | 주소 |
| --- | --- |
| C Swagger / OpenAPI | http://localhost:8000/api/docs / http://localhost:8000/api/openapi.json |
| T Swagger | http://localhost:8001/api/docs |
| 라이브니스 / DB 준비 상태 | 각 서버의 `/api/health` / `/api/health/ready` |
| PostgreSQL | `127.0.0.1:5432` |

포트는 127.0.0.1에만 공개한다. Compose 내부는 `service:8000`, `call:8000`, `db:5432`다.
`docker compose stop`, `start`, `down`은 사용할 수 있으며 DB는 named volume에 보존한다.
**`down --volumes`는 데이터를 삭제하므로 재시작 절차로 사용하지 않는다.**
준비 상태 API는 DB 연결만 검사한다. 업무 스키마는 `alembic current`/`alembic check`로 확인한다.

## 가상 계정으로 수동 테스트

개발용 인증은 기본 비활성이다. 이 PowerShell 세션에서만 활성화하여 C를 재생성할 수 있다.

```powershell
$env:DEV_AUTH_ENABLED = 'true'
docker compose up --detach --wait service
```

Swagger Authorize에 `dev:<user_id>`를 입력한다. HTTP 헤더는 `Authorization: Bearer dev:<user_id>`다.
`senior_id`가 아닌 **user_id**를 인증에 사용한다. 실제 로그인 토큰이 아닌 개발 전용 계정 선택 기능이다.
비활성화하려면 환경 값을 `false`로 바꾸고 같은 Compose 명령을 실행한다.

| 계정 | user_id | senior_id | 용도 |
| --- | --- | --- | --- |
| owner | `4effa9a3-d59e-59a9-b4e1-ca113cf1751c` | `5e19343c-553c-5101-a3fc-0c810bc26b3b` | 기본 개설자 |
| member | `f74b9b33-71d5-5b50-813b-4fa8475dbdfc` | `f2d59249-e7f9-55af-b752-f8ac1dfad245` | 참가자 |
| other | `1b1020e0-ab08-5b1c-a39a-5fae1c4e515a` | `bcc39c21-5357-5ec2-897b-f7a90bf45192` | 타인 권한·정원 경쟁 |
| unverified | `6b89f613-b34a-5e06-ae76-36c7295339a6` | `8b64fdaf-aef3-5a4f-b4c1-593a9cc5600f` | 실명 미완료 403 |
| no_consent | `7662ff21-d9dd-596e-9860-0b77ff09ec6d` | `ad3e8f95-eb38-5873-8ba3-82aa2dd8242f` | 전화 동의 없음; 모임 활동 가능 |

owner는 전역 관리자가 아니다. 인증된 회원 누구나 개설하며 본인이 개설한 대상만 관리한다.
인증 성공은 `identity_verifications`에서 계산하며 나중의 실패 이력이 이전 성공을 취소하지 않는다.
비상연락처·통화 fixture와 실제 계정 API는 아직 없다.

## 구현 API와 계약

모든 경로는 `/api` 접두사와 실명 인증 주체를 요구한다. 상세 입력·응답·오류 코드는 Swagger를 따른다.

| 기능 | 경로 |
| --- | --- |
| 그룹 생성·검색 | POST / GET `/groups` |
| 그룹 상세·수정·중단 | GET / PATCH `/groups/{group_id}` |
| 그룹 일정 생성 | POST `/groups/{group_id}/meetings` |
| 독립 모임 생성·일정 검색 | POST / GET `/meetings` |
| 일정 상세·수정·취소 | GET / PATCH `/meetings/{meeting_id}` |
| 본인 추천 | GET `/seniors/{senior_id}/meeting-recommendations` |
| 참가 신청·관리자 참가자 목록 | POST / GET `/meetings/{meeting_id}/registrations` |
| 본인 신청과 일정 정보 | GET `/seniors/{senior_id}/registrations` |
| 신청 취소 | DELETE `/meetings/{meeting_id}/registrations/{registration_id}` |

- 소유자는 인증 문맥에서 결정하며 변경할 수 없다. 독립 일정은 group_id 생략/null만 허용한다.
- 시각은 시간대 포함 RFC 3339. 종료>시작, 마감≤시작, 생성/수정 시 미래 시작을 검사한다.
- description은 선택(기본 빈 문자열). 이름/제목 1–100자, 설명 최대 5,000자, 장소 1–500자,
  지역 1–32자, 관심사 최대 20개/각 1–50자, 취소 사유 1–1,000자다. 빈 PATCH·null·미정의 필드는 422다.
- 그룹 중단은 `{"status":"closed"}`. 일정 취소는 `{"status":"canceled","cancel_reason":"사유"}`다.
  취소와 다른 필드 수정은 나누어 요청한다. 그룹 중단·일정 취소는 되돌리지 않는다.
- 시작 전 closed/recruiting 전환 가능. 재모집은 마감도 미래여야 한다. 시작 후 일반 수정·개별 신청 취소는 거부한다.
  관리자 일정 전체 취소는 종료 전까지 가능하다. 종료된 일정·확정 신청 이력은 보존한다.
- 신청 POST는 본문 없이 필수 `Idempotency-Key`를 보낸다. 최초 201, 이미 확정/취소 후 재신청 200.
  동일 회원·신청 작업·키는 커밋된 최초 상태 코드/응답을 재현한다. 동일 키로 다른 일정은 409다.
  실패해 롤백된 요청은 저장하지 않는다. 성공 결과의 자동 만료는 없으며 24시간 정책을 확정한 것은 아니다.
- 취소 DELETE는 `If-Match: "1"`처럼 조회 버전을 큰따옴표로 감싸 보낸다. 성공 204, 버전 불일치 409.
  이미 취소된 현재 버전은 204이고 과거 버전은 409다. 재신청은 같은 ID의 버전을 올리고 최초 출처를 보존한다.
- 목록은 `{items,next_cursor}`, 기본 20/최대 100. 그룹은 생성 내림차순, 일정은 시작 오름차순,
  신청은 ID 오름차순이며 ID로 동률을 구분한다. 커서는 같은 필터·조회 권한 범위에서만 재사용한다.
- 일정 from/to는 시작 시각의 `[from,to)`. group_id 생략 시 그룹·독립 일정 모두 포함한다.
  일반 목록에는 중단·취소 이력도 포함한다. 추천은 같은 지역의 모집 중·미래·자리 있음·미신청 일정만 대상으로,
  그룹 관심사 일치 수 내림차순 후 시작순이다. 독립 모임도 포함한다. 추천 기본 3/최대 10.

취소는 신청·버전·이력과 `cancellation_notices`의 수신자별 전달 대기를 함께 저장한다.
취소 직전 참가자용 알림과 개설자의 직접 전화 안내를 중복 없이 남긴다. **전달 대기 저장은 발송 완료가 아니다.**
알림 API·발송·실패 재시도는 P9, 통화 중 신청·동의 검증은 P6에서 연결한다.
통화 FK 연결 전까지 신청/작업의 call_id·confirmation_turn_id는 DB CHECK로 NULL만 허용한다.

마감·종료 상태는 읽을 때도 시각으로 계산하여 작업 지연 중 신청을 허용하지 않는다.
저장 상태 갱신은 아래 명령으로 실행하며 API 시작 시 자동 실행하지 않는다. 주기 실행은 배포 시 연결한다.

```powershell
docker compose exec service python -m app.workers.meeting_status
```

## 환경 변수·의존성

| 변수 | 용도 |
| --- | --- |
| DB_HOST / DB_PORT | 호스트 기본 127.0.0.1:5432, Compose 내부 db:5432 |
| DB_NAME / DB_USER | 기본 siniear |
| DB_PASSWORD | 필수 비밀 값. .env 보관, 로그 출력 금지 |
| SERVICE_PORT / CALL_PORT | 호스트 포트 기본 8000 / 8001 |
| APP_ENV | 기본 production. development/test/production. Compose C는 development |
| DEV_AUTH_ENABLED | 기본 false. true는 development/test에서만 허용, production에서는 시작 거부 |

FastAPI/Uvicorn, Psycopg 3, SQLAlchemy 2.1.8, Alembic 1.20.1을 사용한다. 정확한 버전은 `uv.lock`을 따른다.
의존성 변경은 `uv add` 또는 pyproject.toml 수정 후 `uv lock`; 두 파일을 함께 관리한다.
이미지는 `uv sync --locked`로 빌드하고 비루트 사용자로 실행한다. runtime에는 개발 도구·seed·reload가 없다.
runtime 빌드 확인 명령은 `docker build --target runtime -t siniear-service:runtime-check .`다.
공유 로컬 DB 계정은 개발용이며 운영 계정 분리·GCP·Cloud SQL 배포는 아직 구성하지 않았다.

## 검증

```powershell
docker compose exec service ruff check .
docker compose exec service ruff format --check .
docker compose exec -e RUN_DB_TESTS=1 service pytest
docker compose exec service alembic check
docker compose exec call ruff check .
docker compose exec call ruff format --check .
docker compose exec call pytest
```

업무 테스트는 PostgreSQL에 매 테스트마다 임의 `test_<UUID>` 스키마를 만들고 마이그레이션을 적용한 뒤 제거한다.
기존 개발 데이터는 삭제하지 않는다. 테스트 DB 계정에는 스키마 생성 권한이 필요하다.
`RUN_DB_TESTS=1`이 없으면 업무 DB 테스트는 skip하므로 전체 검증으로 보고하면 안 된다.
GitHub Actions는 별도 PostgreSQL 17을 실행하고 해당 변수를 켠다. 원격 CI는 push 후 별도 확인한다.

호스트에서는 `python -m uv sync --locked` 후 `python -m uv run --locked ruff check .`,
`python -m uv run --locked ruff format --check .`를 사용한다.
PostgreSQL 실행 상태에서 `$env:RUN_DB_TESTS='1'`을 설정하고 `python -m uv run --locked pytest`로 전체 테스트한다.

Group/Meeting 테스트는 실제 PostgreSQL에서 권한·멱등·버전·취소 롤백·동시성을 검증한다.
업무 테이블 7개·운영 테이블 2개이며 Alembic head는 4095cfc36d7d다.
실제 인증·전화·모델 호출·알림 전달·운영 배포·원격 CI는 검증하지 않았다.

## 코드와 문서 위치

`app/db/models`는 C의 공유 매핑, `migrations`는 공유 DDL 이력이다.
`modules/auth`는 인증 경계, `modules/groups`·`modules/meetings`는 API·업무·조회·신청·취소다.
service가 트랜잭션을 소유하고 그룹→일정 순서로 잠근다. 멱등 요청은 DB advisory lock으로 직렬화한다.
`scripts/seed_dev.py`는 개발 계정, `app/workers/meeting_status.py`는 명시적인 상태 갱신 진입점이다.
T는 이 저장소를 import하거나 모임 데이터를 직접 변경하지 않는다. T 업무 API·DB 매핑은 아직 없다.

공통 [지침](../AGENTS.md), 서버 [지침](AGENTS.md),
[세부 구현·검증 기록](../docs/GROUP_MEETING_IMPLEMENTATION.md),
[API 계약](../docs/MVP_API_CONTRACT.md), [DB 정의](../docs/MVP_DB_SCHEMA.md)를 함께 확인한다.
개발 문서·원본 PDF는 루트 docs에 유지하며 두 서버 저장소의 Git 추적 범위 밖이다.
