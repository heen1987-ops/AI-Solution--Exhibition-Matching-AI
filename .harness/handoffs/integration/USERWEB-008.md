# USERWEB-008 Handoff — Backju visual language alignment

Date: 2026-08-03
Status: DONE
Contract: CR-013

## Delivered

- Inspected the official `backju.kr` home and visitor information surfaces in the in-app browser.
- Replaced the generic orange shell with the observed bronze, ivory, plum, mint, blush, and light-blue
  visual system while retaining accessible focus, text contrast, and 44px tap targets.
- Added an official-logo lockup to the global header and a bronze active marker to the five-tab
  mobile navigation.
- Applied the official common sub-page photograph, contrast treatment, thin grid line, source credit,
  pastel shortcuts, editorial section rules, capsule actions, and restrained card elevation to My
  Event and anonymous guest search.
- Recorded remote-asset provenance in `apps/user-web/BRAND_ASSETS.md`; no official binary was copied
  into the repository.

## Boundaries retained

No matching calculation, score, reason, snapshot delivery, personal-link, authorization, approved
catalog, Alimtalk, API, database, or kiosk behavior changed.

## Verification

- Clean NTFS `pnpm install --frozen-lockfile --ignore-scripts`: PASS.
- User web Vitest: 5 passed.
- User web TypeScript: PASS.
- User web lint: PASS with zero warnings/errors.
- User web production build: PASS, 21 static/dynamic routes generated.
- Browser: official logo and hero URLs resolved; semantic My Event and guest-search landmarks,
  three shortcuts, and five bottom navigation links present; zero console warning/error entries.
- `git diff --check`: PASS before harness completion recording.

## Production note

The official footer states all rights reserved. The current implementation references and visibly
credits first-party URLs as explicitly requested; release operations must still confirm continuing
campaign permission/availability or replace them with operator-approved local assets.
