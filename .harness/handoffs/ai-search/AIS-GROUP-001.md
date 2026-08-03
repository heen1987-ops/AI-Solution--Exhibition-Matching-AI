# AIS-GROUP-001 Handoff - GUEST_WEB 검색 품질 재정의 완료

상태: DONE

## 완료 범위

- AIS-007: WEB_ONLY Gold Set, RRF combiner, StructuredSearchProvider, GUEST_WEB_SEARCH_SCORE_V1.
- AIS-008: 무결과·저신뢰 검색 회복 정책.
- AIS-009: Keyword/Vector Provider 계약과 BAC-008 pipeline 연결 순서.

## 범위 결정

CR-001 이후 전용 KIOSK 검색 점수식은 만들지 않는다. 검색 채널은 REGISTERED_WEB/GUEST_WEB/BUYER_WEB 중심이며, 기존 kiosk 구현과 migration은 cleanup-only로 둔다.

## 남은 선행조건

BAC-008 구현 전에 CTR-012가 필요하다. 검색 persistence의 DB CHECK와 FTS/vector index readiness가 아직 WEB_ONLY 계약과 완전히 맞지 않는다.
