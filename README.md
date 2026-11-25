# 신이어 서비스 서버

은퇴 직후 65세 이상 남성의 모임 참여, 프로필과 명함 교환을 지원하는 앱의 백엔드다. 현재 체크아웃은 카카오 로그인, 비공개 프로필·사진, 앱 인터뷰, 개인 명함과 기존 모임·일정·신청·게시글·댓글을 제공한다. 모임 가입·소속 명함·명함 교환은 [목표 명세](../docs/MVP_API_CONTRACT.md)의 다음 단계다.

## 로컬 실행

이 폴더에서 Python 3.12·uv 0.13.8 기반 개발 이미지를 사용한다. 최초 설정 시 `.env.example`을 참고해 `.env`에 `DB_PASSWORD`를 지정한다. Compose는 이 폴더의 `.env`를 읽는다. 기존 파일과 PostgreSQL volume을 보존한다.

**기존 DB 전환 시 주의.** 아래의 `alembic upgrade head`는 `1a65f02ce93b`에서 비상연락처·통화 원문·발신 작업·전화번호와 동의 값을 삭제한다. 기존 설치는 먼저 통화 컨테이너, 작업자, 공급자 웹훅과 구 서비스의 쓰기를 중단하고 대기 작업·보관 방침·복구용 백업을 확인한다. Compose 정의를 바꿔도 이미 실행 중인 구 컨테이너는 남을 수 있다. 구버전 복구에는 전환 전 백업과 해당 서버 버전이 필요하다. 회원·모임·일정 신청과 변경 이력은 유지한다.

```powershell
docker compose up --build --detach --wait --wait-timeout 120 service
docker compose exec service alembic upgrade head
docker compose ps
```

`service`를 지정하면 의존 서비스 `db`도 시작한다. 기본 주소는 `http://127.0.0.1:8000/api/docs`, 실제 계약은 `/api/openapi.json`, 준비 상태는 `/api/health/ready`다. 위 마이그레이션은 현재 코드의 리비전까지 적용한다. 로컬 합성 계정은 `docker compose exec service python -m scripts.seed_dev`, 개발 인증은 개발 환경의 `DEV_AUTH_ENABLED`를 사용한다. 카카오 앱 연동에는 `KAKAO_APP_ID`와 `KAKAO_ADMIN_KEY` 설정이 필요하다.

## 개발 계정으로 개인 명함 만들기

1. 등록된 합성 회원으로 `POST /api/interviews`를 호출한다. 시작·답변·확정 요청마다 작업별 `Idempotency-Key`를 지정하고 같은 요청을 재시도할 때 키를 유지한다.
2. 응답의 `next_question.text`를 표시하고 `next_question.key`와 `version`으로 `POST /api/interviews/{interview_id}/answers`에 답변 또는 `skip: true`를 보낸다. 서버가 여섯 주 질문을 정해진 순서와 문구로 제시한다. Gemini는 앞선 답까지 보아도 현재 주제의 프로필을 사실대로 한 줄 적기 어려울 때 보충 질문을 한다. 기준과 예시는 [꼬리 질문 시스템 프롬프트](app/integrations/interview_model.py)의 `FOLLOW_UP_SYSTEM_PROMPT`에 있다. 보충은 주제당 최대 두 번이며 건너뛰면 다음 주제로 넘어간다. 기본 fake에서는 다섯 글자 미만의 답으로 두 차례 보충을 시연할 수 있다. 앱을 다시 열면 보관한 인터뷰 ID로 현재 질문이나 비공개 초안을 조회한다.
3. `ready` 상태에서 사용자가 고친 `profile`, 템플릿, 공개 항목, 인터뷰·프로필·카드 버전을 같은 본문으로 `/preview`와 `/confirm`에 차례로 보낸다. 최초 확정은 `card_version: null`이다. 새 초안 생성 기준은 [요약 시스템 프롬프트](app/integrations/interview_model.py)의 `SUMMARY_SYSTEM_PROMPT`에 있다. 미리보기는 상태를 변경하지 않는다.
4. `GET /api/me/cards`로 결과를 조회한다. 프로필·명함 수정 시 최근 버전을 따옴표로 감싼 `If-Match`를 보낸다.

기본 `INTERVIEW_PROVIDER=fake`는 오프라인 시연용이다. 실제 모델은 서비스 환경에 `INTERVIEW_PROVIDER=gemini`, `GEMINI_INTERVIEW_MODEL`, `GEMINI_API_KEY`를 지정해야 호출한다. 개발 기본 키는 캐릭터 `default`·`leaf`, 개인 명함 템플릿 `default`·`classic`이다. 사진의 시연용 입력 한도는 JPEG/PNG 5 MiB, 1,200만 픽셀이다. 서버는 메타데이터를 제거하고 긴 변을 최대 2,048픽셀로 줄인 JPEG를 PostgreSQL에 보관한다. 사용자 탈퇴 시 업로드한 미연결 사진도 지운다.

## 검증

```powershell
docker compose exec service ruff check .
docker compose exec service ruff format --check .
docker compose exec -e RUN_DB_TESTS=1 service pytest
```

DB 테스트는 격리 환경에서 실행한다. 명령·환경 변수·seed·기존 라우트의 상세 기록은 [이전 구현 README](README.legacy.md)에 보존했다. [개발 지침](AGENTS.md), [새 기획과 우선순위](../docs/PROJECT_CONTEXT.md), [구조와 전환 차이](../docs/PROJECT_STRUCTURE.md), [커밋 규칙](../docs/COMMIT_CONVENTION.md)을 함께 확인한다.
