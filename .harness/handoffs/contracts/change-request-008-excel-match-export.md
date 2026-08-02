# CR-008 — 사전등록자별 Top-N 참여기업 XLSX export

Status: APPROVED
Requested: 2026-08-02
Approved by: active Codex task continuation after the user accepted the Excel matching direction

## Problem

CR-007은 사전등록자·참여기업 XLSX를 정본 import 계약으로 변환하지만, 운영자가 import된
사전등록자별 추천 실행 상태와 Top-N 참여기업을 한 파일로 검토할 수 있는 출력 계약이 없다.
원본 XLSX끼리 별도 점수식을 계산하면 승인·동의·Hard Filter·공통 facade를 우회하게 된다.

## Contract change

- Add `POST /api/v1/admin/imports/excel/matches`.
- JSON request fields: `tenant_id`, `event_id`, `source_system_code`, one to 100 opaque
  `source_record_ids`, and `top_n` from 1 to 10.
- Success response is
  `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` using workbook schema
  `meet-ai-batch-match-export-v1.0`.
- Each requested source record executes the existing `EXHIBITOR` recommendation pipeline. The
  workbook contains a summary, ranked matches, and per-record processing/audit status.
- A profile that is missing, lacks required consent/age confirmation, targets a closed event, or has
  no eligible candidate is not silently relaxed; its stable error code is exported in the status
  sheet.

## Safety

- Only canonical imported profiles and the existing approved/active catalog are queried.
- The existing request validator, Hard Filter, scoring facade, explanation policy, and result store
  remain the only recommendation path.
- Output contains the operator-supplied opaque source record ID, public exhibitor fields, scores,
  allowlisted reasons, policy versions, eligibility IDs, and fingerprints. Names, phone numbers,
  email addresses, and raw profile attributes are excluded.
- The endpoint is an ADMIN contract. The current repository-wide authentication gap remains
  `BACKEND-010`; this change does not claim production authorization readiness.
- Request size is capped at 100 profiles and 10 results per profile. Larger asynchronous jobs remain
  a worker/operations follow-up.

## Rollback

Remove the route, request schema, batch matching service, workbook renderer, and associated tests.
CR-007 import and the ordinary recommendation/search contracts remain unchanged.
