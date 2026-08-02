# C-5. 공통 AI·데이터 플랫폼 - 공통 API

근거 문서: `docs/redesign-v2/00-master-spec-v1.md`(§59), `docs/redesign-v2/01-module-split-plan.md`(§4-C C-5). [C-4 §6](C-4-search-recommendation-engine.md)의 미결정 사항(임베딩 재계산 트리거)을 확정하고, 웹([W-8](../web/W-8-api-and-db-changes.md))·키오스크가 공통으로 호출하는 API 표면을 정의한다.

## 1. 공통 API 목록과 웹/키오스크 API의 관계

| 공통 API | 웹 모듈 소비([W-8 §5](../web/W-8-api-and-db-changes.md)) | 키오스크 소비 |
| --- | --- | --- |
| `POST /common/search` (구조화+키워드+벡터 RRF, [C-4 §1](C-4-search-recommendation-engine.md)) | `POST /search`(S-3)가 이 API를 호출 + 프로파일 컴포넌트 결합 | [K-3](../kiosk/K-3-screen-ia.md) 결과목록 화면이 직접 호출(프로파일 결합 없음) |
| `GET /common/exhibitors/{id}` | S-5 | K-S5 |
| `GET /common/booths/{id}` | S-5 하위 | K-S6(지도) |
| `POST /common/recommendations` | `GET /recommendations`(S-1/S-2)가 내부적으로 호출 | K-S4(결과목록, 카테고리 선택 경로) |
| `POST /common/qr-sessions` | - | [K-5 §3](../kiosk/K-5-map-location-qr.md) QR 인계 |
| `POST /common/content-approvals` | (관리자 포털 전용, [W-9](../web/W-9-admin-operations.md) 범위) | - |

- 웹과 키오스크가 같은 `/common/search`·`/common/recommendations`를 호출하되 요청 바디의 `profile_id` 유무로 분기한다 - `profile_id`가 있으면 [W-5](../web/W-5-recommendation-logic.md)의 웹 점수식, 없으면 [C-4 §2](C-4-search-recommendation-engine.md)의 Kiosk Search Score를 적용한다. **API 엔드포인트를 웹용/키오스크용으로 이중화하지 않는다** - 01-module-split-plan.md §2.3의 "동일 데이터, 분리된 검색·추천 방식"을 하나의 엔드포인트가 내부 분기로 구현하는 것이 공통 플랫폼 설계 원칙에 더 부합한다(엔드포인트를 나누면 하드필터·재랭킹·이유생성 로직을 두 곳에서 유지보수해야 함).

## 2. 임베딩 재계산 트리거 - 결정

[C-4 §6](C-4-search-recommendation-engine.md)에서 넘긴 질문. **결정: 즉시 재계산이 아니라 배치(비동기 워커)로 처리한다.**

이유: 마스터 스펙 §5가 명시한 인프라는 Kafka 없는 RQ/Celery 워커다 - 업체 정보 수정 시 임베딩을 동기적으로 재계산하면 관리자 포털의 저장 응답이 느려지고, AI 호출 실패 시 정보 저장 자체가 실패하는 결합이 생긴다. 대신 `content_approval`([C-2](C-2-content-collection-ai-structuring.md))이 승인을 확정하는 시점에 재임베딩 잡을 큐에 넣고, 잡이 완료되기 전까지는 이전 임베딩으로 검색되도록 둔다(짧은 지연은 허용 - §57 Semantic 컴포넌트가 완벽히 최신이 아니어도 서비스에 치명적이지 않음).

## 3. QR 세션 API

- `POST /common/qr-sessions`는 [K-5 §3](../kiosk/K-5-map-location-qr.md)에서 확정한 프로토콜(단기 1회용 토큰, `GuestSession.entry_code` 재사용)을 그대로 구현한다 - 별도 신규 테이블 없이 `GuestSession` CRUD만으로 처리 가능([K-5 §5](../kiosk/K-5-map-location-qr.md)).

## 4. C-6으로 넘기는 질문

1. `/common/content-approvals`가 [W-9 §1](../web/W-9-admin-operations.md)에서 결정한 "DATA_REVIEWER는 EVENT_ADMIN 내부 권한 플래그" 방식의 인가를 어떻게 검사하는지 - C-6(개인정보·권한)에서 인가 메커니즘 전체와 함께 정의.
