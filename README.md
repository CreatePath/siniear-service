# 신이어 서비스 서버

은퇴 직후 65세 이상 남성의 모임 참여를 지원하는 앱의 백엔드다. 카카오 로그인, 비공개 인터뷰·프로필, 개인·소속 명함과 교환, 받은 명함첩, 모임 추천·가입 심사, 일정 신청, 게시글·일정 댓글과 답글을 제공한다. [앱 API 계약](../docs/MVP_API_CONTRACT.md)

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

기본 `INTERVIEW_PROVIDER=fake`는 오프라인 시연용이다. 실제 모델은 서비스 환경에 `INTERVIEW_PROVIDER=gemini`, `GEMINI_INTERVIEW_MODEL`, `GEMINI_API_KEY`를 지정해야 호출한다. 개발 기본 키는 캐릭터 `default`·`leaf`, 개인 명함 템플릿 `default`·`classic`·`fresh_start`이다. 사진의 시연용 입력 한도는 JPEG/PNG 5 MiB, 1,200만 픽셀이다. 서버는 메타데이터를 제거하고 긴 변을 최대 2,048픽셀로 줄인 JPEG를 PostgreSQL에 보관한다. 사용자 탈퇴 시 업로드한 미연결 사진도 지운다.

## 앱 연동

프로필 생성·수정에는 `nickname`을 사용한다. `name`은 인증된 실명의 조회 전용 필드다. 프로필 삭제는 `DELETE /api/users/me`로 계정 탈퇴와 함께 처리한다. `POST /api/me/cards`로 개인 명함을 직접 만들고 `DELETE /api/cards/{card_id}`에 현재 버전의 `If-Match`를 보내 삭제할 수 있다. 소속 명함은 개설·가입 승인 시 발급되고 모임 탈퇴·종료 시 효력을 잃는다.

모임장 계정과 신청자 계정으로 가입 신청 → 승인 → 내 소속 목록 → 소속 명함을 순서대로 호출한다. 칭호 목록은 해당 가입 기간에 획득한 항목의 id, label, tier를 반환한다. 모임 개설·가입 승인, 소속 일정 신청(서로 다른 일정 1·10·100개), 게시글 작성(10·100개), 소속 명함 교환(서로 다른 카드 쌍 1·10·100개)으로 칭호를 얻는다. 취소·재신청, 글 수정·삭제, 교환 재시도는 누적 달성 횟수를 바꾸지 않는다. 역할·소개·대표 칭호는 명함 PATCH에서 편집한다. 명함에 칭호를 공개하면 `fields.title`과 `fields.title_tier`가 함께 전달된다. 본인 편집 응답에서는 `selected_title_tier`로 선택한 티어를 읽을 수 있다.

교환 제안의 개발 기본 유효시간은 10분이다. 수신자가 미리보기 후 자신의 명함으로 수락하면 양측 명함첩에 반영된다. 미리보기의 사진 URL은 Bearer 인증과 `X-Exchange-Token` 헤더가 필요하다. 교환 후 사진은 Bearer 인증과 현재 교환·공개 상태로 조회한다.

스키마 head는 `aa2611000008`이다. 이 리비전은 기존 일정에 NULL을 허용하는 활동 분류를 추가한다. 보유 칭호의 label은 활동 칭호 기준표의 label을 참조하는 필수 외래키다. 이관 시 기준표에 없는 부여 행이 있으면 PostgreSQL의 외래키 검증이 실패하고 해당 리비전은 롤백된다. `aa2611000005`에서 기존 활동을 이관하고 `aa2611000006`에서 기기와 푸시 대기열을 추가한다. 서비스 쓰기를 중지하고 전환하면 DB에 남은 가입·글·신청 변경 이력·교환을 소급 반영한다. 이미 삭제된 교환은 복구할 수 없다. 기존 칭호 ID와 대표 선택은 보존한다. 이전 코드에서 `name`에 쓴 표시 이름은 `nickname`으로 이관한다. 기존 활성 모임에는 개설자의 가입 기간·소속 명함만 발급한다. 구버전 서버의 쓰기를 중단한 뒤 앱의 닉네임 입력과 서버·스키마를 함께 전환한다.

## 주변 모임 검색

`GET /api/search/meetings`는 시작 전 번개모임, `GET /api/search/groups`는 운영 중인 동호회를 찾는다. `keyword=동작구 그림`은 동작구와 주변 세 곳 안에서 ‘그림’을 찾는다. `category`는 walk(산책), hobby(취미), exercise(운동)이고 전체는 생략한다. 동호회는 interests에 해당 한글 태그를 저장한다. 일정은 생성·수정 시 category로 분류한다. 응답의 regions 첫 항목이 중심이며 total_count는 페이지를 자르기 전 전체 건수다.

시군구 기준표는 `app/modules/search/districts.csv`에 둔다. 2026년 7월 행정안전부 주소기반산업지원서비스의 전국 시군구 경계 256곳에서 산출했다. EPSG:5179 평면 좌표에서 5m 단순화한 경계 사이가 10m 이내이면 접경 후보로 보고, 후보 중 도형 중심점이 가까운 순으로 세 곳을 선택했다. 섬처럼 접경지가 부족한 경우에는 경계 간 거리가 가까운 곳부터 보충한다. 동률이면 중심점 거리, 시군구 코드순이다. 행정구역 개편 시 코드·명칭·인접 세 곳을 함께 갱신하고 `tests/unit/test_search_regions.py`로 참조 무결성과 지역명 해석을 검증한다. [원천 경계와 자료 기준일](https://www.arcgis.com/home/item.html?id=14fb910ff420484c9b794e09b25a3d9d)

## 칭호 기기 푸시

새 칭호가 발급되면 그 시점에 등록된 회원 본인의 기기마다 FCM 발송을 예약한다. 예를 들어 ‘새로운 얼굴’을 획득하면 알림 제목은 “새 칭호를 받았어요”, 본문은 “‘새로운 얼굴’ 칭호를 획득했어요.”이다. 새로 로그인한 기기로 이전 칭호 알림을 일괄 발송하지 않는다.

1. **앱 등록.** Android·iOS 앱을 같은 Firebase 프로젝트에 연결한다. iOS는 Push Notifications capability와 Firebase의 APNs 자격 증명을 설정한다. 앱 첫 실행 시 OS 알림 권한을 요청한다. 로그인 후 FCM 등록 토큰을 받거나 토큰이 갱신되면 현재 세션의 Bearer 인증으로 `PUT /api/me/push-token`에 `{"token": "<FCM 등록 토큰>"}`을 보낸다. 알림을 해제하면 `DELETE /api/me/push-token`을 호출한다. 두 요청 모두 성공하면 204다. 세션 로그아웃·탈퇴 시 서버가 등록과 남은 발송을 함께 정리한다.
2. **서버 설정.** Firebase Cloud Messaging API를 활성화하고 해당 프로젝트에 발송 권한이 있는 서비스 계정을 준비한다. DB 마이그레이션 적용 후 로컬 Compose에 `FCM_PROJECT_ID`와 저장소 밖 인증 파일의 절대 경로 `FCM_CREDENTIALS_FILE`을 설정하고 `docker compose --profile push up -d --build title-push`로 작업자를 실행한다. 클라우드에서는 같은 런타임 이미지에 ADC와 `FCM_PROJECT_ID`를 제공해 `python -m app.workers.title_push`를 상시 실행한다.
3. **앱에서 열기.** OS가 백그라운드 알림을 표시한다. Flutter는 종료 상태에서 누른 알림을 `getInitialMessage()`로, 백그라운드에서 누른 알림을 `onMessageOpenedApp`으로 처리한다. `data.label`과 `data.tier`는 획득한 활동 칭호의 이름과 티어다. `data.type=title_awarded`이면 로그인 후 `data.membership_id`의 보유 목록을 조회해 `data.title_id`를 보여준다. Android에서 설정으로 앱을 강제 중지한 경우 다시 실행해야 수신할 수 있다.

FCM 응답이 유실되면 같은 칭호 ID로 재시도한다. Android 알림 태그와 APNs collapse ID도 이 ID를 사용한다. FCM의 요청 수락과 기기의 실제 표시 여부는 구분한다. [FCM HTTP v1](https://firebase.google.com/docs/cloud-messaging/send/v1-api) · [Flutter 수신과 알림 탭](https://firebase.google.com/docs/cloud-messaging/flutter/receive-messages)

## 검증

```powershell
docker compose exec service ruff check .
docker compose exec service ruff format --check .
docker compose exec -e RUN_DB_TESTS=1 service pytest
```

DB 테스트는 격리 환경에서 실행한다. 명령·환경 변수·seed·기존 라우트의 상세 기록은 [이전 구현 README](README.legacy.md)에 보존했다. [개발 지침](AGENTS.md), [새 기획과 우선순위](../docs/PROJECT_CONTEXT.md), [구조와 전환 차이](../docs/PROJECT_STRUCTURE.md), [커밋 규칙](../docs/COMMIT_CONVENTION.md)을 함께 확인한다.
