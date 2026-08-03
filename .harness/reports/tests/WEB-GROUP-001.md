# WEB-GROUP-001 Test Report

Date: 2026-08-03

## Result

PASS.

## Verification

- `cd apps/user-web && npm run lint`
  - passed.
- `cd apps/user-web && npm test`
  - 5 test files passed.
  - 12 tests passed.
- `cd apps/user-web && npm run build`
  - passed.
  - API-connected routes are dynamic: `/home`, `/recommendations`, `/search`,
    `/favorites`, `/companies/[companyId]`, `/buyer-matching`, `/my`.
- Playwright smoke on `http://localhost:3310`
  - `/home` rendered with API/fallback banner.
  - `/search?q=목재&mode=GUEST_WEB` rendered fallback result and guest mode selector.
  - mobile 390x844 search viewport visually checked, no obvious text overlap.
  - `/companies/11111111-1111-4111-8111-111111111111` rendered UUID recommendable fallback detail.
  - "관심 저장" button toggled to pressed saved state in local fallback mode.

## Notes

- Local backend was not running during Playwright smoke, so UI exercised the documented fallback path.
- API request shape is covered by `apps/user-web/tests/api-client.test.ts` with mocked `fetch`.
