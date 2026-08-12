# USERWEB-005 — 코드 수준 API 클라이언트 재감사 (2026-08-13)

## 목적·방법

`apps/user-web/lib/api-client.ts`가 실제로 호출하는 경로 문자열을, 백엔드가 **지금 이
브랜치 기준으로(`codex/backju-ontology-ai-gateway` 최신 tip)** 실제로 등록한 FastAPI 경로와
1:1로 대조했다. 2026-08-02 재설계 문서(DECISION-005) 대비 비교가 아니라, 코드-대-코드
비교다.

- **Ground truth**: `app.openapi()["paths"]`에서 직접 추출한 116개 경로 (+ `/healthz`),
  이 감사 직전에 캡처됨. 전체 목록은 이 저장소 밖 스크래치패드에 있었으므로 본 보고서
  16절 부록에 그대로 옮겨 적었다.
- **접두사**: `apps/api/app/core/config.py:50` `API_V1_PREFIX = "/api/v1"`,
  `apps/api/app/main.py:66`에서 `app.include_router(api_router, prefix=settings.API_V1_PREFIX)`로
  적용된다. `api-client.ts`의 `buildUrl()`도 동일하게 `API_V1_PREFIX = "/api/v1"`를 자체
  상수로 붙이므로, 두 쪽 모두 `/api/v1` 접두사를 붙인 뒤의 나머지 경로만 비교하면 apples-to-apples다.
- **분류**:
  - **A** — 실제 경로와 일치. 조치 없음.
  - **B** — ground-truth 116개 경로 어디에도 없는, 진짜 공백. 이 파일(`api-client.ts`)은
    고치지 않는다(가짜 백엔드를 만들지 않는다) — 실제 엔드포인트를 만드는 건 다른 트랙 소유.
  - **C** — 경로가 살짝 틀렸을 뿐 의도된 실제 엔드포인트가 명백히 존재. 이번 감사에서는
    **0건** — 아래 상세.

## 요약

| 구분 | 건수 |
|---|---|
| 점검한 export 함수 | 36 |
| A (일치) | 25 |
| B (공백) | 8 |
| C (경로 오기, 수정함) | 0 |
| 해당 없음(스텁/래퍼, 아래 설명) | 3 |
| 이번 커밋에서 실제로 수정한 함수 | 0 |
| 이번 커밋에서 새로 만든 backlog 항목 | 3 (BACKEND-015, BACKEND-016, BACKEND-017) |

C가 0건인 이유: 이번에 발견된 불일치는 전부 "실제 백엔드에 그런 리소스 자체가 없음"이었지,
"있긴 한데 경로 철자가 다름"이 아니었다. 작업 지시대로, B/C 판별이 애매한 건은 전부 B로
남겨 보고만 하고 임의로 고치지 않았다.

## A — 일치 (25건)

| 함수 | 메서드 | 클라이언트 경로 | 실제 경로 |
|---|---|---|---|
| `searchApprovedCatalog` | POST | `/search` | `/api/v1/search` |
| `createProfileSession` | POST | `/sessions` | `/api/v1/sessions` |
| `putConsents` | PUT | `/consents/me` | `/api/v1/consents/me` |
| `getConsents` | GET | `/consents/me` | `/api/v1/consents/me` |
| `createPrivacyRequest` | POST | `/privacy-requests` | `/api/v1/privacy-requests` |
| `listPrivacyRequests` | GET | `/privacy-requests` | `/api/v1/privacy-requests` |
| `patchProfileSession` | PATCH | `/profiles/me/user-type` | `/api/v1/profiles/me/user-type` |
| `postAnswers` (GOALS) | PUT | `/profiles/me/goals` | `/api/v1/profiles/me/goals` |
| `postAnswers` (CONSUMER_PREFERENCES) | PUT | `/profiles/me/consumer-preferences` | `/api/v1/profiles/me/consumer-preferences` |
| `postAnswers` (BUYER_NEEDS) | PUT | `/profiles/me/buyer-needs` | `/api/v1/profiles/me/buyer-needs` |
| `postAnswers` (VISIT_PLAN) | PUT | `/visit-sessions/current/plan` | `/api/v1/visit-sessions/current/plan` |
| `updateProfilePreferences` | PATCH | `/profiles/me` | `/api/v1/profiles/me` |
| `patchProfileAttributes` | PATCH | `/profiles/me/attributes` | `/api/v1/profiles/me/attributes` |
| `getProfile` | GET | `/profiles/me` | `/api/v1/profiles/me` |
| `getProfileCompleteness` | GET | `/profiles/me/completeness` | `/api/v1/profiles/me/completeness` |
| `getProfileVersions` | GET | `/profiles/me/versions` | `/api/v1/profiles/me/versions` |
| `startConversation` | POST | `/conversations` | `/api/v1/conversations` |
| `sendConversationMessage` | POST | `/conversations/{id}/messages` | `/api/v1/conversations/{conversation_id}/messages` |
| `decideConversationExtraction` | POST | `/conversations/{id}/extractions/{id}/decision` | `/api/v1/conversations/{conversation_id}/extractions/{extraction_id}/decision` |
| `createRecommendationSession` | POST | `/recommendations` | `/api/v1/recommendations` |
| `getHomeRecommendations` | GET | `/home` | `/api/v1/home` |
| `getRecommendationSessionItems` | GET | `/recommendation-sessions/{id}/items` | `/api/v1/recommendation-sessions/{recommendation_session_id}/items` |
| `postInteractions` | POST | `/interactions/batch` | `/api/v1/interactions/batch` |
| `getBooth` | GET | `/booths/{id}` | `/api/v1/booths/{booth_id}` |
| `listPartnerMeetings` | GET | `/partner/meetings` | `/api/v1/partner/meetings` |
| `getPartnerMeetingBuyerSummary` | GET | `/partner/meetings/{id}/buyer-summary` | `/api/v1/partner/meetings/{meeting_id}/buyer-summary` |
| `decidePartnerMeeting` | POST | `/partner/meetings/{id}/decision` | `/api/v1/partner/meetings/{meeting_id}/decision` |
| `submitMeetingOutcome` | POST | `/partner/meetings/{id}/outcome` | `/api/v1/partner/meetings/{meeting_id}/outcome` |

(표에 25개가 아니라 그 이상으로 보이는 건 `postAnswers`의 4개 오버로드를 각 분기별로
한 줄씩 풀어 적었기 때문 — 함수 단위로는 25개.)

`getProfile`/`updateProfilePreferences`가 부르는 `/profiles/me`(경로 파라미터 없는 형태)는
처음에 ground-truth JSON을 훑을 때 있는지 없는지 헷갈렸다 — 다른 `/profiles/me/*` 접두 경로들
사이에 끼어 있어 놓치기 쉽다. `apps/api/app/api/v1/routers/profile.py:1086`
(`PATCH /profiles/me`)과 `:1215`(`GET /profiles/me`) 소스로 직접 재확인해 실재를 확정했다.

## B — 공백 (8건, 코드 미수정)

| 함수 | 메서드 | 클라이언트 경로 | 상태 |
|---|---|---|---|
| `getProduct` | GET | `/products/{id}` | **완전 미착수.** ground-truth 어디에도 없음. `/exhibitors/{exhibitor_id}/products`(목록)와 `/partner/products/{id}/trade-conditions`(입점사 전용 거래조건)만 존재 — 둘 다 이 함수가 원하는 "공개 제품 단건 상세"가 아니다. 세션 내 어느 in-flight 브랜치에서도 손대지 않음. → **BACKEND-015 신설**. |
| `createFavorite` | POST | `/favorites` | **부분 진행 중, 아직 미완성.** ground-truth에 `/favorites`도 `/me/favorites`도 없음 — 라우터가 아직 안 붙었다. 그러나 `.harness/backlog.yaml`의 기존 `BACKEND-009`(`관심목록(즐겨찾기) API`, status: BLOCKED, depends_on: CONTRACT-003·CONTRACT-005)가 이미 이 작업을 소유하고 있고, 계약된 실제 경로는 **`/me/favorites[/{favorite_id}]`** — 지금 클라이언트가 쓰는 `/favorites`가 아니다. `CONTRACT-005`(모델·마이그레이션)는 `feature/contract-005-favorites` 브랜치에서 이미 게시됐지만(라우터 없음), `BACKEND-009` 자체는 아직 착수되지 않았다. → 새 backlog 항목 만들지 않음(이미 BACKEND-009가 소유) — 단, **BACKEND-009 구현 시 실제 경로가 `/favorites`가 아니라 `/me/favorites`라는 점을 반드시 반영해야 하며, 이 파일의 세 함수(`createFavorite`/`deleteFavorite`/`listFavorites`)도 그때 함께 고쳐야 한다**는 점을 여기 명시적으로 남긴다. |
| `deleteFavorite` | DELETE | `/favorites/{id}` | 위와 동일 (BACKEND-009 소관, 계약 경로는 `/me/favorites/{favorite_id}`). |
| `listFavorites` | GET | `/favorites` | 위와 동일 (BACKEND-009 소관, 계약 경로는 `/me/favorites`). |
| `createRoute` | POST | `/routes` | **이미 다른 브랜치에서 구현 완료.** `feature/indoor-route-navigation`(및 `track/route-positioning-pathfinding`, 공통 조상 `72ec013`)가 `apps/api/app/api/v1/routers/route.py`를 추가했고, 실제 등록 경로는 `POST /routes`("" + 라우터 prefix)로 이 클라이언트의 추측과 **정확히 일치**한다. 다만 그 브랜치는 프론트엔드 통합을 이 파일이 아니라 별도 모듈 `apps/user-web/features/indoor-route/api.ts`로 만들었고, `api-client.ts`/`types.ts`에도 직접 몇 줄을 얹었다(`checkpointScan` 함수, `CheckpointScanRequest/Response` 타입, 그리고 아래 타입 불일치 절의 `BoothDetailResponse` 수정). 이 브랜치(`feature/userweb-005-api-audit`)는 그 작업 위에 만들어지지 않았으므로 병합 전까지는 여전히 미해결로 보이지만, 실제로는 **이미 커버됨** — 새 backlog 불필요. |
| `recalculateRoute` | POST | `/routes/{id}/recalculate` | 위와 동일. `route.py`가 `POST /{route_id}/recalculate`를 등록 — 일치. 이미 커버됨. |
| `postCheckIn` | POST | `/check-ins` | **완전 미착수.** ground-truth에 없음. 저장소 전체 git 이력(`git log --all`)과 백엔드 라우터 전수 검색에서 QR 체크인 API 흔적 없음(`apps/user-web/app/check-in/[qrToken]/page.tsx` 화면은 여러 브랜치에 있지만, 그건 main에 이미 있던 화면이 diff에 공통으로 잡힌 것뿐 — 백엔드 라우터는 어디에도 없다). → **BACKEND-016 신설**. |
| `postFeedback` | POST | `/feedback` | **완전 미착수.** ground-truth에 없음, 어떤 브랜치에도 백엔드 라우터 없음. → **BACKEND-017 신설**. |

## C — 경로 오기(수정 대상)

없음. `api-client.ts`가 실제로 부르는 모든 경로는 (a) ground-truth와 정확히 일치하거나
(b) 해당 리소스 자체가 아직 백엔드에 없다. "있긴 한데 세그먼트가 하나 빠졌다/틀렸다"류의
애매한 케이스는 한 건도 없었다.

## 해당 없음 (3건)

- `mergeCurrentSession` — HTTP 호출을 하지 않는 의도적 스텁(`Promise.reject(NOT_IMPLEMENTED)`).
  경로 문자열 자체가 없어 분류 대상이 아니다.
- `getRecommendations` — `getHomeRecommendations`/`getRecommendationSessionItems`(둘 다 A)로
  위임하는 통합 진입점, 자체 경로 없음.
- `postInteraction` — `postInteractions`(A)로 위임하는 단건 편의 함수, 자체 경로 없음.

## `types.ts` 응답 형태 점검 (이번에 비교한 엔드포인트 한정)

이번 감사에서 실제로 쓰이는(A로 분류된) 엔드포인트 중 응답 형태가 코드로 직접 확인 가능했던
것은 `GET /booths/{booth_id}`(`getBooth` → `BoothDetailResponse`) 하나다.
`apps/api/app/schemas/exhibition_public.py`의 `PublicBoothDetail`과 대조한 결과:

- **이미 알려져 고쳐진 문제**: 이 브랜치의 베이스(`codex/backju-ontology-ai-gateway`)가 갖고
  있던 `BoothDetailResponse.location: {zone, x, y}`는 실재한 적 없는 계약이었다 —
  실제 응답은 중첩 객체가 아니라 평면 `zone_name`/`map_x`/`map_y`다. 이건 이미
  `feature/indoor-route-navigation`(= `track/route-positioning-pathfinding`) 브랜치가
  발견 즉시 고쳐서 커밋해 뒀다(해당 브랜치의 `types.ts` 커밋 메시지 겸 주석 참고). 이 브랜치는
  그 작업 위가 아니라 `codex/backju-ontology-ai-gateway` 위에 만들어졌으므로 지금 이
  파일에는 아직 옛 `location` 형태가 남아 있지만, 병합되면 자동 해소된다 — 여기서 다시
  고치지 않는다(같은 수정을 두 브랜치가 따로 하면 병합 충돌만 늘어난다).
- **아직 아무도 안 건드린, 남은 불일치**(위 브랜치도 "범위 밖"이라 명시적으로 스킵함):
  - `exhibitor: BoothExhibitorSummary{exhibitor_id, name, summary}` — 실제 응답은 이걸
    중첩 객체로 감싸지 않고 `exhibitor_id`/`company_name`/`company_summary`를 부스 객체에
    바로 평면으로 둔다. 필드명도 `name`↔`company_name`, `summary`↔`company_summary`로 다르다.
  - 실제 응답에 있는 `congestion_level`(혼잡도)이 프론트 타입엔 전혀 없다.
  - 프론트 타입의 `services: {tasting, purchase, meeting}`, `recommendation_context`는
    실제 `PublicBoothDetail`에 대응 필드가 없다(둘 다 백엔드에 존재하지 않는 필드로 보인다 —
    다만 이건 화면 쪽에서 실제로 참조하는지까지 추적하지 않았으므로 단정하지 않는다).

  이 잔여 불일치는 필드 여러 개가 얽혀 있고(중첩 구조 변경 + 필드명 변경 + 필드 존재
  자체가 불확실한 두 개), 소비하는 화면 컴포넌트까지 손대야 안전하게 고칠 수 있는 규모라
  작업 지시의 "크거나 불확실하면 보고만" 기준에 해당한다. 이 감사에서는 고치지 않고
  보고만 한다 — 필요하면 별도 트랙이 `BoothDetailResponse`를 한 번 더 정리해야 한다.

다른 B로 분류된 엔드포인트(`ProductDetailResponse`, `FavoriteView`/`FavoriteCreateRequest`,
`CheckInRequest/Response`, `FeedbackRequest/Response`)는 백엔드 스키마 자체가 없으므로
대조할 대상이 없다 — 이 파일들의 타입은 여전히 재설계 문서 프로즈 기준의 잠정 계약이며,
해당 backend 작업(BACKEND-015/016/017, BACKEND-009)이 실제 스키마를 게시하면 그때
대조해야 한다.

## 이번 커밋에서 발생한 변경

- `apps/user-web/lib/api-client.ts`, `apps/user-web/lib/types.ts`: **변경 없음** (C가 0건이므로).
- 신규 backlog 항목 3건 (`BACKEND-015`, `BACKEND-016`, `BACKEND-017`) — 아래 섹션.
- `USERWEB-005`를 `DONE`으로 갱신, evidence에 이 보고서 경로와 A/B/C 집계를 남김.

## 신규 backlog 항목

| id | 제목 | track | priority | 대응하는 B 항목 |
|---|---|---|---|---|
| BACKEND-015 | 공개 제품 단건 상세 API (`GET /products/{product_id}`) | BACKEND | P2 | `getProduct` |
| BACKEND-016 | QR 체크인 API (`POST /check-ins`) | BACKEND | P1 | `postCheckIn` |
| BACKEND-017 | 방문 피드백 API (`POST /feedback`) | BACKEND | P2 | `postFeedback` |

(`/favorites`↔`/me/favorites`, `/routes`류는 위에서 설명한 대로 기존 `BACKEND-009`가
소유하거나 이미 다른 브랜치에서 완료됐으므로 새 항목을 만들지 않았다.)

## 부록 — 대조에 사용한 ground-truth 116경로

`app.openapi()["paths"]`에서 추출한 원본 그대로(`/api/v1` 접두사 포함, `/healthz` 제외 116개
+ `/healthz` 1개 = 117개 키, 그중 유의미한 API 경로 116개). 원본 스크래치패드 파일:
`real_api_paths.json`(이 세션 한정 임시 파일 경로, 저장소 밖). 위 A/B 표의 "실제 경로" 열이
이 목록에서 그대로 인용한 값이다.
