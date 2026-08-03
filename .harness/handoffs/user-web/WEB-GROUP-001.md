# WEB-GROUP-001 User-Web Handoff

상태: DONE

## 구현

- `apps/user-web/lib/api-client.ts`
  - API base URL과 MeetAI 헤더 컨텍스트를 읽는 API-first loader 추가.
  - `loadProfile`, `loadRecommendations`, `loadFavorites`, `loadBuyerMatches`,
    `loadCompanyById`, `searchCompanies` 구현.
  - `REGISTERED_WEB`/`GUEST_WEB`/`BUYER_WEB` 검색 채널과 user type 헤더를 분리.
  - `GUEST_WEB` 검색은 `/api/v1/guest/sessions` 생성 후 `/api/v1/search`를 호출.
  - API가 없거나 인증 컨텍스트가 부족하면 동일 UI 타입의 fallback 데이터를 반환.
- `apps/user-web/app/(screens)/**`
  - 홈, 추천, 검색, 관심목록, 업체 상세, 바이어 매칭, MY 화면을 실제 API loader로 전환.
  - API 화면을 `force-dynamic`으로 고정해 빌드 시점 fallback 정적화를 방지.
- `apps/user-web/app/(screens)/companies/[companyId]/SaveFavoriteButton.tsx`
  - 공개 환경변수가 있으면 `POST /api/v1/favorites`와
    `DELETE /api/v1/favorites/{saved_recommendable_id}`를 호출.
  - 로컬 API 컨텍스트가 없으면 데모 상태 토글로 유지.
- `apps/user-web/components/MockDataBanner.tsx`
  - 실제 API/fallback 데이터 출처 배너를 분리.
- `apps/user-web/.env.example`
  - 실제 API 우선 정책과 로컬 개발용 MeetAI 헤더 환경변수를 문서화.

## 동작 계약

- 등록 사용자 흐름은 `/profile/me`, `/recommendations`, `/favorites`, `/search`를 우선 사용한다.
- 게스트 웹 흐름은 전용 앱/키오스크 없이 `/guest/sessions`와 `/search`로 검색한다.
- 바이어 흐름은 `/buyer/matches`를 우선 사용하고, 기존 렌더링 규칙대로 상담 확정 전 연락처를 노출하지 않는다.
- 추천/검색 결과가 `recommendable_id`만 제공하는 경우에도 UUID 상세 URL은 승인 대상 fallback으로 열려 관심 저장 버튼을 사용할 수 있다.

## 검증

- `cd apps/user-web && npm run lint`
- `cd apps/user-web && npm test`: 5 files, 12 tests passed.
- `cd apps/user-web && npm run build`
- Playwright smoke:
  - `/home`
  - `/search?q=목재&mode=GUEST_WEB`
  - `/companies/11111111-1111-4111-8111-111111111111`
  - mobile viewport 390x844 검색 화면 시각 확인.

## 후속

- `ADM-GROUP-001`: 관리자 승인·통계 화면을 BAC-GROUP API에 연결.
- `QAS-GROUP-001`: 실제 백엔드/DB가 떠 있는 환경에서 등록·게스트·바이어 웹 E2E를 통합 검증.
