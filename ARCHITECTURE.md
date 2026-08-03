# ARCHITECTURE.md

## 기술스택 (고정)

프런트엔드: Next.js/React/TypeScript/Tailwind CSS. 백엔드: Python/FastAPI/Pydantic/SQLAlchemy/Alembic. 데이터: PostgreSQL+pgvector+FTS, Redis, S3 호환. 비동기: RQ 또는 Celery(Kafka 미사용). 배포: Docker, 관리형 PostgreSQL·Redis, CDN, WAF, 관리형 컨테이너 서비스 또는 단순 Kubernetes.

## 실제 저장소 구조 (이상적 모노레포와의 차이 - 반드시 확인)

```text
backend/               # FastAPI 앱 (이상적 구조의 apps/api에 해당하나 이동하지 않음)
  app/
    api/v1/endpoints/  # 현재 ontology 엔드포인트만 존재 - 매칭/프로파일/상담 API는 미노출
    models/            # SQLAlchemy ORM (identity/profile/exhibitor/matching/meeting/consent/core)
    services/matching/ # 후보검색·하드필터·피처빌더·오케스트레이터·재랭킹·이유생성
  alembic/versions/    # 8개 마이그레이션 (2026-08-01/02 기준)

src/meet_ai/
  ontology/            # 온톨로지 카탈로그(259개 v1 개념)·CLI·검증기
  scoring/             # ScoringPolicy 엔진 (CONSUMER_SCORE_V1/BUYER_SCORE_V1/EXHIBITOR_SCORE_V1/RECIPROCAL_SCORE_V1)

netlify/functions/     # AI Gateway 경계 함수 (자연어 속성 구조화)

apps/                  # 신규 - Next.js 프런트엔드 3종 (user-web/kiosk/admin), 아직 미생성
packages/              # 신규 - 공유 TS 패키지, 아직 미생성

docs/redesign-v2/       # 설계 단일 기준 (00-master-spec-v1.md 이하 W/K/C 26개 + 통합 로드맵)
.harness/               # 병렬개발 하네스 (본 문서 체계)
```

이 구조를 선택한 이유와 재검토 조건은 `.harness/assumptions.md` ASSUMPTION-001 참고.

## 3모듈 아키텍처

```text
                    공통 AI·데이터 플랫폼 (C)
        업체·부스·제품 DB · 온톨로지 · 검색·추천엔진 · 승인·통계
                              │
                ┌─────────────┴─────────────┐
                ▼                           ▼
      웹 초개인화 모듈 (A)          키오스크 이식형 검색모듈 (B)
      사전등록 사용자, 지속 프로파일    익명 게스트, 단기 세션
```

웹과 키오스크는 업체·부스 데이터와 검색 채널(RRF 후보 검색)을 공유하되, 점수 계산은 분리한다(웹: `ScoringPolicy` 재사용, 키오스크: `KIOSK_SEARCH_SCORE_V1` 신규) - 근거: `docs/redesign-v2/common/C-4-search-recommendation-engine.md` §1.

## 핵심 설계 원칙 (기존 프로젝트 관행 - 계속 유지)

1. 모듈러 모놀리스로 시작, 서비스 경계는 실측된 운영 필요에서만 추가한다.
2. 정본 비즈니스 레코드와 사용자·AI·리뷰 오버레이를 분리한다(`identity` vs `profile` 분리 원칙).
3. 불변 발행물은 버전을 매긴다 - 변경은 새 버전 생성이지 이력 재작성이 아니다.
4. 외부 AI·통합 제공자는 어댑터 뒤에 둔다.
5. 근거·증거 참조·검토 상태·append-only 활동 이력을 저장해 결정을 재현 가능하게 한다.
6. 관측성·재시도/멱등성·복구·프라이버시·운영자 검토를 설계 단계부터 포함한다.
7. AI 출력은 제안이다 - 결정론적 검증과 사용자/운영자 확인이 하드 제약과 정본 데이터를 통제한다.

## 도메인 모델·API 계약

정본은 `.harness/contracts/domain-model.md`(CTR-001 완료 시), `.harness/contracts/openapi.yaml`(CTR-002 완료 시)이다. 그 근거는 `docs/redesign-v2/`의 26개 W/K/C 문서 + 기존 `backend/app/models/*.py`.

## 알려진 아키텍처 격차 (G0/G1 진행 중 해소 예정)

- 매칭/프로파일/상담 도메인에 REST API가 없다(서비스 계층만 존재) - `BAC-GROUP-001`.
- Redis를 실제로 소비하는 코드 경로가 없다(설계만 존재) - Wave 2에서 캐시 구현.
- 프런트엔드 3종(`apps/user-web`, `apps/kiosk`, `apps/admin`)이 아직 없다 - `WEB-001`/`KSK-001`/`ADM-001`.
- CI 파이프라인이 없다 - `FND-003`.
