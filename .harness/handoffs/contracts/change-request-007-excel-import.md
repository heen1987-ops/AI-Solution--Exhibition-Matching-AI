# CR-007 — 사전등록자·참여기업 XLSX import adapter

Status: APPROVED
Requested: 2026-08-02
Approved by: explicit user direction in the active Codex task

## Problem

운영 현장에서 사전등록자와 참여기업 원천자료는 XLSX로 전달될 가능성이 높지만 현재 API는
정규화된 JSON import만 받는다. 브라우저 자연어 검색은 이미 `/api/v1/search`가 처리하므로
엑셀을 별도 매칭 정책으로 만들지 않고 기존 정본·승인·Hard Filter·공통 엔진 앞단의 입력
adapter로 추가해야 한다.

## Contract change

- Add `POST /api/v1/admin/imports/excel`.
- Request body is raw `.xlsx` bytes (`application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`).
- Query parameters: `tenant_id`, `event_id`, `source_system_code`, `dry_run` (default `true`).
- Workbook schema version: `meet-ai-excel-import-v1.0`.
- Recognized input sheets: `사전등록자`, `참여기업`; at least one non-empty valid row is required.
- Response reports sheet-level valid/error counts and, when `dry_run=false`, delegates valid rows to
  the existing visitor/exhibitor import jobs.

## Safety

- `.xlsx` only; maximum 5 MiB and 1,000 non-empty rows per input sheet.
- Formula cells, macro-enabled formats, unknown headers, duplicate source IDs, unknown/nonassignable
  ontology codes, and invalid field types fail closed at row/workbook validation.
- Row errors never include cell values, names, phone numbers, email addresses, or exception text.
- User identity/contact data remains ingestion-only and is not sent to the matching engine.
- Imported exhibitors remain `APPLIED`; existing operator approval and public-index filters still
  govern eligibility.
- `UNKNOWN` stays distinct from false/mismatch. Empty optional cells remain missing.

## Rollback

Remove the new route, response schemas, XLSX adapter, and `openpyxl` dependency. Existing JSON import
and natural-language search contracts remain unchanged.
