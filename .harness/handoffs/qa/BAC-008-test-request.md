# BAC-008 QA Test Request

상태: READY FOR BAC-009

## 테스트 대상

- `POST /api/v1/search`
- `POST /api/v1/guest/sessions/{guest_session_id}/search`
- `POST /api/v1/search/clarify`
- `GET /api/v1/search/{search_session_id}`
- `GET /api/v1/recommendations`
- `GET /api/v1/recommendations/{recommendation_session_id}`

## 필수 회귀 시나리오

- REGISTERED_WEB/BUYER_WEB/GUEST_WEB/ADMIN_PREVIEW 채널별 접근 권한과 persistence 제약.
- FREE_TEXT의 `query_text` 누락, CATEGORY의 `concept_codes` 누락 시 `SEARCH_QUERY_INVALID`.
- 게스트 세션 만료/전환/비WEB entry_channel 시 `GUEST_SESSION_EXPIRED`.
- 무결과 응답은 200 + 빈 `results` + `meta.code=SEARCH_NO_RESULT`.
- 검색 replay와 clarify는 세션 소유권 또는 유효 게스트 세션을 요구.
- 추천 replay는 `RecommendationSession.profile_id` 소유권을 요구.
- `SearchResponse`, `RecommendationListResponse`, 오류 envelope가 `.harness/contracts/openapi.yaml`과 일치.

## 현재 한계

- BAC-008은 STRUCTURED provider만 실행한다.
- KEYWORD/VECTOR/POPULAR provider는 AIS-009 계약대로 unavailable meta만 노출한다.
