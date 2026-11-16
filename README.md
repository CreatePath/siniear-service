# 신이어 서비스 서버

C 서비스 서버의 initial commit이다. FastAPI 실행 환경과 상태 확인 API만 포함한다.
회원·모임·일정·신청·정책은 C, 통화 실행·원문·요약·검색은 T의 책임이다.

## 실행

Python 3.12, uv 0.13.8, Docker Desktop Linux 엔진을 사용한다.
siniear-service와 siniear-call을 같은 부모 폴더에 두고 이 저장소에서 실행한다.
최초 한 번 .env.example을 .env로 복사해 DB_PASSWORD를 설정한다. 기존 .env는 덮어쓰지 않는다.
Compose는 이 저장소의 .env만 읽는다. 비밀 값은 커밋하지 않는다.

```powershell
docker compose up --build --detach --wait --wait-timeout 120
docker compose exec service ruff check .
docker compose exec service ruff format --check .
docker compose exec service pytest
docker compose exec call pytest
```

C는 127.0.0.1:8000, T는 127.0.0.1:8001, PostgreSQL 17은 127.0.0.1:5432다.
Swagger는 /api/docs, 라이브니스는 /api/health, DB 준비 상태는 /api/health/ready다.
DB 오류·시간 초과에 readiness는 내부 정보를 숨기고 503을 반환하며 liveness는 200을 유지한다.
DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD와 SERVICE_PORT/CALL_PORT는 .env.example을 따른다.
stop/start/down은 DB volume을 보존한다. down --volumes는 일반 재시작에 사용하지 않는다.
runtime 이미지는 비루트 사용자이며 개발 도구·reload는 development 이미지에만 있다.

호스트에서는 uv sync --locked 후 uv run --locked ruff check ., uv run --locked ruff format --check .,
uv run --locked pytest를 사용한다. 의존성을 바꾸면 pyproject.toml과 uv.lock을 함께 갱신한다.
GitHub Actions도 같은 검사를 실행한다. 업무 ORM·마이그레이션·로그인·통화 연동·배포는 후속 구현이다.

## 작업 규칙

커밋은 type(scope): 한국어 요약, footer는 실제 Issue의 Refs/Closes를 사용한다.
[작업 템플릿](.github/ISSUE_TEMPLATE/task.md)과 [버그 템플릿](.github/ISSUE_TEMPLATE/bug_report.md)을 따른다.
[공통 규칙 Issue](https://github.com/CreatePath/siniear-service/issues/1)에 협업 규칙을 기록했다.
개발 문서·원본 PDF는 공통 작업공간의 루트 docs에 유지하며 이 저장소에는 포함하지 않는다.
서버 지침은 [AGENTS.md](AGENTS.md)를 따른다.
