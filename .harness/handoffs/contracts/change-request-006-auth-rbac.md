# CR-006 — Authentication, session, RBAC, and administrator MFA

Status: APPROVED
Requested: 2026-08-03
Approved by: explicit user direction to continue the web-first service and the frozen CONTRACT-006 backlog item

## Problem

Protected APIs currently accept caller-supplied identity context such as `X-User-ID`,
`X-Guest-Session-ID`, `X-Tenant-ID`, `X-Event-ID`, and `X-Actor-User-Id`. Database role checks
therefore do not prove who supplied the identifier. The admin web also stores a development role
switcher in `localStorage`; it is a UI test aid, not authentication. RISK-003 consequently blocks
release, personal My Event links, partner administration, and operator approval flows.

This contract freezes the identity boundary that BACKEND-010 and ADMIN-001 must implement. It does
not select a Kakao, email, IdP, or MFA vendor.

## Normative security profile

- Browser applications use a server-managed opaque session in `__Host-meet_ai_session`.
  The cookie is `Secure`, `HttpOnly`, `SameSite=Lax`, `Path=/`, has no `Domain`, and is never exposed
  to JavaScript or copied into browser storage.
- The random session secret contains at least 128 bits of entropy. Only a keyed digest is stored.
  The server rotates it after authentication, MFA, role/scope change, and account recovery, and can
  revoke it immediately.
- Browser requests that mutate state require an origin check and a CSRF token bound to the session.
  `SameSite` is defense in depth and is not the only CSRF control.
- Service-to-service callers may use a short-lived asymmetric JWT. Accepted algorithms and issuers
  are allowlisted; `iss`, `aud`, `sub`, `iat`, `nbf`, `exp`, and `jti` are mandatory. Access JWTs
  expire in at most 10 minutes, are never issued to browser JavaScript, and have no browser refresh
  token. Key rotation must overlap verification keys without accepting an unknown `kid`.
- Authenticated browser sessions have a 12-hour absolute limit and a 60-minute inactivity limit.
  Admin sessions have a 12-hour absolute limit and a 30-minute inactivity limit. A privileged
  publish, export, role change, MFA change, or recovery action requires MFA no older than 15 minutes.
- Guest state uses a separate `__Host-meet_ai_guest` cookie. It is not authentication and cannot
  satisfy buyer, exhibitor, reviewer, or event-admin authorization.
- TLS is mandatory outside local development. Authentication secrets, link tokens, session IDs,
  JWTs, OTPs, WebAuthn assertions, recovery codes, and raw contact values are never logged.

References used for this profile:

- NIST SP 800-63B-4, especially AAL2, authenticator lifecycle, and session management:
  https://pages.nist.gov/800-63-4/sp800-63b.html
- OWASP Session Management Cheat Sheet:
  https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html
- OWASP Multifactor Authentication Cheat Sheet:
  https://cheatsheetseries.owasp.org/cheatsheets/Multifactor_Authentication_Cheat_Sheet.html
- OWASP Forgot Password Cheat Sheet, applied to one-time access links:
  https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html

## Verified principal

Every protected request receives one immutable principal constructed only after session-cookie or
JWT verification. Client input may select a resource but cannot assert identity or scope.

| Claim | Rule |
| --- | --- |
| `subject_type` | `USER` or `SERVICE`; guest context is modeled separately |
| `subject_id` | canonical user/service UUID, derived from the verified credential |
| `session_id` | server session UUID; absent only for service JWTs |
| `tenant_id` | mandatory, derived from the credential and active membership |
| `event_id` | mandatory for event-scoped calls; switching events revalidates membership |
| `role_grants` | server-loaded active grants with `role`, `tenant_id`, and required scope ID |
| `authn_level` | `AAL1` or `AAL2`; it cannot be supplied by an application header |
| `amr` | verified methods such as `magic_link`, `webauthn`, `totp`, or `recovery_code` |
| `authenticated_at` | successful primary-authentication time |
| `mfa_at` | latest successful second-factor time, otherwise null |
| `jti` | mandatory only for JWT principals |

The authorization dependency evaluates authentication, tenant membership, event membership, role,
resource ownership, and MFA freshness in that order. A resource query is always constrained by the
principal scope; authorization must not be implemented as a post-query UI filter.

## Personal access link exchange

Kakao Alimtalk or email may deliver an HTTPS link containing a random opaque token. Delivery is not
proof by itself. `POST /api/v1/auth/magic-links/exchange` consumes the token and creates a restricted
or authenticated server session.

- Generate at least 128 random bits, store only a keyed digest, expire in at most 15 minutes, and
  make the token single-use. Resending invalidates earlier unconsumed tokens for the same purpose.
- Bind the token to tenant, event, intended user, purpose, and an allowlisted same-origin return
  path. Never place user IDs, contact values, roles, or destination URLs in the token.
- The landing page uses `Referrer-Policy: no-referrer`, does not load third-party resources before
  exchange, removes the token from browser history, and never logs it.
- Invalid, expired, consumed, revoked, and unknown tokens all return the same `AUTH_LINK_INVALID`
  response and timing class. Attempts are rate-limited by token digest, account, and network risk.
- A magic link provides only AAL1. It cannot satisfy administrator MFA or fresh-MFA requirements.

## Administrator MFA and recovery

- `EVENT_ADMIN` and `DATA_REVIEWER` grants are dormant until AAL2 is present. A user-verifying
  multi-factor WebAuthn/passkey authenticator is the preferred and required-to-offer
  phishing-resistant method. TOTP is a compatibility second factor only when the independently
  verified primary credential is a different factor class (for example, a password). A magic link
  plus TOTP is still two possession proofs and MUST NOT be labeled AAL2. SMS, email, and Kakao
  messages are not accepted as administrator second factors.
- Challenges are short-lived, session- and purpose-bound, single-use, attempt-limited, and invalidated
  on success. OTP values and WebAuthn assertion bodies are not retained in logs.
- Enrollment, factor replacement, recovery-code regeneration, recovery, and factor removal revoke
  other sessions and create append-only audit events. The account receives an independent security
  notification without secret material.
- Enrollment issues ten one-time recovery codes. Only salted/keyed digests are stored; displaying
  the codes is a one-time action. Regeneration invalidates all previous codes.
- If no factor or recovery code remains, recovery requires documented identity verification and
  approval by two distinct platform administrators. The requester cannot approve their own recovery.
  Security questions and support-operator role switching are prohibited.
- `EXHIBITOR_ADMIN` may use AAL1 for own-company drafts and submissions. It needs fresh AAL2 if a
  later policy grants a privileged cross-company or export capability; this contract grants none.

## RBAC and resource policy

The API role vocabulary is frozen as `EVENT_ADMIN`, `DATA_REVIEWER`, and `EXHIBITOR_ADMIN` for the
admin/partner surface. Existing persistence values are migration aliases only: an `OPERATOR` row
must resolve to an explicit event role, and an `EXHIBITOR` row may resolve to `EXHIBITOR_ADMIN` only
with the matching `exhibitor_id`. A raw `ADMIN` row never bypasses event policy automatically.

| Capability | EVENT_ADMIN | DATA_REVIEWER | EXHIBITOR_ADMIN |
| --- | :---: | :---: | :---: |
| View event operations and review queues | event | event | own company only |
| Edit event/booth configuration | yes | no | no |
| Import registration/exhibitor/product data | yes | no | no |
| Review exhibitor/product/AI evidence | yes | yes | own draft/evidence only |
| Approve, reject, publish, or suspend public data | yes | yes | no |
| Edit any exhibitor/product | yes | yes, review correction only | no |
| Edit and submit own exhibitor/product/trade data | yes | yes | yes |
| View audit metadata | event | event review activity | own activity only |
| Manage roles or MFA policy | yes, fresh MFA | no | no |
| Export private operational data | yes, explicit export grant + fresh MFA | no | no |

`EVENT_ADMIN` and `DATA_REVIEWER` require AAL2 for every protected admin operation. Frontend role
gates are presentation only; the backend repeats every capability and resource-scope check.

Contact disclosure remains stricter than role membership. Buyer contact details are available only
to an authenticated `EXHIBITOR_ADMIN` assigned to the meeting's exhibitor after that exhibitor has
accepted the meeting. Event administrators and reviewers do not receive a contact-disclosure
override. Denied cross-tenant, cross-event, cross-exhibitor, and pre-acceptance lookups return the
same forbidden/not-found policy and do not reveal whether the resource exists.

## OpenAPI security and error behavior

- `BrowserSession` and `BearerJWT` are alternative authenticated security schemes.
- `GuestSession` is explicitly non-authenticating and is allowed only where a route declares guest
  use. Public catalog and natural-language search remain anonymously accessible.
- Missing, malformed, expired, revoked, wrong-issuer, or wrong-audience credentials return 401.
  Bearer failures include `WWW-Authenticate: Bearer` without validation detail.
- A verified principal with insufficient tenant/event/resource role or MFA returns 403. Responses
  never echo credential claims, token contents, contact values, or database identifiers not already
  supplied safely by the client.
- Authentication endpoints use the schemas and error codes published in `openapi.json` and
  `error-codes.yaml`.

## Trusted-header transition

The following inputs are deprecated as identity assertions: `X-User-ID`, `X-Guest-Session-ID`,
`X-Tenant-ID`, `X-Event-ID`, and `X-Actor-User-Id`.

1. BACKEND-010 introduces the verified-principal dependency and makes it the default for every
   protected route.
2. A temporary compatibility adapter may run only when `ALLOW_TRUSTED_IDENTITY_HEADERS=true`, which
   defaults to false. It must be behind an authenticated trusted proxy, strip all client-provided
   copies, and translate a verified proxy assertion into the same principal model. It is forbidden
   in production and cannot assert AAL2.
3. `X-Profile-ID` and `X-Visit-Session-ID` may remain resource selectors, but the selected resource
   must belong to the verified principal. Signed site-context headers may add request integrity but
   cannot create a user/admin principal.
4. Before G3, the compatibility flag is false in every release environment, raw identity-header
   tests are removed or converted to session/JWT fixtures, and an automated test proves spoofed
   headers cannot change principal, tenant, event, role, or MFA state.

## Audit and privacy

Record successful/failed authentication class, session creation/rotation/revocation, MFA lifecycle,
role/scope changes, authorization denial category, recovery approvals, and privileged actions. Use
pseudonymous subject/session IDs and request IDs; never record secrets or raw contact data. Retention
follows the event privacy policy and is not extended by this contract.

## Acceptance evidence for downstream tasks

BACKEND-010 is complete only when common dependencies enforce this principal and route policy,
MFA/recovery audit tests pass, and direct identity-header spoofing is rejected. ADMIN-001 is complete
only when the development session switcher is unavailable in production, no credential is stored in
`localStorage`, and role menus reflect—but do not replace—the backend decision.

The current `identity.authentication_method` persistence enum does not include WebAuthn, TOTP, or
recovery-code material. BACKEND-010 must therefore add a reviewed migration/secure credential-store
adapter and expand its owned paths before claiming MFA enrollment or recovery complete. Storing
these secrets in the existing generic JSON fields, admin `localStorage`, or plaintext is prohibited.

## Rollback

Remove the new auth endpoints and security schemes only before any personal link or protected client
uses them. Rolling back to caller-supplied identity headers is prohibited for staging or production;
if authentication is unavailable, fail protected routes closed while public catalog/search remain
available.
