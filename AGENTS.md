# Project implementation contract

## Required design baseline

Before changing architecture, data models, AI behavior, API contracts, or user flows, review the shared ChatGPT design thread:

- https://chatgpt.com/share/6a6d8239-5d0c-83ee-a5b5-7505c996e874

The page is larger than ordinary text fetch limits. If a tool cannot return it directly, inspect the page through a browser session or decode the page's serialized current-branch conversation. Do not treat a failed lightweight fetch as evidence that the reference is unavailable.

Apply its transferable design principles to this exhibition domain; do not copy the source thread's unrelated research-platform entities.

Mandatory invariants:

1. Start as a modular monolith and add service boundaries only from measured operational need.
2. Keep canonical business records separate from user, AI, and review overlays.
3. Version immutable published artifacts; changes create a new version rather than rewriting history.
4. Put external AI and integration providers behind adapters.
5. Store provenance, evidence references, review state, and append-only activity needed to reproduce decisions.
6. Include observability, retry/idempotency, recovery, privacy, and operator review in the design—not as later add-ons.
7. AI output is a proposal. Deterministic validation and user/operator confirmation govern hard constraints and canonical data.

Record any deliberate exception in the relevant design document before implementing it.

## Delivery

After an implementation unit passes relevant checks, commit it intentionally and push it to the `exhibition` Git remote unless the user says otherwise. Never include secrets, local dependency directories, or unrelated workspace changes.
