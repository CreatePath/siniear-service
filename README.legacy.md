# 신이어 서비스 서버

> 2026-11-24 이전 구현·실행 기록. 현재 개발 기준은 [README](README.md)와 [작업 지침](AGENTS.md)에 있다.

C는 회원·모임·일정·참가 신청·정책을, T(`siniear-call`)는 통화 실행·원문·요약·검색을 담당한다.
상태 확인·Group/Meeting C01–C14·커뮤니티 D01–D09·통화 예약/기록 B01–B06·내부 F01–F09를 구현했다.
개발용 인증·합성 seed·SQLAlchemy·Alembic을 사용한다. 카카오 로그인·회원 프로필·연락처·탈퇴 API를 제공한다. 실명·나이 인증은 보류한다.

## 작업 기록과 커밋

작업마다 관련 GitHub Issue를 확인하고 없으면 생성한다. [작업 템플릿](.github/ISSUE_TEMPLATE/task.md)과
[버그 템플릿](.github/ISSUE_TEMPLATE/bug_report.md)에 배경·범위·완료 조건을 적고, 완료 시 검증 결과를 남긴다.
커밋은 `[#번호] type(scope): 한국어 요약` 형식으로 작성하며 scope는 선택, 제목은 72자 이내를 권장한다.
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
| unverified | `6b89f613-b34a-5e06-ae76-36c7295339a6` | `8b64fdaf-aef3-5a4f-b4c1-593a9cc5600f` | 실명 인증 이력 없이 이용 |
| no_consent | `7662ff21-d9dd-596e-9860-0b77ff09ec6d` | `ad3e8f95-eb38-5873-8ba3-82aa2dd8242f` | 전화 동의 없음; 모임 활동 가능 |

owner는 전역 관리자가 아니다. 인증된 회원 누구나 개설하며 본인이 개설한 대상만 관리한다.
실명 인증 이력과 무관하게 프로필 등록 후 모임을 이용한다. 통화에는 `call_agree=true`가 필요하다.

## 카카오 로그인과 회원 API

C 환경의 `KAKAO_APP_ID`에 카카오 개발자 콘솔의 숫자 앱 ID, `KAKAO_ADMIN_KEY`에 같은 앱의 서버 전용 어드민 키를 설정한다. 기본 앱 ID 0은 로그인을 비활성화한다. 공유 DB는 C 컨테이너에서 `alembic upgrade head`로 갱신한 뒤 두 서버를 실행한다.

1. 앱의 카카오 SDK 액세스 토큰을 `POST /api/auth/kakao`의 JSON `access_token`으로 전달한다. 응답은 신이어 `access_token`, `refresh_token`, `expires_in`(초), `user_id`, `verification_status`다.
2. 이후에는 신이어 access 토큰으로 `GET /api/users/me`를 호출한다. `senior_id`가 null이면 `POST /api/seniors`에 표시 이름 `name`, E.164 `phone_number`, `region_code`, `call_agree`와 선택 필드 `interests`를 보낸다.
3. 본인 프로필은 `GET/PATCH /api/seniors/{senior_id}`로 조회·수정한다. 같은 경로 아래 `/care-contacts`는 목록·생성, `/care-contacts/{contact_id}`는 수정·삭제를 지원한다.
4. access는 최대 15분, refresh는 로그인 시점부터 30일이다. `POST /api/auth/refresh`에 `refresh_token`을 전달하면 토큰 쌍이 교체된다. `POST /api/auth/logout`에는 같은 세션의 Bearer access와 refresh 본문을 보낸다.
5. `DELETE /api/users/me`는 로그인한 회원의 모든 세션과 전화 데이터를 지우고 카카오 연결을 해제한다. 공급자 장애 시 503이며 같은 세션으로 재시도할 수 있다. 개설한 그룹을 닫고 미완료 일정을 취소하며 공동 활동 이력의 프로필에는 ‘탈퇴 회원’을 표시한다.

## 구현 API와 계약

모임·커뮤니티 경로는 `/api` 접두사와 프로필 등록 회원의 Bearer 토큰을 사용한다. 상세 입력·응답·오류 코드는 Swagger를 따른다.

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
| 그룹 게시글 목록·작성 | GET / POST `/groups/{group_id}/posts` |
| 게시글 상세·수정·삭제 | GET / PATCH / DELETE `/posts/{post_id}` |
| 댓글 목록·작성 | GET / POST `/posts/{post_id}/comments` |
| 댓글 수정·삭제 | PATCH / DELETE `/comments/{comment_id}` |

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

게시글 생성은 `{"title":"산책 후기","content":"함께 걸어서 즐거웠습니다."}`,
댓글 생성·수정은 `{"content":"다음에도 함께해요."}`다. 작성자 ID는 인증 문맥에서 정한다.
게시글 수정은 title/content 중 하나 이상을 받는다. 제목 1–100자·본문 1–5,000자·댓글 1–1,000자이며
앞뒤 공백 제거 후 검증한다. 공백만 입력·null·빈 PATCH·미정의 필드는 422다.
본인만 수정할 수 있고 작성자 또는 해당 그룹장만 삭제할 수 있다. 게시글 작성자는 타인의 댓글 삭제 권한을 얻지 않는다.
게시글은 소프트 삭제하고 댓글은 실제 삭제한다. 삭제된 글의 상세·수정·재삭제와 모든 댓글 접근은 404다.
게시글 최신순·댓글 생성순에 UUID로 동률을 구분하며, 커서는 해당 그룹/게시글에서만 재사용한다.
표시 이름은 현재 프로필에서, 댓글 수는 남아 있는 댓글에서 계산한다. 전화 동의는 요구하지 않는다.
그룹 중단에 대한 별도 게시판 제한은 명세에 없어 추가하지 않았다. 변경 시 계약과 테스트를 함께 수정한다.

취소는 신청·버전·이력과 `cancellation_notices`의 수신자별 전달 대기를 함께 저장한다.
취소 직전 참가자용 알림과 개설자의 직접 전화 안내를 중복 없이 남긴다. **전달 대기 저장은 발송 완료가 아니다.**
알림 API·발송·실패 재시도는 P9에서 연결한다. 통화 중 신청·동의 검증과 calls/원문 복합 FK는 이번에 연결했다.

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
docker compose exec -e RUN_DB_TESTS=1 call pytest
```

업무 테스트는 PostgreSQL에 매 테스트마다 임의 `test_<UUID>` 스키마를 만들고 마이그레이션을 적용한 뒤 제거한다.
기존 개발 데이터는 삭제하지 않는다. 테스트 DB 계정에는 스키마 생성 권한이 필요하다.
`RUN_DB_TESTS=1`이 없으면 업무 DB 테스트는 skip하므로 전체 검증으로 보고하면 안 된다.
GitHub Actions는 별도 PostgreSQL 17을 실행하고 해당 변수를 켠다. 원격 CI는 push 후 별도 확인한다.

호스트에서는 `python -m uv sync --locked` 후 `python -m uv run --locked ruff check .`,
`python -m uv run --locked ruff format --check .`를 사용한다.
PostgreSQL 실행 상태에서 `$env:RUN_DB_TESTS='1'`을 설정하고 `python -m uv run --locked pytest`로 전체 테스트한다.

2026-11-16 커뮤니티 추가 후 컨테이너 검증: C 53개·T 5개 통과, 양쪽 Ruff 통과.
Alembic `7ac4d29b10ef`를 로컬 DB에 적용했고 ORM 정합성 검사도 통과했다. 업무 테이블 9개·운영 테이블 2개다.
커뮤니티 신규 테스트 18개는 CRUD·권한·입력·커서·삭제 노출 차단·실제 PostgreSQL 잠금 경합을 포함한다.
빈 격리 스키마에서 전체 upgrade·downgrade/upgrade도 검증했다. 기존 개발 데이터는 보존한다.
실제 인증·전화·모델 호출·알림 전달·운영 배포·원격 CI는 검증하지 않았다.

## 코드와 문서 위치

`app/db/models`는 C의 공유 매핑, `migrations`는 공유 DDL 이력이다.
`modules/auth`는 인증 경계, `modules/groups`·`modules/meetings`는 API·업무·조회·신청·취소다.
`modules/community`는 게시글·댓글 API·권한·조회다. 모든 댓글 변경과 게시글 변경은 부모 게시글을 먼저 잠근다.
service가 트랜잭션을 소유하고 그룹→일정 순서로 잠근다. 멱등 요청은 DB advisory lock으로 직렬화한다.
`scripts/seed_dev.py`는 개발 계정, `app/workers/meeting_status.py`는 명시적인 상태 갱신 진입점이다.
T는 이 저장소를 import하거나 모임 데이터를 직접 변경하지 않는다. T 업무 API·DB 매핑은 아직 없다.

공통 [지침](../AGENTS.md), 서버 [지침](AGENTS.md),
[세부 구현·검증 기록](../docs/archive/2026-11-23/implementation-plan/GROUP_MEETING_IMPLEMENTATION.md),
[커뮤니티 구현·검증 기록](../docs/archive/2026-11-23/implementation-plan/COMMUNITY_IMPLEMENTATION.md),
[API 계약](../docs/archive/2026-11-23/MVP_API_CONTRACT.md), [DB 정의](../docs/archive/2026-11-23/DB/MVP_DB_SCHEMA.md)를 함께 확인한다.
개발 문서·원본 PDF는 루트 docs에 유지하며 두 서버 저장소의 Git 추적 범위 밖이다.

## 통화 기능 — 2026-11-16 추가

[C #5](https://github.com/CreatePath/siniear-service/issues/5), [T #2](https://github.com/CreatePath/siniear-call/issues/2).
공유 마이그레이션 c6a929f2dc12를 로컬 DB에 적용했다. 업무 테이블 총 16개, 운영 테이블 총 6개다.
신청/작업의 통화 FK를 연결했다. 전화 신청 이력이 있는 DB의 downgrade는 기존 제약 복원 단계에서 거부되므로 운영 롤백 절차로 사용하지 않는다.

| 기능 | 경로 (/api 접두사) |
| --- | --- |
| 본인 예약 목록·생성 | GET / POST /seniors/{senior_id}/call-schedules |
| 본인 예약 수정·삭제 | PATCH / DELETE /seniors/{senior_id}/call-schedules/{schedule_id} |
| 본인 통화 목록·요약 상세 | GET /seniors/{senior_id}/calls[/{call_id}] |
| 내부 모임 도구·상태 이벤트·비상연락 조회·관심사 | F01–F09, Swagger 및 루트 API 계약 참조 |

예약은 Asia/Seoul, MON–SUN, HH:mm를 사용한다. 미응답 종료 3분 후 같은 회차에서 최초 포함 최대 3회다.
세 번 모두 no_answer이면 등록 순서대로 비상연락을 전체 최대 3회 실행한다. 기술 실패와 중복 이벤트는 집계에서 제외한다.
안부전화와 비상전화는 회원별로 순차 실행한다. 회원 NO KEY UPDATE 잠금은 정책을 직렬화하면서 FK 참조 검사를 허용한다.
회차·queued Call·전송 대기를 함께 저장하고, C는 T의 durable 이벤트 근거를 확인하며 T 소유 상태를 덮어쓰지 않는다.
통화 중 신청/취소는 저장된 안내·명시적 동의·턴 재사용·신청 버전을 검증한다. 취소는 본인 신청만 허용한다.
통화 목록은 시작 시각(없으면 예약 시각)과 UUID 내림차순이다. duration_seconds는 answered_at부터 ended_at까지이며 수신 근거가 없으면 null이다.

Compose의 C_TO_T_TOKEN/T_TO_C_TOKEN을 방향별로 설정한다. 빈 토큰은 내부 API를 거부한다.
단독 C 실행은 INTERNAL_INBOUND_TOKEN/OUTBOUND_TOKEN, INTERNAL_SCOPES, PEER_BASE_URL을 사용한다.
설정 예시는 .env.example, 공급자 설정과 T 실행 방법은 [T README](../siniear-call/README.legacy.md)를 따른다.
작업자는 한 번 실행한 뒤 종료하며 API 시작 시 자동 실행하지 않는다. 주기 실행은 배포 단계에서 연결한다.

```powershell
docker compose exec service python -m app.workers.calls
docker compose exec call python -m app.workers.calls
```

기본 CALL_PROVIDER=disabled이며 이번 검증은 fake만 사용했다. 실제 전화·유료 모델 호출은 수행하지 않았다.
최종 컨테이너 테스트 C 68개·T 27개 통과, 양쪽 Ruff 검사·포맷 통과, alembic check 차이 없음.
실제 카카오 앱 연동과 음성·검색 품질, 운영 배포 검증은 남아 있다.
[통화 구현·검증 기록](../docs/archive/2026-11-23/implementation-plan/CALL_IMPLEMENTATION.md)에 구현 선택과 수정 이력을 정리했다.
## 공유 가상 데이터로 비통화 테스트

`scripts/seed_non_call_demo.py`는 가상 계정 4개, 그룹 2개, 일정 4개, 신청 2개,
게시글·댓글 각각 3개를 추가한다. 모든 계정은 전화 수신에 동의하지 않은 상태다.
기존 `7ac4d29b10ef` DB와 통화 마이그레이션 적용 DB에서 검증했다.
재실행은 이미 만들어진 데이터의 수정·취소·삭제를 덮어쓰지 않는다.

실행에는 `APP_ENV=development|test`, `SEED_NON_CALL_DEMO=1`이 필요하고
`CALL_PROVIDER=disabled`, `ALLOW_PAID_CALLS=false`를 사용한다.
API에서 가상 계정을 사용하려면 C에 별도로 `DEV_AUTH_ENABLED=true`를 설정한다.
가상 토큰은 공개 서비스의 실제 로그인 수단이 아니다.

VM 파일 업로드·기존 runtime 이미지에서 실행·계정별 토큰·테스트 모드 종료 명령은
[비통화 공동 테스트 안내](../docs/archive/2026-11-23/NON_CALL_DEMO.md)를 따른다.
관련 검증은 `docker compose exec -e RUN_DB_TESTS=1 service pytest tests/integration/test_non_call_demo.py -q`다.
