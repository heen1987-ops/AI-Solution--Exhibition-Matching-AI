# AGENTS.md - 모든 에이전트가 반드시 준수하는 불변 규칙

이 문서는 병렬개발 하네스(`.harness/`)를 운영하는 모든 에이전트·트랙에 적용된다. 위반 시 해당 작업은 완료로 처리하지 않는다.

## 1. 프로젝트 목표 (요약 - 전체는 `PROJECT_SCOPE.md`)

CR-001 이후 프로젝트 목표는 모바일 우선 웹서비스다. 채널은 `REGISTERED_WEB`,
`GUEST_WEB`, `BUYER_WEB`, `ADMIN_PARTNER_WEB`으로 고정하고, 전용 키오스크 모듈은
MVP에서 제외한다. 단일 기준은 `PROJECT_SCOPE.md`, `.harness/decisions.md`의
DEC-011, `.harness/contracts/**`다. 기존 `docs/redesign-v2/kiosk/**`와 키오스크 관련
구현/마이그레이션은 이력·cleanup 참고용으로만 남기며 신규 기능의 정본으로 사용하지 않는다.

## 2. 제외범위

`PROJECT_SCOPE.md` §제외범위를 확인 없이 구현하지 않는다. 새 기능을 발견해도 현재 작업에 몰래 포함하지 말고 `.harness/expansion-candidates.md`에 `EXPANSION-XXX`로 기록한다.

## 3. 기술스택 (고정 - 임의 추가·교체 금지, 변경 시 ADR 필요)

프런트엔드: Next.js/React/TypeScript/Tailwind. 백엔드: Python/FastAPI/Pydantic/SQLAlchemy/Alembic. 데이터: PostgreSQL/pgvector/PostgreSQL FTS/Redis/S3 호환. 비동기: RQ 또는 Celery 중 하나(Kafka 금지). 배포: Docker/관리형 PostgreSQL·Redis/CDN/WAF.

## 4. 디렉터리 소유권

`.harness/locks.yaml`이 유일한 정본이다. 이 문서에 요약하지 않는다 - 항상 `locks.yaml`을 확인한다. 핵심 원칙: 다른 트랙 소유 경로는 절대 직접 수정하지 않는다. 필요하면 `.harness/handoffs/{track}/`에 요청을 남긴다.

주의: 이 저장소는 메타프롬프트 원문의 이상적 경로(`apps/api`, `apps/worker`)를 그대로 쓰지 않는다. 기존 `backend/`(FastAPI)와 `src/meet_ai/`(온톨로지·스코어링 코어)는 물리적으로 이동하지 않았다 - `apps/`, `packages/`는 신규 코드 전용이다(`.harness/assumptions.md` ASSUMPTION-001).

## 5. 코드 규칙

- TypeScript: `any` 금지(명시적 사유 없이는), API 응답 타입 자동생성, 컴포넌트/비즈니스 로직 분리, 서버·UI 상태 분리, 오류·로딩·빈 결과 상태 필수.
- Python: 타입힌트 필수, Pydantic 요청·응답 모델, Service/Repository 분리, 예외를 공통 오류코드(`.harness/contracts/error-codes.yaml`)로 변환, 동기·비동기 혼용 주의, DB 세션 범위 명확화.
- AI: 출력 JSON Schema 검증, 허용 온톨로지 코드만 사용, 원문에 없는 조건 생성 금지, 실패 시 Fallback, 미승인 업체정보 사용 금지, 최종 필터·순위는 규칙엔진(하드필터·재랭킹) 담당 - AI가 최종 결정을 내리지 않는다.

## 6. DB 변경 규칙

- 직접 스키마 수정 금지 - Alembic Migration만 사용.
- 외래키·Unique·Check Constraint 사용. 시간은 UTC 저장. 삭제·승인·공개 상태를 명시적 컬럼으로 표현. 개인정보와 추천용 프로파일을 분리한다(기존 `identity` vs `profile` 스키마 분리 원칙 - `docs/07-user-profile-model.md` 2.1절, 계속 유지).
- DB 마이그레이션은 CONTRACTS 트랙만 생성한다.

## 7. API 변경 규칙

- 공유 계약(`.harness/contracts/openapi.yaml` 등)은 G1_CONTRACT_FREEZE 이후 직접 수정하지 않는다. 변경이 필요하면 `CHANGE_REQUEST`를 작성하고 영향 분석 후 CONTRACTS 트랙만 계약을 수정한다.
- 생성된 클라이언트 타입은 수동 편집하지 않는다. 통합 실패를 숨기기 위해 타입을 느슨하게 만들지 않는다.

## 8. 개인정보 금지사항 (절대 금지 - 메타프롬프트 §21과 동일)

- 게스트 웹에 회원가입 강제·전화번호·이메일·주소 입력·장기 사용자 프로파일·장기 브라우저
  지문을 추가하지 않는다.
- 게스트 웹 세션 종료 후 개인정보가 잔존하지 않는다. 기존 키오스크 세션도 cleanup 완료 전까지
  같은 개인정보 잔존 금지 원칙을 유지한다.
- 상담 수락(`meeting.status = CONFIRMED`) 전에는 연락처를 공개하지 않는다(`docs/redesign-v2/web/W-7-buyer-matching-consultation.md` §3).
- 미승인 업체(`master_approval_status != 'APPROVED'`)를 검색·추천에 포함하지 않는다(`docs/redesign-v2/common/C-4-search-recommendation-engine.md` §4).
- AI 출력값을 검증 없이 DB에 저장하지 않는다.

## 9. 테스트 완료조건

- Lint, Type Check, Unit Test, Integration Test 통과 없이 작업을 완료 처리하지 않는다.
- 테스트 실패를 무시하고 완료 처리하지 않는다.
- 전체 게이트 기준은 `.harness/quality-gates.yaml` 참고. `TESTING.md`에 실행 방법 상세.

## 10. 인계 형식

작업 완료 후 `.harness/handoffs/{track}/{task-id}.md`를 메타프롬프트 §16 형식(완료 내용/변경 파일/공개 인터페이스/DB 변경/테스트/알려진 제한/다른 트랙이 해야 할 일/되돌리는 방법/다음 권장 작업)으로 생성한다.

## 11. 절대 금지사항

계획만 반복하고 구현하지 않는 행위, 이미 정해진 사항을 다시 질문하는 행위, 범위 밖 기능을 "좋은 아이디어"라는 이유로 구현하는 행위, 테스트 실패 무시, 다른 트랙 소유 파일 무단 수정, AI 출력값 미검증 저장, 게스트 웹 개인정보 입력 추가, 신규 키오스크 기능 생성, 상담 수락 전 연락처 공개, 미승인 업체의 검색·추천 포함, `다음` 입력 시 전체 계획만 다시 설명하는 행위.

## 12. 배포

구현 단위가 관련 검증을 통과하면 의도적으로 로컬 커밋한다(트랙별로 분리, 다른 트랙의 미완료 변경과 섞지 않는다). 비밀값·로컬 의존성 디렉터리·무관한 작업공간 변경을 포함하지 않는다.

**Push는 자동으로 하지 않는다.** 이 저장소의 실제 remote는 `origin`(`heen1987-ops/AI-Solution--Exhibition-Matching-AI`) 하나뿐이다 - 과거 문서가 언급한 `exhibition`이라는 이름의 별도 remote는 실제로 설정된 적이 없다(2026-08-02 WEB-001 작업 중 확인). `origin`은 다른 협업자(예: 병렬 Codex 개발)가 함께 보는 공유 저장소이므로, push는 매번 사용자에게 명시적으로 확인받은 뒤에만 실행한다.
