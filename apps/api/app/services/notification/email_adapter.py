"""EMAIL delivery adapter interface for the notification pipeline.

WAVE 2E BACKEND-NOTIFICATION. Per this track's task spec: "Implement the email path behind a
minimal Adapter interface with a no-op/fake default (no real SMTP wiring required for MVP -
note this limitation in your report)." This module is that boundary.

Why the adapter never resolves a real email address itself
------------------------------------------------------------
``identity.user_identity.email_enc`` holds the only real address, and ``app/db/base.py``'s
module docstring is explicit: "identity와 audit 스키마는 일반 서비스 역할의 직접 조회를
금지한다" (identity/audit schemas forbid direct query by an ordinary service role). This module
therefore only ever receives ``recipient_user_id`` - resolving that to a real deliverable
address (decrypting identity.user_identity.email_enc through whatever KMS/authorized path a
future identity-access track provides) is out of scope for this track and is the main reason
no real adapter ships here.

MVP limitation (call this out in the final report)
------------------------------------------------------
``NoopEmailAdapter`` never actually sends anything over the network - there is no SMTP/SES/
SendGrid wiring in this repository yet. It simulates a successful send so the rest of the
pipeline (notification_deliveries/notification_delivery_attempts bookkeeping, retry sweep) can
be exercised end-to-end in tests and in a real deployment without silently no-oping the whole
EMAIL channel forever. Swap in a real implementation of ``EmailAdapter`` (this Protocol) when a
provider is chosen; nothing else in this package needs to change.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class EmailSendResult:
    success: bool
    #: Safe, application-facing message only - never a raw provider exception/stack trace
    #: (same rule this repo applies to integration.sync_row_error.error_message).
    error_message: str | None = None


class EmailAdapter(Protocol):
    """Minimal send boundary. Implementations must never raise - always return a result."""

    async def send(
        self, *, recipient_user_id: UUID, subject: str, body: str
    ) -> EmailSendResult: ...


class NoopEmailAdapter:
    """MVP default. See module docstring "MVP limitation" - simulates success, sends nothing."""

    async def send(
        self, *, recipient_user_id: UUID, subject: str, body: str
    ) -> EmailSendResult:
        del recipient_user_id, subject, body
        return EmailSendResult(success=True)


default_email_adapter = NoopEmailAdapter()
