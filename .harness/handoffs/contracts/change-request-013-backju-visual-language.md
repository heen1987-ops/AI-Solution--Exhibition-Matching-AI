# CR-013 — Backju official-site visual language alignment

Status: APPROVED
Requested: 2026-08-03
Approved by: explicit user direction to inspect `https://www.backju.kr/` and apply the same tone,
design elements, and citeable official imagery

## Problem

The active user web delivers the correct My Event, guest-search, personal-link, and matching
boundaries, but its generic orange application shell does not visually connect to the official
2026 대한민국 백주대간 website. The service can therefore feel like a detached product even when
the user arrived from the official event channel.

## Approved scope

- Align the active user-web palette, typography, spacing, borders, navigation, section headings,
  shortcuts, and primary actions with the official site's white, bronze, ivory, mint, blush, and
  light-blue visual system.
- Use the official Backju logo and common sub-page photograph by referencing their public official
  URLs. Keep a source record and visible image credit; do not copy binaries into the repository.
- Apply the language first to the global shell, My Event delivery surface, recommendation cards,
  and anonymous guest search.
- Preserve responsive layout, keyboard focus, 44px tap targets, text contrast, reduced motion, and
  semantic navigation.

## Non-goals and retained boundaries

- No matching formula, API, data model, recommendation snapshot, personal-link, notification,
  approval, or authorization behavior changes.
- No official-site registration form, content, tracking script, carousel, social embed, or
  dedicated kiosk behavior is copied.
- The remote image references do not imply a general redistribution license. Production operators
  must confirm continuing publication permission before launch or replace them with approved local
  campaign assets.

## Rollback

Revert the visual tokens and component class/markup changes. All user flows and API contracts remain
compatible because this change is presentation-only.
