# CR-009 Web-first Scope and Guest Search Evidence

Date: 2026-08-02
Status: PASS

## Outcome

The active product channels are now `REGISTERED_WEB`, `GUEST_WEB`, `BUYER_WEB`, and
`ADMIN_PARTNER_WEB`. Dedicated kiosk hardware, runtime, deployment, configuration, and new feature
work are excluded from MVP/v1.x. QR codes are ordinary guest-web entry links.

Existing kiosk source, routes, records, and handoff compatibility are retained but inactive. This
avoids an unversioned breaking OpenAPI/database removal and provides a reversible rollback path.
Root lint, typecheck, test, and build scripts exclude `backju-kiosk`.

## Guest web implementation

- Added `/explore` as a no-login mobile-first natural-language search route.
- The start page no longer creates a profile session before anonymous browsing.
- Added typed `POST /api/v1/search` client contracts with `channel=WEB` fixed by the client.
- Results expose approved exhibitor name, booth, public summary/products, grounded reason, concepts,
  and backend operating status. Detail links use the existing public booth route.
- Empty search results render server clarification options; service/config errors are explicit.
- Missing or malformed `NEXT_PUBLIC_EVENT_ID` fails closed before sending an invalid API request.

No score formula, retrieval policy, approval filter, OpenAPI path, database schema, or contact-data
rule changed. The existing common catalog-search facade remains authoritative.

## Verification

- Clean NTFS workspace frozen pnpm install: PASS
- Active root lint (`apps/user-web`, `apps/admin`): PASS
- Active root typecheck (`apps/user-web`, `apps/admin`, root Netlify TypeScript): PASS
- Active root production build: PASS
- Root deterministic engine/ontology suite: 54 passed
- Backend suite: 197 passed, 2 pre-existing PostgreSQL integration skips
- `/explore` prerender: PASS, 3.29 kB route, 103 kB first-load JS
- In-app browser semantic DOM: unique labeled searchbox and submit button, quick-search buttons,
  navigation landmarks, and status/alert regions present
- 390 px responsive DOM geometry: content width 390 px, heading/input within 16 px page gutters
- Missing event configuration boundary: explicit user alert, no API transmission
- Browser console errors: 0

The Google Drive workspace continues to make local pnpm linking unreliable; verification used the
documented clean NTFS copy. This is an environment constraint, not a source or build failure.
