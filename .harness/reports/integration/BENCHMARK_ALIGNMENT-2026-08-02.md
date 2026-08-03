# Benchmark Alignment - 2026-08-02

Input: user-provided executive summary,
`/Users/ppp/.codex/attachments/1535af83-db53-4e5d-bc0d-019b026d9530/pasted-text.txt`.

Status: reviewed as supporting evidence. It does not override the frozen project
contracts in `docs/redesign-v2/00-master-spec-v1.md` and `.harness/contracts/**`.

## Aligned Decisions

- Treat domestic public exhibition examples as digital matching operations, not as
  proven AI hyper-personalization implementations unless AI/model details are
  explicitly disclosed.
- Keep the MVP recommendation engine deterministic: approved-data candidates,
  hard filters before ranking, BM25/vector hybrid retrieval, explicit profile/current
  query signals, and reason templates grounded in approved fields.
- Keep buyer matching bilateral: buyer-to-exhibitor and exhibitor-to-buyer fit should
  be represented separately before any mutual score or final recommendation tier.
- Keep `UNKNOWN` out of mandatory-condition pass decisions; show it as "needs
  confirmation" instead of treating it as positive.
- Keep kiosk as an anonymous exploration and QR handoff surface. Do not add login,
  phone, email, address, or signup input to the kiosk.
- Keep AI structuring behind human approval. No AI synonym/category/exhibitor
  extraction should be published automatically.
- Keep event-time personalization to session features, recent behavior, and cache
  invalidation. Do not add live model retraining to the MVP.
- Validate by offline gold set, staff rehearsal, limited pilot, feature flags, and
  expansion only after privacy, hard-filter, QR, and residual-session guardrails pass.

## Immediate Implementation Impact

- Reinforces `BAC-005`: anonymous `profile.guest_session`, short-lived QR handoff,
  no PII input, no new QR table.
- Reinforces existing security/privacy gates: kiosk residual data must remain a
  release blocker, and QR success plus session reset should be included in pilot
  validation.
- No new scope is accepted from the benchmark document. SaaS integrations, managed
  recommenders, cross-encoder reranking, learning-to-rank, multi-event transfer,
  advanced A/B infrastructure, and real-time model learning remain v2 or later
  candidates that require separate change control.
