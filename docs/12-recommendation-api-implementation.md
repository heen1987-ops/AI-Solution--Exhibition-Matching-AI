# 추천 API·사이트 어댑터 구현

## 공개 경계

- `POST /api/v1/recommendations`: 결정론적 필터·점수·재정렬 파이프라인을 실행하고 정책·모델·택소노미 버전과 결과를 한 트랜잭션으로 저장한다.
- `GET /api/v1/recommendation-sessions/{id}/items`: 동일 테넌트·행사·프로파일 소유자만 저장된 결과를 조회한다.
- `POST /api/v1/interactions/batch`: 표준 행동 이벤트를 행별 SAVEPOINT로 격리해 저장한다.

## backju.kr `/adm/` 이식 경계

`/adm/`의 현재 오류 화면, 세션 쿠키 이름, PHP 테이블 구조를 매칭 코어의 계약으로 사용하지 않는다. 백주대간 또는 다른 전시회 사이트는 서버 측 BFF/PHP/Netlify 함수에서 현재 로그인·익명 세션을 자체 방식으로 해석한 뒤 아래 권한 헤더를 전달한다.

- `X-Tenant-Id`
- `X-Event-Id`
- `X-Profile-Id`
- `X-Visit-Session-Id`(선택)
- `X-User-Id` 또는 `X-Guest-Session-Id` 중 정확히 하나
- `X-Site-Context-Timestamp`
- `X-Site-Context-Signature`

서명은 위 권한 헤더의 정규화된 값에 대한 HMAC-SHA256(`v1=...`)이며 허용 시차는 5분이다. 브라우저에는 `SITE_CONTEXT_SECRET`을 제공하지 않는다. 로컬·개발 디버그 환경만 무서명 헤더를 허용하고, staging/production은 `SECRET_KEY` 또는 `SITE_CONTEXT_SECRET`이 준비되지 않으면 설정 로딩 단계에서 실패한다.

정규화 원문은 다음 순서의 LF 구분 UTF-8 문자열이다. 선택 헤더가 없으면 콜론 뒤를 빈 값으로 유지한다.

```text
{X-Site-Context-Timestamp}
x-tenant-id:{value}
x-event-id:{value}
x-profile-id:{value}
x-visit-session-id:{value}
x-user-id:{value}
x-guest-session-id:{value}
```

PHP 호스트용 서버 측 서명 예제는 `adapters/php/BackjuAiSiteContext.php`에 있다. 사이트는 자체 세션·DB에서 위 식별자를 해석한 뒤 이 함수에 전달하며, 매칭 플랫폼이 `/adm/` 내부 세션 구현을 직접 읽지 않는다.

프로파일 소유권, 추천 세션 소유권, 추천 결과와 대상의 테넌트·행사 경계는 애플리케이션 검증과 복합 FK 양쪽에서 확인한다. 따라서 사이트 어댑터가 잘못된 ID를 전달해도 다른 행사 데이터로 연결할 수 없다.

`matching.match_result.context_details`에는 거리·도보시간·대기시간·관측시각·가용성의 최소 스냅샷을 보존한다. 재조회는 기본 점수가 아니라 당시 `final_score`와 이 스냅샷을 사용하므로 생성 직후와 저장 후의 등급·추천행동이 달라지지 않는다.

## 행동 이벤트 멱등성과 오류 격리

파티션된 `interaction.interaction_event`만으로 전역 중복을 판단하지 않는다. 비파티션 `interaction.client_event_dedupe`가 `(tenant_id, client_event_id)`를 선점하고 원문 스키마 페이로드의 SHA-256 지문을 보존한다.

- 같은 ID + 같은 지문: 최초 `interaction_event_id` 재사용
- 같은 ID + 다른 지문: `IDEMPOTENCY_CONFLICT`
- 개별 저장 실패: 해당 SAVEPOINT만 롤백하고 다른 이벤트는 유지
- dedupe 레코드와 행동 이벤트: 같은 SAVEPOINT에서 원자적으로 저장
- 두 테이블: append-only 트리거 적용

`context_json`에는 허용 목록 속성과 `zone`만 저장한다. 직접 식별정보·자유 메모·토큰·OTP·URL query 등 임의 속성은 버린다.

## 선택 모듈과 AI 경계

상담 테이블과 벡터 테이블은 사이트마다 설치 여부가 다를 수 있다. PostgreSQL `to_regclass`로 기능을 감지하며, 미설치 상태를 예외로 만들거나 진행 중인 추천 트랜잭션을 롤백하지 않는다.

현재 랭킹·하드필터·양면 점수는 내부 결정론적 모델이다. 향후 자연어 의도 추출과 추천 설명에 AI를 붙일 때만 Netlify AI Gateway 어댑터를 호출하며, 공급자 모델명·키·응답 원문을 도메인/API에 노출하지 않는다. AI 결과는 제안으로 취급하고 스키마·온톨로지·근거 검증을 통과한 뒤에만 저장한다.

## 검증

- OpenAPI 공개 경로 계약
- 사이트 컨텍스트 위변조·재전송 서명 검증
- 프로파일 소유자 경계
- 선택 벡터 기능 미설치 시 무롤백
- 행동 이벤트 SAVEPOINT 오류 격리
- 동일/상이 페이로드 멱등성
- Alembic PostgreSQL 오프라인 SQL 생성
- `POSTGRES_TEST_DATABASE_URL` 기반 실제 PostgreSQL 카탈로그 통합 테스트(선택 실행)

14단계 상황인지 실시간 재정렬과 위치·시간·혼잡·재고·상담 계보는 [14단계 구현 문서](./14-context-aware-reranking.md)에 반영했다. 다음 구현 단위는 15단계 다양성·공정성 정책 버전이다.
