# 서비스 서버 C

설명과 결과는 한국어, 코드 식별자는 영어로 작성한다.
공통 작업공간에서는 루트 AGENTS.md와 docs/PROJECT_CONTEXT.md, MVP_IMPLEMENTATION_PLAN.md,
MVP_API_CONTRACT.md, MVP_DB_SCHEMA.md, ERD.md 및 관련 PDF를 먼저 확인한다.
루트 docs는 독립 저장소의 추적 범위 밖에 유지한다. 단독 실행 절차는 README.md를 따른다.

현재는 실행 환경과 상태 API만 구현되어 있다. 앱은 C만 호출하고 통화 실행은 T가 담당한다.
업무 구현 시 SQLAlchemy·Alembic을 C에서 단일 관리하며 공유 DB라고 T가 C 데이터를 수정하지 않는다.
실명 인증·본인/모임장 권한·정원·마감·동시성·동의·멱등성을 서버에서 검증한다.
실제 인증·통화·모델 호출은 허용된 대상과 범위에서만 수행하며 기본 테스트는 fake/mock을 사용한다.
.env와 비밀번호·실제 전화번호·통화 원문을 커밋하거나 로그에 출력하지 않는다. DB volume을 보존한다.
개발 컨테이너에서 ruff check ., ruff format --check ., pytest를 실행하고 실제 결과만 보고한다.
작업마다 Issue를 확인/생성하며 type(scope): 한국어 요약과 Refs/Closes footer를 사용한다.
