# 변경 요청 CR-004 — 검색 임베딩 계약 게시

상태: **APPROVED**
승인일: 2026-08-02
승인 근거: Blocker Score 6(영향도 3 + 되돌리기 어려움 1 + 보안·개인정보 2 + 기존정보 부족 0).
기능은 기본 비활성이고 공급자 어댑터·새 모델 버전으로 교체 가능하므로 권장 기본값을 적용한다.

- 요청 트랙: AI_SEARCH
- 관련 작업: AISEARCH-002
- 현재 계약: `docs/db-erd-table-spec.md` §18.4의 `VECTOR(n)`에서 모델·차원·활성 모델이 미확정
- 필요 변경:
  - `text-embedding-3-small`의 `dimensions=512` 출력을 검색 임베딩 v1 계약으로 고정
  - cosine similarity와 active SUMMARY-row HNSW `vector_cosine_ops` 인덱스 사용. 참가 SUMMARY에
    승인 제품 공개 텍스트를 포함해 업체당 언어별 후보 행을 제한. 업체명·모든 제품명을 설명보다
    먼저 보존하고 남은 8,000-byte 입력 예산은 소스별로 공정 배분
  - 다중 event/model/language 필터의 회수 누락을 줄이기 위해 데이터베이스 pgvector 0.8.0
    이상과 `hnsw.iterative_scan=strict_order` 사용
  - `ai.object_embedding`을 tenant/event 경계, 콘텐츠 해시, 모델 버전, 언어, 활성 포인터와 함께 게시
  - 공개 승인 카탈로그 텍스트만 객체 임베딩 대상으로 허용
  - 업체·참가·제품·행사제품·recommendable membership이 바뀌면 DB trigger가 같은 참가사의
    활성 catalog vector를 즉시 비활성화한다. `BEFORE STATEMENT` trigger가 행 변경·FK cascade보다
    먼저 짧은 전역 catalog advisory lock을 잡고, 최종 백필도 같은 lock 안에서 최신 snapshot을
    재검증한 이후에만 포인터 교체
  - 질의 임베딩은 provider adapter 뒤에서 호출하고 원문·벡터를 로그에 남기지 않음
  - provider/pgvector/테이블 장애 시 semantic 점수만 0으로 낮추고 keyword/category 검색 유지
- 변경하지 않을 경우 문제: Semantic Relevance가 항상 0이며 AISEARCH-002의 P0 수용조건을 충족할 수 없음
- 영향 트랙: CONTRACTS, BACKEND, AI_SEARCH, QA
- 마이그레이션 필요: 예 — `0017_object_embedding`
- 하위호환 가능 여부: 예 — 공개 API/OpenAPI 응답 형식은 변경하지 않음
- 권장안: 512차원 고정 테이블과 정확한 `model_version_id` 결합. 다른 차원으로 전환할 때는 새 모델 버전과 별도 마이그레이션으로 백필 후 활성 포인터 교체
- 임시 우회 여부: 없음. 기능 비활성 또는 장애 시 기존 PostgreSQL FTS/keyword/category 경로가 정식 fallback
- 승인된 소유경로 확장:
  - `apps/api/app/models/ai.py`, `apps/api/alembic/**`, 계약 문서 — CONTRACTS
  - `apps/api/app/services/catalog_search.py`, `apps/api/app/services/matching/**`, `apps/api/app/core/config.py`, `apps/api/pyproject.toml`, 라우터 — BACKEND/AI_SEARCH 공동 인계
  - `apps/api/tests/**`, `.harness/reports/**` — QA

## 롤백 절차

1. 배포 환경의 `SEARCH_EMBEDDING_ENABLED=false`로 새 질의 임베딩 호출을 즉시 중단한다.
   공개 검색은 기존 FTS·keyword·category 경로를 그대로 사용한다.
2. 백필 또는 품질 문제가 원인이면 해당 event/language의 활성 포인터를 비활성화하고, 검증된
   구 모델 스냅샷이 있을 때만 원자적으로 다시 활성화한다.
3. 스키마 자체를 되돌려야 하고 후속 마이그레이션이 0017에 의존하지 않을 때
   `alembic downgrade 0016_kiosk_session`을 실행한다. 0017 downgrade는
   `ai.object_embedding`과 자신이 시드한 model version만 제거하며 공유 `vector` 확장은 유지한다.
   불변 `ai_run` 감사 행 또는 `recommendation_session` 런타임 행이 시드 모델을 참조하면 데이터
   보존을 위해 downgrade가 명시적으로 중단되므로, 이 경우 기능만 비활성화하고 스키마를 유지한다.
4. OpenAPI 응답 계약은 바뀌지 않았으므로 클라이언트 롤백은 필요하지 않다.

## 선택 근거

- 고정 차원은 pgvector 인덱스와 객체·질의 벡터의 동일 모델 비교를 강제한다.
- 512차원은 OpenAI embedding v3의 `dimensions` 파라미터로 직접 생성하며 애플리케이션이 임의 절단하지 않는다.
- Netlify AI Gateway의 현재 지원 모델 목록에는 embedding 모델이 없으므로 기존 Gateway 호출과 섞지 않는다.
- 의미 유사도는 `clamp(1 - cosine_distance, 0, 1)`로 정규화하고 최종 순위는 기존 결정적 가중식이 계산한다.
