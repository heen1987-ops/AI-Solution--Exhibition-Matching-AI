# 19단계 구현 — 대화형 프로파일링

## 구현 상태

대화형 프로파일링의 실행 코어, 공개 API, 모바일 화면, 외부 모델 추출 경계를 구현했다.
운영 기본 경로는 결정론 정책이며, 외부 모델 결과도 사용자 확인 전에는 정본 프로파일에
반영되지 않는다.

## 사용자 흐름

1. `/profile/conversation`에서 현재 프로파일과 활성 대화를 불러온다.
2. 사용자가 방문 목적·취향·가격·거래조건을 자연어로 입력한다.
3. 서버는 식별정보를 마스킹한 후 조건과 모호성을 추출한다.
4. 각 조건을 `PROPOSED` 카드로 표시한다.
5. 사용자가 조건별로 확인하거나 거절한다.
6. 확인된 온톨로지 속성만 정본 프로파일에 반영한다.
7. 프로파일 버전을 증가시키고 기존 활성 추천을 무효화한다.

홈 화면에는 대화형 조건 설정과 선택형 직접 수정 진입점을 함께 제공한다.

## 개인정보와 정본 통제

- 전화번호, 이메일, 주민등록번호는 처리 전에 마스킹한다.
- 대화 DB에는 원문 대신 마스킹 문장과 SHA-256 지문만 저장한다.
- AI·규칙 추출값은 항상 `PROPOSED` 상태로 시작한다.
- 사용자 확인값만 `profile.profile_attribute`에 반영한다.
- 확인 요청은 예상 프로파일 버전을 검사해 동시 수정 충돌을 차단한다.
- 온톨로지에 없는 주문수량 같은 구조화 필드는 잘못된 속성으로 강제 변환하지 않는다.

## API

모든 공개 응답은 `{ success, data, meta }` 봉투를 사용한다.

| 메서드 | 경로 | 역할 |
|---|---|---|
| POST | `/api/v1/conversations` | 현재 프로파일의 활성 대화 생성·재사용 |
| POST | `/api/v1/conversations/{conversation_id}/messages` | 마스킹, 조건 추출, 모호성 질문 |
| POST | `/api/v1/conversations/{conversation_id}/extractions/{extraction_id}/decision` | 조건 확인·거절 및 프로파일 반영 |

## 데이터 모델

`conversation` 스키마에 다음 테이블을 사용한다.

- `conversation_session`: 행사·프로파일 경계, 대화 상태, 정책 버전
- `message`: 발신자, 마스킹 문장, 내용 지문
- `entity_extraction`: 코드·연산자·값·단위·근거·신뢰도·결정 상태·반영 속성 참조

Alembic 헤드는 `0015_conversation_profile`이다.

## AI 추출 경계

`netlify/functions/conversation-extract.ts`는 `/internal/ai/conversation/extract` 내부 경로를
제공한다.

- 내부 토큰이 없는 요청은 거부한다.
- 현재 온톨로지의 허용 코드만 JSON Schema enum으로 제공한다.
- 입력 문장에 실제로 포함된 근거 문자열이 없는 추출값은 폐기한다.
- 연령·성별·건강·소득·신원·연락처를 추론하지 않는다.
- 순위 결정이나 후보 추천을 수행하지 않는다.
- 모든 추출값에 사용자 확인 필요 상태를 강제한다.
- 모델·프롬프트·온톨로지 버전과 공급자 요청 ID를 응답 메타에 남긴다.

현재 공개 대화 API는 장애와 비용에 독립적인 결정론 정책을 기본으로 사용한다. 이 모델
경계를 선택 호출하고 결과 계보를 `ai.ai_run`에 기록하는 오케스트레이션은 22단계에서
연결한다.

## 구현 파일

- `backend/app/services/conversation_policy.py`
- `backend/app/api/v1/routers/conversation.py`
- `backend/app/models/conversation.py`
- `backend/app/schemas/conversation.py`
- `backend/alembic/versions/20260802_0015_conversation_profile.py`
- `netlify/functions/conversation-extract.ts`
- `frontend/app/profile/conversation/page.tsx`
- `frontend/lib/api-client.ts`
- `frontend/lib/types.ts`

## 검증

- 결정론 추출·마스킹·모호성·수량 단위 테스트
- 공개 라우트 등록 및 성공 응답 봉투 OpenAPI 계약 테스트
- Netlify 함수 TypeScript 검사
- Next.js 프로덕션 빌드 및 `/profile/conversation` 정적 생성
- 전체 백엔드 테스트와 Alembic 오프라인 SQL 검증

## 남은 범위

- 주문수량·상담시간을 전용 구조화 필드에 반영하는 명령 처리
- 현재 요청·방문 세션·행사·장기 프로파일 적용범위 선택
- 외부 모델 선택 호출, 재시도·회로차단, `ai.ai_run` 계보 연결
- 다국어·오탈자·사투리 평가셋과 접근성 실기기 검증
