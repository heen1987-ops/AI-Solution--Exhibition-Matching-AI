# C-7. 공통 AI·데이터 플랫폼 - 공통 인프라

근거 문서: `docs/redesign-v2/00-master-spec-v1.md`(§5 기술 스택, §56), `docs/redesign-v2/01-module-split-plan.md`(§4-C C-7). [W-6 §3](../web/W-6-information-delivery-policy.md), [C-5 §2](C-5-common-api.md)에서 이관된 "발송·재계산 워커" 실행 주체를 확정한다.

## 1. 인프라 구성 (마스터 스펙 §5 그대로 채택)

```text
API 서버: FastAPI (기존 backend/ 그대로)
DB: PostgreSQL + pgvector + FTS (신규 확장: pgvector, C-4)
캐시: Redis
파일저장: S3(호환)
비동기 워커: RQ 또는 Celery (Kafka 없음, §56 제외)
```

- 새 인프라 구성요소를 도입하지 않는다 - `pgvector` 확장 활성화([C-4 §3](C-4-search-recommendation-engine.md))가 이번 재설계에서 유일하게 새로 추가되는 인프라 의존성이다.

## 2. 워커가 처리하는 작업 목록 (지금까지 이관된 항목 총정리)

| 작업 | 근거 | 트리거 |
| --- | --- | --- |
| 임베딩 재계산 | [C-5 §2](C-5-common-api.md) | 업체정보 승인(`content_approval`) 확정 시 큐잉 |
| 행사 후 정적 알림 발송 | [W-6 §3](../web/W-6-information-delivery-policy.md) | `visit_session.session_status = COMPLETED` 전이 시 |
| 사전등록 배치 임포트 | [W-2 §1-1](../web/W-2-user-journey.md), [W-9 §2](../web/W-9-admin-operations.md) | 관리자 트리거 또는 스케줄 |
| 자동 업데이트 자산 배포 | [K-7 §6](../kiosk/K-7-portable-package-structure.md) | 키오스크 앱 시작 시 폴링(워커가 아니라 클라이언트가 폴링하는 방식 - 워커는 자산을 준비해두기만 함) |

- 이메일 발송은 워커가 SMTP 연동을 직접 처리([W-6 §3](../web/W-6-information-delivery-policy.md) "실제 SMTP 발송은 C-7 책임"). SMS는 MVP 제외([W-6 §3](../web/W-6-information-delivery-policy.md)).

## 3. 캐시 사용 범위

- Redis는 (a) 세션 상태(웹 로그인 세션, 키오스크 세션 TTL), (b) 검색 결과 단기 캐시(동일 질의 반복 시 재계산 방지) 두 용도로만 사용한다 - [K-7 §7](../kiosk/K-7-portable-package-structure.md)의 "키오스크 로컬 캐시"(클라이언트 측)와는 별개로, 이건 서버 측 Redis다. 혼동 방지를 위해 이 구분을 명시한다.

## 4. 모니터링

- 마스터 스펙에 구체적 모니터링 스택이 명시되어 있지 않다 - 이 문서는 "무엇을 관측해야 하는가"만 정의하고 도구 선택(Prometheus/Grafana 등)은 구현 단계로 넘긴다: API 응답시간·오류율, 워커 큐 적체(특히 임베딩 재계산·알림 발송), `ai_execution_log`([C-2](C-2-content-collection-ai-structuring.md)) 기반 AI 호출 성공률.

## 5. C-8로 넘기는 질문

없음 - 이 문서에서 모든 항목을 확정했다.
