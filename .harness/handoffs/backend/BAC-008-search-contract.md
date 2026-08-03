# BAC-008 Search Facade Contract From AIS-009

상태: READY FOR BACKEND

## 사용해야 할 AI_SEARCH 산출물

- `SearchQuery`, `SearchCandidate`, `StructuredSearchProvider`, `ReciprocalRankFusionCombiner`
- `decide_search_recovery`
- `BAC008_SEARCH_PIPELINE`
- `KEYWORD_SEARCH_CONTRACT`
- `VECTOR_SEARCH_CONTRACT`
- `DEFAULT_PROVIDER_READINESS`
- `fallback_reason_for_recovery`

## 구현 주의

현재 기본 readiness에서 STRUCTURED만 READY다. KEYWORD/VECTOR/POPULAR은 후속 provider SQL/query embedding adapter 구현 전까지 실행하지 말고, unavailable reason을 검색 meta/debug/handoff에 남긴다.

CTR-012로 `matching.search_session.channel` DB CHECK와 FTS/pgvector index migration은 정렬됐다. BAC-008은 `REGISTERED_WEB/GUEST_WEB/BUYER_WEB/ADMIN_PREVIEW` 값을 그대로 persistence할 수 있다.
