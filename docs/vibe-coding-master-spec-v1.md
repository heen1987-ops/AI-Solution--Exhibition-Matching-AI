# 백주대간 AI 매칭·탐색 서비스 — 바이브코딩용 통합 개발 명세서 v1.0

> ## ⚠️ SUPERSEDED (2026-08-11, CR-009 / DECISION-014)
> 이 문서는 §0에서 스스로를 "개발의 단일 기준"이라고 선언하지만, 그 선언은 **더 이상 사실이 아니다**.
> CR-009(웹/키오스크 분리 재설계 자체를 대체하는 web-first 전환)와 DECISION-014가 이 문서의 핵심
> 전제 — 키오스크 하드웨어/전용 런타임이 존재하는 "웹·키오스크 분리형" 서비스 — 를 뒤집었다:
> 전용 키오스크는 MVP/v1.x 범위에서 제외된 비활성 호환 자산이고(`apps/kiosk`), 활성 채널은
> REGISTERED_WEB/GUEST_WEB/BUYER_WEB/ADMIN_PARTNER_WEB 네 개뿐이다. 현재의 단일 기준 문서는
> `PROJECT_SCOPE.md` + `AGENTS.md` + `.harness/contracts/**`이다. §33(키오스크 검색점수)과
> §35(바이어 매칭점수 재설계판)는 이 문서가 대체하려 했던 기존 산식과 사실상 다시 갈라져
> 있으며, 실제 구현은 어느 쪽도 그대로 채택하지 않았다 — `.harness/contracts/domain-model.md`와
> `apps/api/app/services/matching/**`가 실제 계약이다.
>
> **예외(그대로 유지 — 삭제하지 않음, 여전히 인용됨)**: §33-35와 §40은 부분적으로 여전히
> load-bearing이다. DECISION-009는 §34(웹 초개인화 점수)를 명시적으로 검토·기각하는 근거로
> §34 본문을 인용하고, CONTRACT-003은 §40(API 경로 규칙)을 실제 구현 경로와의 대조표 기준으로
> 인용한다. 이 두 결정을 다시 읽을 사람을 위해 §33-35와 §40 본문은 삭제하지 않고 그대로
> 보존한다 — 단, "이대로 구현하라"는 지시가 아니라 "이 결정이 무엇을 검토했는지의 기록"으로
> 읽어야 한다.
>
> 문서 전체(§0의 3모듈 재정리, MVP 제외목록 등)는 역사적 근거 문서로서 유효하지만, 새 작업의
> 출발점으로 이 문서를 다시 읽지 말 것. `PROJECT_SCOPE.md`에서 시작할 것.

> 문서 상태: 재설계(웹/키오스크 분리) 이후의 마스터 구현 기준서. 기존 1~28단계를 재검토해 통합.
> 로드맵: [30단계 통합 설계 로드맵](./00-roadmap.md) · 재설계 배경: [redesign-web-kiosk-split.md](./redesign-web-kiosk-split.md)
> 실행 방법론(하네스·병렬워커): [harness-orchestrator-prompt-pack.md](./harness-orchestrator-prompt-pack.md)

## 0. 문서 목적

본 문서는 기존 제1~28단계에서 설계한 사용자 프로파일, 업체·제품 데이터, 자연어 검색, AI 추천, 바이어 매칭, 관리자 기능, 개인정보·인프라 내용을 재검토하여 다음 3개 영역으로 재정리한 구현 기준서다.

1. 웹 초개인화 모듈 — 사전등록 사용자·바이어 대상
2. 키오스크 이식형 검색모듈 — 현장 비등록 방문객 대상
3. 공통 AI·데이터 플랫폼 — 업체·부스 데이터와 검색·추천 엔진 공유

본 문서를 개발의 단일 기준으로 사용한다. 기존 1~28단계에서 과도하게 확장된 다음 기능은 기본 MVP에서 제외한다: 정밀 위치추적, 복잡한 동선 최적화, 실시간 혼잡 예측, 제품별 실시간 재고관리, 장기 거래 CRM, 견적·계약·정산, 샘플 배송, 복잡한 상담장 자동배정, 대규모 온라인 학습, 키오스크 회원가입, 키오스크 장기 개인화, 독립 마케팅 자동화 플랫폼.

## 1. 서비스 한 줄 정의

사전등록 사용자와 바이어에게는 등록정보와 관심영역을 기반으로 개인별 참가업체·부스 정보를 선제적으로 제공하고, 현장 비등록 방문객에게는 키오스크 또는 게스트 웹의 자연어 검색을 통해 현재 관심분야와 관련된 업체·부스 목록과 위치를 제공하는 **웹·키오스크 분리형 AI 매칭·탐색 서비스**.

## 2. 핵심 서비스 원칙

### 2.1 사용자 유형에 따른 서비스 분리

| 사용자 | 서비스 방식 |
|---|---|
| 사전등록 일반 사용자 | 지속형 초개인화 추천 |
| 사전등록 바이어 | B2B 업체 매칭 |
| 현장 비등록 방문객 | 익명 자연어 검색 |
| 키오스크 사용자 | 현재 질의 기반 부스 탐색 |
| 참가업체 | 업체·제품·거래정보 관리 |
| 운영자 | 데이터 승인·검색·추천 운영 |

현장 비등록 방문객에게는 "초개인화"라는 표현을 사용하지 않는다.

### 2.2 추천과 검색 구분

- 초개인화 추천 = 사용자가 질문하지 않아도 프로파일 기반으로 먼저 제안
- 자연어 검색 = 사용자가 현재 필요한 내용을 입력하면 관련 결과 제공

### 2.3 채널 분리

웹과 키오스크는 화면, 세션, 사용자 상태, 기능을 분리한다. 공유하는 요소는: 참가업체·제품·부스 데이터, 관심영역 온톨로지, 자연어 질의 분석, 키워드·벡터 검색, 검색·추천 랭킹, 추천·검색 이유, 관리자 승인 데이터.

## 3. 최종 시스템 구성

```text
┌────────────────────────────────────────────────────┐
│              공통 AI·데이터 플랫폼                 │
│ 업체·제품·부스 DB / 관심영역 온톨로지 / 자연어 질의분석 │
│ 키워드·벡터 하이브리드 검색 / 초개인화 추천 엔진      │
│ B2B 매칭 엔진 / 추천·검색 이유 생성 / 업체자료 AI구조화│
│ 공통 관리자 기능                                    │
└───────────────────────┬────────────────────────────┘
                        │
           ┌────────────┴────────────┐
           ▼                         ▼
┌──────────────────────┐  ┌──────────────────────────┐
│ 웹 초개인화 모듈     │  │ 키오스크 검색모듈       │
│ 사전등록 사용자/바이어│  │ 현장 비등록 사용자      │
│ 지속 프로파일         │  │ 익명 단기 세션          │
│ 맞춤정보 선제 제공    │  │ 자연어 검색             │
│ 관심목록/B2B 매칭     │  │ 업체·부스·지도/QR 전달  │
└──────────────────────┘  └──────────────────────────┘
```

## 4. 애플리케이션 구성

- **apps/user-web** — 사전등록 일반 사용자, 사전등록 바이어, QR로 결과를 넘겨받은 게스트
- **apps/kiosk** — 행사장 키오스크, 무인안내 단말, 대형 터치스크린
- **apps/admin** — 행사 운영자, 참가업체 관리자, 데이터 검수자
- **apps/api** — 인증, 프로파일, 업체·제품·부스, 검색, 추천, 바이어 매칭, 관심목록, 간단 상담, 관리자 승인, QR 인계, 이벤트 수집
- **apps/worker** — 문서 구조화, 임베딩 생성, 검색문서 갱신, 알림 발송, 집계 처리

## 5. 권장 기술스택

- 프런트엔드: React, Next.js, TypeScript, Tailwind CSS, 공통 UI 컴포넌트 패키지. PWA는 키오스크·게스트 웹에 제한적으로 적용.
- 백엔드: Python, FastAPI, Pydantic, SQLAlchemy, Alembic
- 데이터: PostgreSQL, pgvector, PostgreSQL Full Text Search, Redis, S3 호환 Object Storage
- 비동기 처리: Redis Queue(RQ) 또는 Celery. 초기에는 별도 Kafka 도입 안 함.
- AI: LLM Gateway, 임베딩 모델, 자연어 조건 추출모델, 선택적 재순위화 모델, 템플릿 기반 설명 생성
- 배포: Docker, 관리형 컨테이너 서비스 또는 단순 Kubernetes, CDN, WAF, 관리형 PostgreSQL/Redis

## 6. 모노레포 예시

```text
backju-ai-matching/
├─ apps/
│  ├─ user-web/
│  ├─ kiosk/
│  ├─ admin/
│  ├─ api/
│  └─ worker/
├─ packages/
│  ├─ ui/
│  ├─ api-client/
│  ├─ shared-types/
│  ├─ ontology/
│  ├─ validation/
│  └─ config/
├─ database/
│  ├─ migrations/
│  ├─ seeds/
│  └─ views/
├─ ai/
│  ├─ prompts/
│  ├─ schemas/
│  ├─ evaluation/
│  └─ fallback/
├─ infra/
│  ├─ docker/
│  ├─ terraform/
│  └─ monitoring/
├─ tests/
│  ├─ api/
│  ├─ integration/
│  ├─ ai/
│  └─ e2e/
└─ docs/
   ├─ requirements/
   ├─ api/
   ├─ data-model/
   └─ operations/
```

## 7. 사용자 역할

`GENERAL_REGISTERED`(사전등록 일반), `BUYER_REGISTERED`(사전등록 바이어), `GUEST_WEB`(QR/게스트), `KIOSK_GUEST`(키오스크 익명), `EXHIBITOR_ADMIN`(참가업체 관리자), `EVENT_ADMIN`(행사 운영자), `DATA_REVIEWER`(업체정보 검수자)

## 8. 웹 초개인화 모듈

목적: 사전등록 사용자의 등록정보와 관심영역을 이용하여 적합한 참가업체·부스·프로그램을 행사 전·중·후에 전달한다.

핵심 기능: 사전등록 사용자 연계, 관심 프로파일 확인·수정, 개인화 홈, 추천 업체·부스, 자연어 추가검색, 관심 업체 저장, 업체·제품·부스 상세, 부스 위치 확인, 바이어 전용 업체 매칭, 간단 상담 요청, 행사정보 알림, 추천 피드백

## 9. 사전등록 사용자 연계

연계 데이터: 기존 등록 ID, 사용자 유형, 방문목적, 관심분야, 관심 제품·서비스, 업종, 회사정보, 바이어 여부, 연락처 인증 연결값

흐름: `기존 사전등록 사용자 로그인 → 외부 등록 ID 매핑 → 행사 프로파일 생성 → 기존 관심정보 표시 → 사용자 확인·수정 → 최초 추천 생성`

사용자가 확인하지 않은 기존 정보를 강한 필수조건으로 사용하지 않는다.

## 10. 일반 사용자 프로파일

기본정보: 사용자 유형, 행사 ID, 방문목적, 관심 산업, 관심 기술, 관심 제품·서비스, 선호 업체 유형, 관심 프로그램

상태: EXPLICIT(직접 입력) / IMPORTED(사전등록) / INFERRED(행동 추정) / CONFIRMED(사용자 확인) / REJECTED(삭제)

우선순위: `사용자 직접 수정 > 사용자 확인 > 사전등록 정보 > 반복 행동 > 단일 행동`

## 11. 개인화 홈

주요 영역: 나를 위한 추천 업체, 관심분야별 부스, 신규 참가업체, 관심 프로그램, 저장한 업체, 자연어 검색창, 바이어 전용 매칭

추천 카드 구성: 업체명, 부스번호, 대표 제품·서비스, 추천한 이유, 관련 관심분야, [상세보기]/[관심 저장]/[지도 보기]

## 12. 웹 자연어 검색

사전등록 사용자도 현재 요구에 따라 검색할 수 있다. 검색 시 `사용자 기존 관심 프로파일 + 현재 자연어 질의 + 행사 업체 데이터`를 결합한다. 현재 검색어가 기존 프로파일과 충돌할 경우 현재 요청을 우선하되 장기 프로파일을 자동 변경하지 않는다.

## 13. 웹 관심목록

저장 대상: 업체, 제품·서비스, 부스, 프로그램
주요 기능: 저장, 삭제, 메모, 카테고리 분류, 지도 확인, 바이어 상담 요청
저장정보: 사용자, 행사, 대상 유형, 대상 ID, 저장 시각, 저장 출처, 간단 메모

## 14. 바이어 웹 모듈

바이어 프로파일: 바이어 유형, 업종, 유통·판매 채널, 관심 제품·기술, 거래 목적, 예상 주문·도입 규모, 희망 공급지역, 거래 희망시점, OEM·PB·유통·수출 등 협력유형

핵심 흐름: `바이어 프로파일 확인 → 적합 업체 추천 → 업체 비교 → 관심 저장 → 간단 상담 요청 → 업체 수락·거절 → 연락처 제한 공유`

## 15. 바이어 매칭 최소 범위

포함: 업체 추천, 업체 비교, 공개 거래조건 조회, 상담 요청, 업체 수락/거절, 대체 시간 제안, 연락처 공유동의
제외: 장기 영업 CRM, 견적 발행, 계약 체결, 정산, 샘플 배송, 발주관리, 거래처 관리

## 16. 간단 상담 요청

요청정보: 업체, 관심 제품·서비스, 상담주제, 희망시간, 예상 거래규모, 요청 메모, 연락처 공유동의
상태: REQUESTED, ACCEPTED, TIME_PROPOSED, REJECTED, CANCELLED, COMPLETED
연락처 공유: `바이어 동의 + 업체 수락 = 제한적 연락처 공유`. 추천 노출만으로 연락처를 제공하지 않는다.

## 17. 키오스크 이식형 검색모듈

목적: 현장 비등록 방문객이 회원가입이나 프로파일 작성 없이 자연어로 관심분야를 입력하고 관련 업체·부스 목록을 찾도록 한다.

핵심 기능: 대기화면, 언어 선택, 자연어 검색, 카테고리 빠른 검색, 관련 업체·부스 목록, 업체 상세, 부스 위치·지도, QR 모바일 전송, 세션 자동 초기화, 기본 로컬 캐시

## 18. 키오스크 사용자 흐름

`대기화면 → 언어 선택 → 자연어 질문 또는 카테고리 선택 → 질의 분석 → 관련 업체·부스 검색 → 결과목록 → 업체 상세·지도 → QR 모바일 전송 → 세션 초기화`

## 19. 키오스크 화면 IA

K00 대기화면, K01 언어 선택, K02 검색 홈, K03 자연어 입력, K04 카테고리 선택, K05 검색 결과, K06 업체 상세, K07 부스 지도, K08 QR 전송, K09 검색 결과 없음, K10 네트워크 오류, K11 세션 종료

## 20. 키오스크 검색 홈

입력방식: 화면 키보드, 추천 검색문, 카테고리 버튼, 선택적 음성입력(MVP 필수 아님)

## 21. 키오스크 검색결과

카드: 업체명, 부스번호, 대표 제품·서비스, 질의와 관련된 이유, 관련 카테고리, 지도/상세 버튼
정렬: 자연어 질의 관련성, 카테고리 일치, 검색어 키워드 일치, 업체 데이터 완성도, 현재 운영 여부, 동일 업체 중복제어
키오스크에서는 사용자 행동이력과 장기 프로파일을 사용하지 않는다.

## 22. 키오스크 추가질문

검색결과가 지나치게 많거나 의도가 불명확할 때만 한 번의 추가질문을 제공한다. 긴 대화형 설문은 제공하지 않는다.

## 23. 키오스크 QR 인계

흐름: `키오스크 결과 선택 → QR 세션 생성 → 스마트폰 스캔 → 게스트 웹에서 동일 목록 확인`

QR에는 직접 데이터를 넣지 않고 서명된 세션 토큰만 넣는다:
```json
{"handoff_id": "qh_001", "event_id": "event_001", "expires_at": "2026-10-09T15:30:00+09:00", "signature": "signed_value"}
```

게스트 웹: 업체 목록/상세/지도 보기, 브라우저 내 임시 저장. 회원 전환은 선택적, 강제하지 않는다.

## 24. 키오스크 세션

원칙: 익명, 단기, 기기 단위, 개인정보 미수집, 이용 종료 후 초기화
초기화 조건: 이용 종료, QR 전송 완료, 60~120초 무입력, 관리자 초기화
초기화 대상: 입력 검색어, 검색결과, 선택 업체, 언어 설정, QR 토큰, 임시 로그

## 25. 키오스크에서 금지할 기능

회원가입 강제, 전화번호/이메일 입력, 바이어 상세 프로파일, 장기 관심목록, 장기 행동학습, 개인 상담내역, 결제, 계약·견적, 개인별 알림, 지속 위치추적. 복잡한 작업은 QR을 통해 웹으로 넘긴다.

## 26. 키오스크 이식 설정

```json
{
  "event_id": "event_001",
  "kiosk_id": "kiosk_a01",
  "default_language": "ko",
  "supported_languages": ["ko", "en", "ja", "zh"],
  "zone_id": "entrance_a",
  "session_timeout_seconds": 90,
  "qr_expiration_minutes": 30,
  "theme": {"logo_url": "", "primary_color": ""},
  "feature_flags": {"voice_input": false, "map": true, "qr_handoff": true}
}
```

## 27. 관리자·참가업체 모듈

운영자 기능: 행사 생성·설정, 사전등록 Import, 업체·제품·부스 관리, 관심영역 코드 관리, 업체정보 승인, 키오스크 설정, 부스 운영상태, 검색·추천 기본통계, 무결과 검색어, 사용자·권한, 감사로그

참가업체 기능: 업체 기본정보, 제품·서비스 등록, 부스정보 확인, 공개 거래정보, 문서 업로드, AI 추출값 확인, 수정·제출, 승인상태 확인

## 28. 업체정보 등록·승인

상태: DRAFT, SUBMITTED, AI_EXTRACTED, EXHIBITOR_REVIEWED, OPERATOR_REVIEW, APPROVED, PUBLISHED, REJECTED

추천·검색 사용 조건: `행사 참가 승인 + 필수 업체정보 완료 + 최소 1개 제품·서비스 등록 + 관심영역 코드 등록 + 운영자 승인`. 승인되지 않은 데이터는 운영 검색 인덱스에 포함하지 않는다.

## 29. 업체자료 AI 구조화

입력: 참가신청서, 회사소개서, 제품 카탈로그, 제품목록, 공개 거래자료
추출 대상: 업체명, 제품·서비스명, 산업, 기술분야, 활용분야, 주요 고객군, 제품 특징, 공개 거래조건, 공급지역, OEM·PB·수출 여부
처리 흐름: `문서 업로드 → 텍스트 추출 → 개인정보 마스킹 → AI 구조화 → 근거문장 연결 → 업체 확인 → 운영자 승인 → 검색·추천 반영`
원칙: 원문에 없는 값 생성 금지, AI 결과는 제안값, 근거문장 필수, 확인 전 게시 금지

## 30. 관심영역 온톨로지

```text
산업: 제조/물류/관광/식품/모빌리티/유통/공공
기술: AI/로봇/데이터/클라우드/IoT/자동화/친환경 기술
제품·서비스: 하드웨어/소프트웨어/플랫폼/솔루션/소재/장비/컨설팅
활용목적: 구매/도입/유통/협력/투자/실증/정보수집
```

코드 구조 예: `INDUSTRY.MANUFACTURING`, `TECH.AI`, `TECH.ROBOTICS`, `PRODUCT.PLATFORM`, `GOAL.PARTNERSHIP`, `CHANNEL.ONLINE`, `TRADE.OEM`

유사어 예: 스마트공장/스마트팩토리/지능형 제조 → `INDUSTRY.SMART_MANUFACTURING`. 다국어 라벨과 동의어는 별도 관리.

## 31. 자연어 질의 분석

입력 예: "관광객을 위한 다국어 AI 안내 솔루션 업체를 찾고 있어요."

출력 예:
```json
{
  "intent": "SEARCH_EXHIBITOR",
  "target_type": "EXHIBITOR",
  "concepts": ["INDUSTRY.TOURISM", "TECH.AI", "SERVICE.MULTILINGUAL_GUIDE"],
  "requirements": [], "excluded_concepts": [], "confidence": 0.94, "clarification_required": false
}
```

AI 역할 제한 — 수행: 의도 분류, 관심영역 추출, 유사어 해석, 검색조건 구조화, 결과 설명문 작성. 수행하지 않음: 최종 순위 임의 결정, 존재하지 않는 카테고리 생성, 미승인 업체정보 사용, 필수조건 자동 완화, 상담 확정.

## 32. 검색엔진

채널: 구조화 필터, 키워드 검색, 벡터 의미검색, 온톨로지 확장검색
처리순서: `자연어 입력 → 질의 구조화 → 공개범위 필터 → 구조화 후보검색 → 키워드 검색 → 벡터 검색 → 후보 통합 → 관련성 재정렬 → 중복제거 → 결과 이유 생성`
MVP 검색기술: PostgreSQL Full Text Search, pgvector, 메타데이터 필터, Reciprocal Rank Fusion 또는 가중합. 초기부터 OpenSearch나 전용 벡터 DB를 필수로 사용하지 않는다.

## 33. 키오스크 검색점수

```text
Kiosk Search Score = 0.45×Semantic Relevance + 0.30×Keyword Match + 0.15×Category Match + 0.05×Data Quality + 0.05×Booth Availability
```

필수 원칙: 운영 종료/미승인 업체 제외, 동일 업체 결과 반복 제한, 검색어와 무관한 신규업체 강제 삽입 금지, 광고는 검색결과와 분리

## 34. 웹 초개인화 점수

```text
Personalized Score = 0.35×User Interest Match + 0.25×Current Query Match + 0.15×Visit Goal Match + 0.10×Explicit Behavior Match + 0.10×Data Quality + 0.05×Booth Availability
```

현재 검색어가 없는 개인화 홈은 Current Query Match를 제외하고 재정규화한다.

행동 반영(MVP): 관심 저장, 업체 상세조회, 검색 클릭, 명시적 추천 제외. 단일 클릭으로 장기 선호를 확정하지 않는다.

## 35. 바이어 매칭점수 (재설계판 — 단순화 버전)

### 35.1 Hard Filter

제품·기술 분야 필수조건, 공급지역 필수조건, MOQ 상한, OEM·PB 필수, 수출국 필수, 신규 거래 불가, 공개범위·승인상태

### 35.2 기본점수

```text
Buyer Match Score = 0.20×Product·Technology Match + 0.15×Business Goal Match + 0.15×Channel Match
                   + 0.15×Order Scale·MOQ Match + 0.10×Region Match + 0.10×Cooperation Type Match
                   + 0.10×Trade Readiness + 0.05×Data Trust
```

> 참고: 이 재설계판 가중치는 12단계 문서의 10-요소·상세 가중치보다 단순화된 버전이다. 실제 구현 시 어느 쪽을 기준으로 할지는 확인 필요(로드맵의 "재설계 반영 여부" 항목 참고).

### 35.3 양면 적합도

업체가 희망 바이어 조건을 입력한 경우에만 적용:
```text
Mutual Score = Harmonic Mean(Buyer to Exhibitor Score, Exhibitor to Buyer Score)
```
업체 희망조건 데이터가 없으면 바이어→업체 단방향 점수만 제공한다.

## 36. 추천·검색 이유

생성방식: `점수·필터에서 근거코드 생성 → 템플릿 문장 → 선택적으로 LLM 문장 다듬기 → 사실 검증`. LLM이 새로운 추천근거를 만들지 못하게 한다.

## 37. 결과 없음 처리

원칙: 필수조건을 자동 완화하지 않는다. 무결과 검색어를 집계해 업체 데이터/카테고리/동의어/검색 설명/다음 행사 유치 분야 개선에 활용한다.

## 38. 핵심 데이터 모델

- 행사·사용자: `event`, `registered_user`, `external_reference`, `user_event_profile`, `buyer_profile`, `profile_interest`, `consent_record`
- 업체·부스: `exhibitor`, `event_participation`, `booth`, `product_service`, `exhibitor_interest`, `public_trade_condition`, `booth_status`
- 검색·추천: `search_session`, `search_query`, `search_result`, `recommendation_session`, `recommendation_result`, `favorite`
- 키오스크: `kiosk_device`, `kiosk_config`, `kiosk_session`, `qr_handoff`
- 상담: `meeting_request`, `meeting_status_history`
- AI·운영: `source_document`, `extracted_attribute`, `content_approval`, `embedding_document`, `embedding_vector`, `ai_execution_log`, `audit_log`, `interaction_event`

## 39. 주요 테이블 정의 (요약)

- `user_event_profile`: profile_id, user_id, event_id, user_type, visit_goals, profile_status, profile_version, created_at, updated_at
- `profile_interest`: profile_interest_id, profile_id, concept_code, preference_level, source_type, confidence, user_confirmed, active
- `exhibitor`: exhibitor_id, official_name, brand_name, summary, website_url, approval_status, data_quality_score, active
- `product_service`: product_service_id, exhibitor_id, name, type, summary, concept_codes, public, approval_status
- `booth`: booth_id, event_id, exhibitor_id, booth_number, zone_id, map_x, map_y, status
- `buyer_profile`: buyer_profile_id, profile_id, buyer_type, channel_codes, order_scale, region_codes, cooperation_codes, decision_timeline, verification_status
- `search_session`: search_session_id, event_id, channel(WEB/KIOSK), user_id, kiosk_session_id, language, created_at
- `search_result`: search_result_id, search_session_id, object_type, object_id, rank, semantic_score, keyword_score, structured_score, final_score, reason_codes
- `qr_handoff`: handoff_id, kiosk_session_id, selected_result_ids, token_hash, expires_at, claimed_at

## 40. API 설계 (요약 — 재설계판 경로 규칙)

```text
POST /api/v1/auth/login
POST /api/v1/auth/logout
POST /api/v1/events/{event_id}/registration/sync
GET/PATCH /api/v1/me/event-profile

GET /api/v1/events/{event_id}/exhibitors
GET /api/v1/exhibitors/{exhibitor_id}
GET /api/v1/exhibitors/{exhibitor_id}/products
GET /api/v1/booths/{booth_id}
GET /api/v1/events/{event_id}/map

POST /api/v1/search
GET  /api/v1/search/{search_session_id}

POST /api/v1/recommendations
GET  /api/v1/recommendations/{recommendation_session_id}

GET/POST/DELETE /api/v1/me/favorites[/{favorite_id}]

POST /api/v1/buyer/matches
GET  /api/v1/buyer/matches/{match_session_id}

POST/GET/PATCH /api/v1/meetings[/{meeting_id}]
GET /api/v1/me/meetings

POST /api/v1/kiosk/sessions
POST /api/v1/kiosk/sessions/{session_id}/search
POST /api/v1/kiosk/sessions/{session_id}/handoff
POST /api/v1/kiosk/sessions/{session_id}/close
GET  /api/v1/kiosk/config/{kiosk_id}

POST /api/v1/admin/exhibitors/import
GET  /api/v1/admin/exhibitors/review
POST /api/v1/admin/exhibitors/{id}/approve
POST /api/v1/admin/exhibitors/{id}/reject
PATCH /api/v1/admin/booths/{id}/status
GET  /api/v1/admin/analytics/searches
GET  /api/v1/admin/analytics/no-results
```

> 참고: 이 경로 체계는 `docs/frontend-backend-ai-interface-spec.md`(예: `/api/v1/profiles/me`, `/api/v1/meetings` 등)와 상당 부분 유사하지만 완전히 동일하지는 않다(예: `/api/v1/me/event-profile` vs `/api/v1/profiles/me`). 실제 구현된 backend/의 48개 엔드포인트와 대조 필요.

## 41. 검색 API 응답 예시

```json
{
  "search_session_id": "ss_001",
  "interpreted_query": {"intent": "SEARCH_EXHIBITOR", "concepts": ["TECH.AI", "INDUSTRY.TOURISM", "SERVICE.MULTILINGUAL_GUIDE"]},
  "results": [{
    "rank": 1, "object_type": "EXHIBITOR", "exhibitor_id": "ex_001", "name": "업체 A",
    "booth_number": "B-12", "summary": "관광지용 다국어 AI 안내 솔루션 제공",
    "reason": "검색하신 다국어 관광안내 AI와 관련된 솔루션을 전시합니다.",
    "concepts": ["TECH.AI", "INDUSTRY.TOURISM"]
  }],
  "clarification": null
}
```

## 42. 웹 주요 화면

W00 로그인, W01 사전등록 연계, W02 프로파일 확인, W03 개인화 홈, W04 추천 목록, W05 자연어 검색, W06 검색결과, W07 업체 상세, W08 제품·서비스 상세, W09 부스 지도, W10 관심목록, W11 바이어 프로파일, W12 바이어 매칭, W13 업체 비교, W14 상담 요청, W15 상담 상태, W16 MY·동의관리

## 43. 관리자 주요 화면

A00 관리자 홈, A01 행사 관리, A02 사전등록 Import, A03 업체 목록, A04 업체 검수, A05 제품·서비스 검수, A06 AI 추출 검수, A07 부스·지도 관리, A08 관심분야 코드, A09 키오스크 설정, A10 바이어 검증, A11 상담 요청, A12 검색 통계, A13 무결과 검색어, A14 사용자·권한, A15 감사로그

## 44. 검색·추천 데이터 품질

필수 업체정보: 업체명, 업체소개, 참가 행사, 부스번호, 최소 1개 제품·서비스, 최소 1개 관심분야 코드, 승인상태
검색 제외 대상: 참가 취소, 미승인, 필수정보 부족, 운영 중단, 공개범위 불일치

## 45. 개인정보 원칙

- 웹 사용자: 사전등록 연계 동의, 개인화 선택 동의, 프로파일 수정, 행동추론 삭제, 관심목록 삭제, 상담 연락처 공유동의
- 키오스크: 개인정보 원칙적 미수집, 익명 단기 세션, 검색내용 세션 종료 후 비식별 통계만 활용, 다음 사용자에게 이전 세션 미노출
- 바이어·업체: 비공개 거래정보 공개범위, 상담 수락 전 연락처 비공개, 타 업체·타 바이어 활동정보 비공개

## 46. 보안 요구사항

관리자 MFA, RBAC, 객체 단위 권한검사, TLS, 개인정보 컬럼 암호화, API Rate Limit, 파일 악성코드 검사, 키오스크 세션 자동 초기화, QR 토큰 서명·만료, AI 입력 개인정보 마스킹, 감사로그, 관리자 다운로드 통제

## 47. 이벤트 수집

- 웹: PROFILE_CONFIRMED, RECOMMENDATION_IMPRESSED, RECOMMENDATION_CLICKED, EXHIBITOR_VIEWED, FAVORITE_ADDED, SEARCH_SUBMITTED, MEETING_REQUESTED
- 키오스크: KIOSK_SESSION_STARTED, KIOSK_QUERY_SUBMITTED, KIOSK_RESULT_VIEWED, KIOSK_EXHIBITOR_VIEWED, KIOSK_MAP_OPENED, KIOSK_QR_CREATED, KIOSK_SESSION_ENDED
- 관리자: EXHIBITOR_APPROVED, EXHIBITOR_REJECTED, BOOTH_STATUS_CHANGED, KIOSK_CONFIG_CHANGED

직원·테스트 계정 이벤트는 성과지표에서 제외한다.

## 48. 핵심 KPI

- 웹: 사전등록 연계 성공률, 프로파일 확인 완료율, 추천 노출 사용자율, 추천 클릭률, 관심 저장률, 추천 업체 상세조회율, 바이어 상담 요청률, 부적합 피드백률
- 키오스크: 세션 수, 자연어 검색 완료율, 검색결과 제공률, 무결과율, 업체 상세조회율, 지도 열람률, QR 전송률, 평균 이용시간, 세션 자동 초기화 성공률
- 관리자: 업체 승인 완료율, 필수정보 완성도, AI 추출 수정률, 승인 후 검색 반영시간, 무결과 검색어 개선율

## 49. 성능 목표

| 기능 | 목표 |
|---|---|
| 일반 API | P95 500ms 이내 |
| 자연어 검색 | P95 2초 이내 |
| 개인화 추천 | P95 3초 이내 |
| 키오스크 결과 표시 | P95 2초 이내 |
| 업체 상세 | P95 1초 이내 |
| QR 생성 | P95 500ms 이내 |
| 관리자 승인 반영 | 5분 이내 |
| 키오스크 세션 초기화 | 즉시 |
| 핵심 서비스 가용성 | 99.9% 이상 |

## 50. 최소 AI 운영체계

필요: 모델 버전, 프롬프트 버전, 온톨로지 버전, 검색 인덱스 버전, 실행 로그, Fallback, 기본 평가셋
제외(초기 MVP): 자동 재학습, 복잡한 Feature Store, 실시간 Multi-Armed Bandit, 자동 Champion-Challenger 승격, 대규모 MLOps 플랫폼

## 51. AI Fallback

| 장애 | 대체 |
|---|---|
| 자연어 분석 실패 | 카테고리 선택 |
| 임베딩 실패 | 키워드·구조화 검색 |
| 재순위화 실패 | 기본 점수순 |
| LLM 설명 실패 | 템플릿 설명 |
| 문서 추출 실패 | 수동입력 |
| 외부 AI 장애 | 기본 검색 유지 |

AI 장애가 업체·부스 검색 전체 장애로 이어지지 않도록 한다.

## 52. 인프라 최소구성

```text
CDN·WAF → Load Balancer → Frontend Apps(user-web/kiosk/admin) → FastAPI Backend
                                                                   ├─ PostgreSQL + pgvector
                                                                   ├─ Redis
                                                                   ├─ Object Storage
                                                                   └─ Worker
```

MVP에서 Kafka, 전용 벡터 DB, 복잡한 마이크로서비스는 필수로 사용하지 않는다.

## 53. 키오스크 저속망 대응

로컬 캐시: 기본 화면, 주요 카테고리, 업체·부스 최소정보, 정적 지도, 오류 안내
네트워크 장애 시: 저장된 카테고리·업체 목록 제공, 캐시임을 표시. 상담·회원정보를 처리하지 않으므로 복잡한 오프라인 동기화는 구현하지 않는다.

## 54. 개발 우선순위 (Phase 0~8)

- **Phase 0. 프로젝트 기반**: 모노레포, Docker, 공통 환경설정, PostgreSQL, Redis, 인증 뼈대, 공통 타입, 테스트 환경. 완료기준: 모든 앱 실행, DB 마이그레이션, Health Check, 공통 CI
- **Phase 1. 업체·부스 데이터**: 행사, 업체, 제품·서비스, 부스, 관심영역 코드, 관리자 CRUD, 승인상태. 완료기준: 운영자가 업체를 등록·승인 가능, 승인 업체만 공개 API 노출, 부스 지도 좌표 저장
- **Phase 2. 키오스크 검색 MVP**: 키오스크 설정, 익명 세션, 카테고리/자연어 검색, 키워드·벡터 검색, 결과, 상세, 지도, 세션 초기화. 완료기준: 비회원 사용 가능, 자연어 검색 결과 제공, 90초 무입력 자동 초기화, 이전 사용자 정보 미노출
- **Phase 3. QR 모바일 인계**: QR 토큰, 게스트 웹 결과, 만료, 서명, 선택 결과 전달. 완료기준: 키오스크 결과가 모바일에서 동일하게 표시, 만료 토큰 차단, 개인정보 미포함
- **Phase 4. 웹 사용자·프로파일**: 로그인, 사전등록 Import·연계, 행사 프로파일, 관심정보 수정, 개인화 홈, 관심목록. 완료기준: 기존 등록 사용자 연결, 프로파일 확인·수정, 관심 업체 저장
- **Phase 5. 초개인화 추천**: 프로파일 매칭, 추천 점수, 추천 이유, 명시적 피드백, 제한적 행동 반영. 완료기준: 동일 조건에서 재현 가능한 추천, 사용자 직접 조건 우선, 미승인 업체 미노출, 추천 이유 제공
- **Phase 6. 바이어 매칭·간단 상담**: 바이어 프로파일, B2B Hard Filter, 업체 매칭점수, 업체 비교, 상담 요청, 수락·거절, 연락처 공유. 완료기준: 필수조건 위반 업체 제외, 상담 수락 전 연락처 비공개, 상담 상태 이력 저장
- **Phase 7. AI 업체정보 구조화**: 파일 업로드, 문서 파싱, AI 속성 추출, 원문 근거, 업체 확인, 운영자 승인, 임베딩 갱신. 완료기준: AI 값 자동 게시 금지, 모든 추출값에 근거 존재, 승인 후 검색 반영
- **Phase 8. 운영·통계·보안**: 검색 통계, 무결과 검색어, 추천/키오스크 KPI, 관리자 권한, 감사로그, 개인정보 기능, 배포·모니터링. 완료기준: 역할별 권한 적용, 관리자 주요행위 감사, 검색·추천·키오스크 성과 조회, 운영 배포 가능

키오스크를 먼저 구현하면(Phase 2) 공통 업체 데이터와 검색엔진의 품질을 빠르게 확인할 수 있다.

## 55. MVP 완료조건

- 웹: 사전등록 로그인, 관심정보 확인·수정, 개인화 추천, 자연어 추가검색, 관심 저장, 바이어 적합 업체 검색·추천, 간단 상담 요청
- 키오스크: 회원가입 없이 이용, 자연어/카테고리 검색, 관련 업체·부스 목록, 상세·지도, QR 모바일 전달, 세션 종료 후 이전 데이터 삭제
- 관리자: 업체·제품·부스 등록·승인, 관심영역 코드 관리, 키오스크 설정 변경, 부스 운영상태 관리, 검색·추천 기본지표·무결과 검색어 확인
- AI: 자연어 질의를 허용 코드로 구조화, 키워드·벡터 검색 결합, 추천·검색 이유를 실제 근거로 제공, AI 장애 시 기본 검색 유지, 미승인 정보 미사용

## 56. MVP 제외사항

개발 에이전트는 다음을 임의로 추가하지 않는다: 정밀 실내 내비게이션, 실시간 혼잡 예측, 실시간 제품 재고, 장기 사용자 행동학습, 키오스크 로그인, 키오스크 개인화, 복잡한 상담장 자동배정, 장기 리드 CRM, 견적·계약·결제, 마케팅 자동화, 전용 데이터웨어하우스, Kafka, 전용 벡터 DB, 복잡한 MLOps 플랫폼. 필요할 경우 확장 인터페이스만 남긴다.

## 57. 기존 1~28단계 반영 결과

| 기존 설계영역 | 최종 반영 |
|---|---|
| 사용자 유형 분리 | 유지 |
| 사용자 여정 | 웹·키오스크로 재구성 |
| 화면 IA | 채널별 분리 |
| 사용자 프로파일 | 웹 등록 사용자만 적용 |
| 업체·제품 프로파일 | 공통 플랫폼에 유지 |
| 온톨로지 | 공통 검색·추천 핵심으로 유지 |
| 후보검색 | 하이브리드 검색으로 유지 |
| Hard Filter | 웹·B2B에 유지 |
| B2C 추천점수 | 웹에 축소 적용 |
| B2B 점수 | 바이어 매칭에 적용 |
| 양면 적합도 | 업체 선호정보 존재 시 적용 |
| 상황 재정렬 | 운영상태·부스 위치 수준만 유지 |
| 다양성 | 동일 업체 반복제어 수준 |
| 콜드스타트 | 키오스크 세션 검색으로 단순화 |
| 행동학습 | 웹에서 제한적으로 적용 |
| 추천 설명 | 템플릿 중심 유지 |
| 대화형 프로파일링 | 웹 보조기능으로 축소 |
| 업체정보 AI 구조화 | 유지 |
| 임베딩·RAG | 공통 검색엔진으로 유지 |
| AI 오케스트레이션 | 최소 라우팅·Fallback 유지 |
| 데이터 파이프라인 | 필요한 동기화·승인 중심 유지 |
| MLOps | 버전·평가·롤백만 유지 |
| 분석 | 핵심 KPI 중심으로 축소 |
| 관리자 운영 | 업체·검색·추천 운영 중심 |
| 개인정보·보안 | 유지 |
| 고가용성·DR | MVP 수준으로 축소 |
| 복잡한 현장관제 | 제외 |
| 장기 CRM | 제외 |

## 58. 바이브코딩 실행지침

개발방식: 한 Phase씩 구현, 매 Phase마다 DB 마이그레이션 작성, API Schema 먼저 정의, Mock Data로 화면 구현, API와 화면 연결, 단위·통합 테스트 작성, 완료조건 검증 후 다음 Phase 진행

코드 원칙: TypeScript any 사용 최소화, Python 타입힌트 필수, Pydantic 요청·응답 모델 사용, 서비스·Repository 분리, 모든 API에 오류코드 정의, DB 직접 수정 금지(마이그레이션 사용), 권한검사 공통 Middleware 적용, AI 출력은 JSON Schema 검증, 개인정보 로그 출력 금지

범위 원칙: 키오스크와 웹 컴포넌트를 억지로 하나로 합치지 않음, 공통 UI는 버튼·카드·타입 수준에서만 공유, 키오스크는 익명 검색에 집중, 웹은 프로파일·개인화에 집중, 관리자 기능은 운영에 필요한 수준으로 제한, 새로운 기능을 임의 추가하지 않음

## 59. 개발 에이전트용 최종 명령

이 프로젝트는 사전등록 사용자용 웹 초개인화 모듈과 현장 비등록 방문객용 키오스크 자연어 검색모듈을 분리하여 개발한다. 웹 모듈은 사전등록 데이터 연계, 사용자 프로파일, 개인화 업체·부스 추천, 자연어 추가검색, 관심목록, 바이어 매칭과 간단 상담 요청을 제공한다. 키오스크 모듈은 로그인과 개인정보 수집 없이 익명 세션에서 자연어 또는 카테고리 검색을 제공하고, 관련 업체·부스 목록, 상세, 지도, QR 모바일 전송을 제공한다. 세션 종료 후 검색정보를 초기화한다.

두 모듈은 공통 업체·제품·부스 데이터, 관심영역 온톨로지, 자연어 질의 분석, 키워드·벡터 하이브리드 검색과 추천 이유 엔진을 공유한다. AI는 자연어 해석, 문서 구조화, 검색 보조와 설명문 생성에만 사용한다. 최종 필터, 추천점수, 공개범위, 상담상태와 개인정보 공유는 규칙 기반 백엔드에서 결정한다. 미승인 업체정보는 검색·추천에 사용하지 않는다. 키오스크에는 회원가입, 장기 프로파일, 상담 CRM, 개인정보 입력과 장기 행동학습을 구현하지 않는다.

PostgreSQL, pgvector, Redis, FastAPI, Next.js 기반으로 구현하고, MVP에서는 Kafka, 전용 벡터 DB, 복잡한 마이크로서비스와 대규모 MLOps 플랫폼을 도입하지 않는다. Phase 0부터 Phase 8까지 순서대로 구현하며, 각 Phase의 완료조건과 테스트가 충족된 후 다음 단계로 진행한다.

## 60. 최종 확정

1. 사전등록 사용자는 웹 초개인화 추천
2. 현장 비등록 방문객은 키오스크 자연어 검색
3. 웹과 키오스크는 별도 프런트엔드·세션·사용자 흐름
4. 업체·부스 데이터와 AI 검색엔진은 공통 사용
5. 바이어 매칭은 웹 전용
6. 키오스크 결과는 QR로 모바일에 전달
7. AI는 해석·검색·설명 보조, 최종 결정은 규칙엔진
8. 행사 운영플랫폼·장기 CRM으로 범위를 확장하지 않음
