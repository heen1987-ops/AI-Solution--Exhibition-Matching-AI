"""바이어<->업체 매칭 상담 도메인 규칙 + 오케스트레이션.

이 모듈은 상담 표면(``app/api/v1/routers/meetings.py``) 하나가 공유하는 도메인 규칙을
담는다. 통합 전 worktree(WAVE 2C)에는 같은 ``interaction.meeting`` 행을 쓰는 두 번째
라우터(``meeting_buyer_extension.py``)가 있었지만, 그 모듈 자신의 docstring이 "최종적으로는
``/meetings`` 하나의 표면만 남아야 한다"고 명시했다. 통합 저장소는 그 지시를 따라 두 번째
라우터를 등록하지 않고, 그 라우터가 쓰던 서비스 계층만 여기로 옮겼다.

두 부분으로 나뉜다.

1. 순수 도메인 규칙 - :func:`contact_reveal_allowed`, :func:`validate_transition`.
   SQLAlchemy에 의존하지 않으므로 DB 없이 그대로 단위 테스트할 수 있다.
2. 오케스트레이션 - :class:`MeetingGateway` 프로토콜에만 의존하는 상담 생성/수락/거절/
   변경제안/취소 함수들. 프로덕션에서는 ``sqlalchemy_gateway.SqlAlchemyMeetingGateway``가,
   테스트에서는 인메모리 gateway가 그 프로토콜을 구현한다. 덕분에 1635줄짜리 라우터가
   커버하지 못하던 상태 머신·연락처 게이트·크로스테넌트 차단을 Postgres 없이 검증할 수
   있다.

연락처 공개 게이트
------------------
:func:`contact_reveal_allowed` 가 "연락처는 언제 공개되는가"에 대한 단일 진실 공급원이다.
라우터/직렬화 계층은 이 함수가 True를 돌려주기 전에는 어떤 연락처 필드도 채우지 않는다.
통합 전 main의 ``meetings.py``는 세 조건 중 두 개(확정 + 바이어 동의)만 확인했고
``MeetingContactShare``에는 업체측 opt-in 컬럼 자체가 없었다 - 즉 바이어 동의만으로
이름/전화/이메일이 공개되는 실제 불변식 위반이었다. 이 함수가 그 결함을 닫는다.

암호화
------
WAVE 2C 원본(worktree)의 ``_encrypt_text``/``_decrypt_text``는 평문 UTF-8 인코딩
placeholder였다. 통합 저장소는 ``app/core/auth.py``의 AESGCM 봉투 암호화
(``encrypt_secret``/``decrypt_secret``, InvalidTag에 fail-closed)를 쓴다. 그 두 함수의
정본이 :func:`encrypt_meeting_text` / :func:`decrypt_meeting_text` 이며 ``meetings.py``도
같은 구현을 재사용한다 - 한 상담 레코드가 어느 코드 경로로 쓰였든 같은 형식으로 저장된다.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol

from cryptography.exceptions import InvalidTag

from app.core.auth import decrypt_secret, encrypt_secret
from app.core.config import get_settings
from app.models.consent import AuditLog
from app.models.exhibitor import ExhibitorParticipation, ExhibitorStaff, Product
from app.models.identity import UserAccount, UserIdentity
from app.models.meeting import (
    MEETING_CONFIRMED_STATUS,
    MEETING_REJECT_REASON_CODES,
    AvailabilitySlot,
    MeetingContactShare,
    MeetingRequest,
    MeetingSlotRequest,
    MeetingStatusHistory,
)
from app.models.profile import UserProfile

__all__ = [
    "BUYER_MATCH_CONTACT_FIELDS",
    "CONTACT_SHARE_PURPOSE",
    "BuyerMeetingRequestInput",
    "MeetingBuyerMatchError",
    "MeetingForbiddenError",
    "MeetingGateway",
    "MeetingInvalidTransitionError",
    "MeetingNotFoundError",
    "MeetingSlotConflictError",
    "MeetingValidationError",
    "MeetingVersionConflictError",
    "accept_meeting",
    "build_contact_view",
    "cancel_buyer_meeting",
    "contact_reveal_allowed",
    "create_meeting_request",
    "decrypt_meeting_text",
    "encrypt_meeting_text",
    "get_buyer_meeting",
    "get_partner_meeting",
    "list_buyer_meetings",
    "list_partner_meetings",
    "propose_alternate",
    "reject_meeting",
    "select_alternate",
    "validate_transition",
]


# --------------------------------------------------------------------------
# 오류 타입 — 라우터 계층이 HTTP 상태/오류코드로 매핑한다.
# --------------------------------------------------------------------------


class MeetingBuyerMatchError(Exception):
    """이 모듈이 던지는 모든 오류의 공통 베이스."""


class MeetingNotFoundError(MeetingBuyerMatchError):
    pass


class MeetingForbiddenError(MeetingBuyerMatchError):
    """존재하지만 요청 주체의 소유가 아니다 - 크로스테넌트 접근 차단."""


class MeetingVersionConflictError(MeetingBuyerMatchError):
    pass


class MeetingInvalidTransitionError(MeetingBuyerMatchError):
    def __init__(self, *, current_status: str, action: str) -> None:
        super().__init__(
            f"cannot apply action {action!r} to meeting in status {current_status!r}"
        )
        self.current_status = current_status
        self.action = action


class MeetingValidationError(MeetingBuyerMatchError):
    def __init__(self, message: str, *, field: str) -> None:
        super().__init__(message)
        self.field = field


class MeetingSlotConflictError(MeetingBuyerMatchError):
    """요청/제안한 시간대 중 어느 것도 점유하지 못했다."""


# --------------------------------------------------------------------------
# 상태 머신 (app/models/meeting.py의 MEETING_STATUSES를 그대로 재사용)
# --------------------------------------------------------------------------

#: 액션 이름 -> 이 액션이 허용되는 현재 상태 집합.
_ALLOWED_SOURCE_STATUSES: dict[str, tuple[str, ...]] = {
    "ACCEPT": ("requested", "counter_proposed"),
    "REJECT": ("requested", "counter_proposed"),
    "PROPOSE_ALTERNATE": ("requested",),
    "BUYER_SELECT_ALTERNATE": ("counter_proposed",),
    # wireframes 6.2절: draft/requested/accepted/counter_proposed 상태에서 취소 가능.
    "BUYER_CANCEL": ("draft", "requested", "accepted", "counter_proposed"),
}


def validate_transition(current_status: str, action: str) -> None:
    """``action``이 ``current_status``에서 허용되지 않으면 예외를 던진다.

    completed/rejected/cancelled/no_show는 어떤 액션의 허용 집합에도 없으므로, 이 함수
    하나가 "완료된 상담은 재개될 수 없다"는 요구사항을 액션 종류와 무관하게 만족한다.
    """

    allowed = _ALLOWED_SOURCE_STATUSES.get(action, ())
    if current_status not in allowed:
        raise MeetingInvalidTransitionError(current_status=current_status, action=action)


def contact_reveal_allowed(
    *, meeting_status: str, contact_share: MeetingContactShare | None
) -> bool:
    """"가장 중요한 규칙" — 세 조건을 모두 만족해야만 연락처를 공개한다.

    1. meeting.status가 확정 상태(accepted)다.
    2. 바이어가 동의했다(contact_share가 존재하고 accepted_at이 채워져 있다).
    3. 업체측이 이 상담에 한해 연락처 공유를 명시적으로 켰다(exhibitor_enabled_at이
       채워져 있다).

    셋 중 하나라도 빠지면 무조건 False다 - 이 함수가 이 정책의 단일 진실 공급원이며,
    라우터/직렬화 계층은 이 함수의 결과 없이는 연락처 필드를 채우지 않는다.
    """

    return (
        meeting_status == MEETING_CONFIRMED_STATUS
        and contact_share is not None
        and contact_share.accepted_at is not None
        and contact_share.exhibitor_enabled_at is not None
    )


# --------------------------------------------------------------------------
# AEAD 봉투 암호화 — 통합 저장소의 정본.
# worktree의 평문 UTF-8 placeholder는 의도적으로 옮기지 않았다: 그 경로로 쓰인 값을
# main의 fail-closed 복호화기가 읽으면 언제나 None이 되어 데이터가 조용히 사라진다.
# --------------------------------------------------------------------------


def encrypt_meeting_text(value: str | None, *, purpose: str) -> bytes | None:
    if value is None:
        return None
    return encrypt_secret(value, purpose=purpose, settings=get_settings())


def decrypt_meeting_text(value: bytes | None, *, purpose: str) -> str | None:
    if value is None:
        return None
    try:
        return decrypt_secret(value, purpose=purpose, settings=get_settings()).decode(
            "utf-8"
        )
    except (InvalidTag, ValueError, UnicodeDecodeError):
        # Fail closed: legacy/plaintext or corrupt data must never be echoed.
        return None


#: buyer 흐름에서 "연락처 공유 동의"가 고정으로 요청하는 필드 집합. 기존
#: app/schemas/meeting.py의 ALLOWED_CONTACT_SHARE_FIELDS와 호환되는 하위집합을 쓴다.
#: title/affiliation은 identity 도메인에 컬럼이 없어 제외한다(ContactView 참고).
BUYER_MATCH_CONTACT_FIELDS: tuple[str, ...] = ("NAME", "PHONE", "BUSINESS_EMAIL")

#: "contact_share_consent boolean"을 기존 consent_policy 기반 흐름과 연결하기 위한 잠정
#: purpose 네임스페이스. meetings.py의 ``_MEETING_CONTACT_SHARE_PURPOSE``와 동일한 값이다.
CONTACT_SHARE_PURPOSE = "MEETING_CONTACT_SHARE"


# --------------------------------------------------------------------------
# Gateway 프로토콜 — 오케스트레이션 함수가 의존하는 유일한 인터페이스.
# --------------------------------------------------------------------------


class MeetingGateway(Protocol):
    async def get_profile(self, profile_id: uuid.UUID) -> UserProfile | None: ...

    async def get_account(self, user_id: uuid.UUID) -> UserAccount | None: ...

    async def get_participation_for_exhibitor(
        self, *, tenant_id: uuid.UUID, event_id: uuid.UUID, exhibitor_id: uuid.UUID
    ) -> ExhibitorParticipation | None: ...

    async def get_participation(
        self, participation_id: uuid.UUID
    ) -> ExhibitorParticipation | None: ...

    async def get_product(self, product_id: uuid.UUID) -> Product | None: ...

    async def get_staff(self, staff_id: uuid.UUID) -> ExhibitorStaff | None: ...

    async def get_identity_by_user_id(self, user_id: uuid.UUID) -> UserIdentity | None: ...

    async def get_meeting(self, meeting_id: uuid.UUID) -> MeetingRequest | None:
        """잠금 없는 조회 (목록/단건 GET용)."""

    async def get_meeting_locked(self, meeting_id: uuid.UUID) -> MeetingRequest | None:
        """``SELECT ... FOR UPDATE``와 동등한 수준의 잠금 조회 (상태 전이용)."""

    async def list_by_buyer(self, buyer_profile_id: uuid.UUID) -> list[MeetingRequest]: ...

    async def list_by_participation(
        self, participation_id: uuid.UUID
    ) -> list[MeetingRequest]: ...

    async def get_slot(self, slot_id: uuid.UUID) -> AvailabilitySlot | None: ...

    async def reserve_slot(
        self, *, slot_id: uuid.UUID, participation_id: uuid.UUID
    ) -> AvailabilitySlot | None:
        """조건부 UPDATE로 원자적으로 점유한다. 실패하면 None."""

    async def release_slot(self, slot_id: uuid.UUID) -> None: ...

    async def get_slot_requests(self, meeting_id: uuid.UUID) -> list[MeetingSlotRequest]: ...

    async def add_slot_request(self, slot_request: MeetingSlotRequest) -> None: ...

    async def get_contact_share(
        self, meeting_id: uuid.UUID
    ) -> MeetingContactShare | None: ...

    async def add_contact_share(self, contact_share: MeetingContactShare) -> None: ...

    async def add_meeting(self, meeting: MeetingRequest) -> None: ...

    async def add_status_history(self, entry: MeetingStatusHistory) -> None: ...

    async def add_audit_log(self, entry: AuditLog) -> None: ...

    async def resolve_topic_concept(
        self, topic_code: str
    ) -> tuple[uuid.UUID, uuid.UUID, str] | None:
        """자유 입력 topic_code를 (taxonomy_version_id, concept_id, 실제 코드)로 해석한다."""

    async def concept_code_for(self, concept_id: uuid.UUID | None) -> str | None:
        """저장된 concept_id를 사람이 읽는 concept_code 문자열로 되돌린다 (응답 직렬화용)."""

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


# --------------------------------------------------------------------------
# 내부 헬퍼
# --------------------------------------------------------------------------


async def _reserve_first_available(
    gateway: MeetingGateway, *, slot_ids: list[uuid.UUID], participation_id: uuid.UUID
) -> AvailabilitySlot:
    for slot_id in slot_ids:
        slot = await gateway.reserve_slot(slot_id=slot_id, participation_id=participation_id)
        if slot is not None:
            return slot
    await gateway.rollback()
    raise MeetingSlotConflictError("none of the requested time slots are available")


async def _release_all_held_slots(gateway: MeetingGateway, meeting: MeetingRequest) -> None:
    released: set[uuid.UUID] = set()
    for row in await gateway.get_slot_requests(meeting.meeting_id):
        if row.status == "SELECTED":
            await gateway.release_slot(row.availability_slot_id)
            released.add(row.availability_slot_id)
            row.status = "WITHDRAWN"
    if meeting.confirmed_slot_id is not None and meeting.confirmed_slot_id not in released:
        await gateway.release_slot(meeting.confirmed_slot_id)


def _record_status_history(
    meeting: MeetingRequest,
    *,
    previous_status: str,
    changed_by_user_id: uuid.UUID | None,
    reason_code: str | None,
) -> MeetingStatusHistory:
    return MeetingStatusHistory(
        meeting_status_history_id=uuid.uuid4(),
        meeting_id=meeting.meeting_id,
        previous_status=previous_status,
        new_status=meeting.status,
        changed_by_user_id=changed_by_user_id,
        reason_code=reason_code,
    )


def _record_audit(
    meeting: MeetingRequest,
    *,
    actor_user_id: uuid.UUID | None,
    actor_role: Literal["BUYER", "EXHIBITOR"],
    action_type: Literal["CREATE", "UPDATE", "VIEW"],
    reason_code: str | None = None,
) -> AuditLog:
    """상태 전이·연락처 공개 이벤트마다 감사로그 1건을 남긴다.

    audit.audit_log 스키마는 app/models/consent.py(meetings.py가 이미 상담 연락처 열람
    로깅에 쓰는 것과 동일한 테이블)를 그대로 재사용한다 - 새 감사로그 테이블을 만들지
    않는다.
    """

    return AuditLog(
        tenant_id=meeting.tenant_id,
        event_id=meeting.event_id,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action_type=action_type,
        resource_type="interaction.meeting",
        resource_id=meeting.meeting_id,
        reason_code=reason_code,
    )


# --------------------------------------------------------------------------
# 바이어 액션
# --------------------------------------------------------------------------


@dataclass
class BuyerMeetingRequestInput:
    exhibitor_id: uuid.UUID
    product_id: uuid.UUID | None
    topic_code: str
    preferred_time_slots: list[uuid.UUID]
    order_scale_code: str | None
    message: str | None
    contact_share_consent: bool


async def create_meeting_request(
    gateway: MeetingGateway, *, buyer_profile_id: uuid.UUID, payload: BuyerMeetingRequestInput
) -> MeetingRequest:
    profile = await gateway.get_profile(buyer_profile_id)
    if profile is None or getattr(profile, "deleted_at", None) is not None:
        raise MeetingForbiddenError("buyer profile not found")
    if profile.user_type != "BUYER":
        raise MeetingValidationError(
            "only BUYER profiles may request a consultation", field="buyer_profile_id"
        )
    if profile.user_id is None:
        raise MeetingForbiddenError("phone verification is required to request a consultation")
    account = await gateway.get_account(profile.user_id)
    if account is None or account.authentication_state not in (
        "PHONE_VERIFIED",
        "ACCOUNT_AUTHENTICATED",
    ):
        raise MeetingForbiddenError("phone verification is required to request a consultation")

    participation = await gateway.get_participation_for_exhibitor(
        tenant_id=profile.tenant_id, event_id=profile.event_id, exhibitor_id=payload.exhibitor_id
    )
    if participation is None or participation.participation_status != "APPROVED":
        raise MeetingNotFoundError("exhibitor participation not found")
    if not participation.consultation_enabled:
        raise MeetingValidationError(
            "this exhibitor is not accepting consultation requests", field="exhibitor_id"
        )

    if payload.product_id is not None:
        product = await gateway.get_product(payload.product_id)
        if not product_belongs_to_participation(product, participation=participation):
            raise MeetingValidationError(
                "product not found for this exhibitor", field="product_id"
            )

    topic_resolved = await gateway.resolve_topic_concept(payload.topic_code)
    if topic_resolved is None:
        raise MeetingValidationError("unknown topic_code", field="topic_code")
    taxonomy_version_id, concept_id, _resolved_code = topic_resolved

    reserved_slot = await _reserve_first_available(
        gateway,
        slot_ids=payload.preferred_time_slots,
        participation_id=participation.participation_id,
    )

    meeting_id = uuid.uuid4()
    now = datetime.now(UTC)
    meeting = MeetingRequest(
        meeting_id=meeting_id,
        tenant_id=profile.tenant_id,
        event_id=profile.event_id,
        buyer_profile_id=profile.profile_id,
        participation_id=participation.participation_id,
        staff_id=reserved_slot.staff_id,
        booth_id=reserved_slot.booth_id,
        taxonomy_version_id=taxonomy_version_id,
        concept_id=concept_id,
        product_id=payload.product_id,
        order_scale_code=payload.order_scale_code,
        message_enc=encrypt_meeting_text(payload.message, purpose="meeting-message"),
        status="requested",
        row_version=0,
        # server_default=func.now()는 실제 DB INSERT를 거쳐야만 채워진다
        # (app/models/meeting.py). 이 함수는 DB 백엔드가 아닌 Gateway와도 함께 쓰이므로
        # (테스트의 인메모리 gateway 포함) 여기서 명시적으로 채운다 - SqlAlchemyMeetingGateway
        # 경로에서는 실제 INSERT 시 서버가 다시 한번 같은 값을 확정한다.
        created_at=now,
        updated_at=now,
    )
    await gateway.add_meeting(meeting)

    for order, slot_id in enumerate(payload.preferred_time_slots, start=1):
        await gateway.add_slot_request(
            MeetingSlotRequest(
                meeting_slot_request_id=uuid.uuid4(),
                meeting_id=meeting_id,
                availability_slot_id=slot_id,
                preference_order=order,
                status="SELECTED" if slot_id == reserved_slot.availability_slot_id else "PENDING",
            )
        )

    if payload.contact_share_consent:
        await gateway.add_contact_share(
            MeetingContactShare(
                meeting_contact_share_id=uuid.uuid4(),
                meeting_id=meeting_id,
                # TODO(동의 정책 상세설계 확정 후): consent_policy_id를 실제 정책 레코드로
                # 채운다 - meetings.py는 이미 consent_policy 조회 경로를 갖고 있다.
                # 여기서는 정책 레코드 조회를 강제하지 않고자 안전한 결정론적 파생 UUID를
                # 임시로 쓴다.
                consent_policy_id=uuid.uuid5(uuid.NAMESPACE_URL, CONTACT_SHARE_PURPOSE),
                shared_fields=list(BUYER_MATCH_CONTACT_FIELDS),
                accepted_at=datetime.now(UTC),
            )
        )

    await gateway.add_status_history(
        _record_status_history(
            meeting,
            previous_status="draft",
            changed_by_user_id=profile.user_id,
            reason_code=None,
        )
    )
    await gateway.add_audit_log(
        _record_audit(
            meeting,
            actor_user_id=profile.user_id,
            actor_role="BUYER",
            action_type="CREATE",
        )
    )
    await gateway.commit()
    return meeting


def product_belongs_to_participation(
    product: Product | None, *, participation: ExhibitorParticipation
) -> bool:
    """상담에 첨부하려는 제품이 이 참가업체의 승인된 제품인지 확인한다.

    ``interaction.meeting``에는 (participation_id, product_id) 복합 FK가 없다 - 애플리케이션
    계층이 이 검사를 대신해야 한다. AGENTS.md 불변조건("미승인 업체/제품 데이터는 공개
    표면에 노출되지 않는다")의 상담 측 대응이기도 하다: 바이어가 공개 카탈로그에서 볼 수
    없는 미승인/삭제된 제품을 상담에 슬쩍 연결하는 경로를 막는다.
    """

    return (
        product is not None
        and product.exhibitor_id == participation.exhibitor_id
        and product.master_approval_status == "APPROVED"
        and getattr(product, "deleted_at", None) is None
    )


async def get_buyer_meeting(
    gateway: MeetingGateway, *, buyer_profile_id: uuid.UUID, meeting_id: uuid.UUID
) -> MeetingRequest:
    meeting = await gateway.get_meeting(meeting_id)
    if meeting is None:
        raise MeetingNotFoundError("meeting not found")
    if meeting.buyer_profile_id != buyer_profile_id:
        # 존재는 하지만 다른 바이어 소유 - 크로스테넌트 차단. 존재 여부를 흘리지 않도록
        # 라우터 계층은 이 예외를 404와 동일하게 취급한다.
        raise MeetingForbiddenError("meeting does not belong to this buyer")
    return meeting


async def list_buyer_meetings(
    gateway: MeetingGateway, *, buyer_profile_id: uuid.UUID
) -> list[MeetingRequest]:
    return await gateway.list_by_buyer(buyer_profile_id)


async def cancel_buyer_meeting(
    gateway: MeetingGateway,
    *,
    buyer_profile_id: uuid.UUID,
    meeting_id: uuid.UUID,
    version: int,
) -> MeetingRequest:
    meeting = await gateway.get_meeting_locked(meeting_id)
    if meeting is None:
        await gateway.rollback()
        raise MeetingNotFoundError("meeting not found")
    if meeting.buyer_profile_id != buyer_profile_id:
        await gateway.rollback()
        raise MeetingForbiddenError("meeting does not belong to this buyer")
    if meeting.row_version != version:
        await gateway.rollback()
        raise MeetingVersionConflictError("stale version")
    validate_transition(meeting.status, "BUYER_CANCEL")

    await _release_all_held_slots(gateway, meeting)
    previous_status = meeting.status
    meeting.status = "cancelled"
    meeting.row_version += 1

    profile = await gateway.get_profile(buyer_profile_id)
    await gateway.add_status_history(
        _record_status_history(
            meeting,
            previous_status=previous_status,
            changed_by_user_id=profile.user_id if profile else None,
            reason_code=None,
        )
    )
    await gateway.add_audit_log(
        _record_audit(
            meeting,
            actor_user_id=profile.user_id if profile else None,
            actor_role="BUYER",
            action_type="UPDATE",
        )
    )
    await gateway.commit()
    return meeting


async def select_alternate(
    gateway: MeetingGateway,
    *,
    buyer_profile_id: uuid.UUID,
    meeting_id: uuid.UUID,
    slot_id: uuid.UUID,
    version: int,
) -> MeetingRequest:
    """counter_proposed에서 바이어가 대안 중 하나를 골라 accepted로 넘어간다."""

    meeting = await gateway.get_meeting_locked(meeting_id)
    if meeting is None:
        await gateway.rollback()
        raise MeetingNotFoundError("meeting not found")
    if meeting.buyer_profile_id != buyer_profile_id:
        await gateway.rollback()
        raise MeetingForbiddenError("meeting does not belong to this buyer")
    if meeting.row_version != version:
        await gateway.rollback()
        raise MeetingVersionConflictError("stale version")
    validate_transition(meeting.status, "BUYER_SELECT_ALTERNATE")

    slot_requests = await gateway.get_slot_requests(meeting.meeting_id)
    matching = [
        row
        for row in slot_requests
        if row.availability_slot_id == slot_id and row.status == "SELECTED"
    ]
    if not matching:
        await gateway.rollback()
        raise MeetingValidationError(
            "slot_id is not one of the proposed alternates", field="slot_id"
        )
    slot = await gateway.get_slot(slot_id)
    if slot is None:
        await gateway.rollback()
        raise MeetingNotFoundError("slot not found")

    previous_status = meeting.status
    meeting.status = "accepted"
    meeting.confirmed_slot_id = slot.availability_slot_id
    meeting.confirmed_start = slot.start_at
    meeting.confirmed_end = slot.end_at
    meeting.row_version += 1

    profile = await gateway.get_profile(buyer_profile_id)
    await gateway.add_status_history(
        _record_status_history(
            meeting,
            previous_status=previous_status,
            changed_by_user_id=profile.user_id if profile else None,
            reason_code=None,
        )
    )
    await gateway.add_audit_log(
        _record_audit(
            meeting,
            actor_user_id=profile.user_id if profile else None,
            actor_role="BUYER",
            action_type="UPDATE",
        )
    )
    await gateway.commit()
    return meeting


# --------------------------------------------------------------------------
# 업체(참가업체) 담당자 액션
# --------------------------------------------------------------------------


async def get_partner_meeting(
    gateway: MeetingGateway, *, staff: ExhibitorStaff, meeting_id: uuid.UUID
) -> MeetingRequest:
    meeting = await gateway.get_meeting(meeting_id)
    if meeting is None:
        raise MeetingNotFoundError("meeting not found")
    if meeting.participation_id != staff.participation_id:
        raise MeetingForbiddenError("meeting does not belong to this exhibitor")
    return meeting


async def list_partner_meetings(
    gateway: MeetingGateway, *, staff: ExhibitorStaff
) -> list[MeetingRequest]:
    return await gateway.list_by_participation(staff.participation_id)


def enable_exhibitor_contact_sharing(
    contact_share: MeetingContactShare | None, *, staff: ExhibitorStaff
) -> MeetingContactShare | None:
    """연락처 공개의 "세 번째 게이트"를 켠다 (업체측 명시적 opt-in).

    바이어가 애초에 동의하지 않았다면(contact_share 행 자체가 없다면) 업체가 "켜기"를
    요청해도 만들어주지 않는다 - 세 조건 중 바이어 동의는 업체가 대신 만들 수 없다.
    """

    if contact_share is None:
        return None
    contact_share.exhibitor_enabled_at = datetime.now(UTC)
    contact_share.exhibitor_enabled_by_staff_id = staff.staff_id
    return contact_share


async def accept_meeting(
    gateway: MeetingGateway,
    *,
    staff: ExhibitorStaff,
    meeting_id: uuid.UUID,
    slot_id: uuid.UUID,
    version: int,
    enable_contact_sharing: bool,
) -> MeetingRequest:
    meeting = await gateway.get_meeting_locked(meeting_id)
    if meeting is None:
        await gateway.rollback()
        raise MeetingNotFoundError("meeting not found")
    if meeting.participation_id != staff.participation_id:
        await gateway.rollback()
        raise MeetingForbiddenError("meeting does not belong to this exhibitor")
    if meeting.row_version != version:
        await gateway.rollback()
        raise MeetingVersionConflictError("stale version")
    validate_transition(meeting.status, "ACCEPT")

    slot_requests = await gateway.get_slot_requests(meeting.meeting_id)
    existing = next(
        (row for row in slot_requests if row.availability_slot_id == slot_id), None
    )
    if existing is not None and existing.status == "SELECTED":
        slot = await gateway.get_slot(slot_id)
        if slot is None:
            await gateway.rollback()
            raise MeetingNotFoundError("slot not found")
    else:
        slot = await gateway.reserve_slot(
            slot_id=slot_id, participation_id=staff.participation_id
        )
        if slot is None:
            await gateway.rollback()
            raise MeetingSlotConflictError("requested slot is no longer available")
        if existing is None:
            await gateway.add_slot_request(
                MeetingSlotRequest(
                    meeting_slot_request_id=uuid.uuid4(),
                    meeting_id=meeting.meeting_id,
                    availability_slot_id=slot_id,
                    preference_order=len(slot_requests) + 1,
                    status="SELECTED",
                )
            )
        else:
            existing.status = "SELECTED"

    for row in slot_requests:
        if row.status == "SELECTED" and row.availability_slot_id != slot_id:
            await gateway.release_slot(row.availability_slot_id)
            row.status = "DECLINED"

    previous_status = meeting.status
    meeting.status = "accepted"
    meeting.staff_id = staff.staff_id
    meeting.confirmed_slot_id = slot.availability_slot_id
    meeting.confirmed_start = slot.start_at
    meeting.confirmed_end = slot.end_at
    meeting.row_version += 1

    if enable_contact_sharing:
        enable_exhibitor_contact_sharing(
            await gateway.get_contact_share(meeting.meeting_id), staff=staff
        )

    await gateway.add_status_history(
        _record_status_history(
            meeting,
            previous_status=previous_status,
            changed_by_user_id=staff.user_id,
            reason_code=None,
        )
    )
    await gateway.add_audit_log(
        _record_audit(
            meeting, actor_user_id=staff.user_id, actor_role="EXHIBITOR", action_type="UPDATE"
        )
    )
    await gateway.commit()
    return meeting


async def reject_meeting(
    gateway: MeetingGateway,
    *,
    staff: ExhibitorStaff,
    meeting_id: uuid.UUID,
    reason_code: str,
    version: int,
) -> MeetingRequest:
    if reason_code not in MEETING_REJECT_REASON_CODES:
        raise MeetingValidationError(
            f"unsupported reason_code: {reason_code}", field="reason_code"
        )

    meeting = await gateway.get_meeting_locked(meeting_id)
    if meeting is None:
        await gateway.rollback()
        raise MeetingNotFoundError("meeting not found")
    if meeting.participation_id != staff.participation_id:
        await gateway.rollback()
        raise MeetingForbiddenError("meeting does not belong to this exhibitor")
    if meeting.row_version != version:
        await gateway.rollback()
        raise MeetingVersionConflictError("stale version")
    validate_transition(meeting.status, "REJECT")

    await _release_all_held_slots(gateway, meeting)
    previous_status = meeting.status
    meeting.status = "rejected"
    meeting.row_version += 1

    await gateway.add_status_history(
        _record_status_history(
            meeting,
            previous_status=previous_status,
            changed_by_user_id=staff.user_id,
            reason_code=reason_code,
        )
    )
    await gateway.add_audit_log(
        _record_audit(
            meeting,
            actor_user_id=staff.user_id,
            actor_role="EXHIBITOR",
            action_type="UPDATE",
            reason_code=reason_code,
        )
    )
    await gateway.commit()
    return meeting


async def propose_alternate(
    gateway: MeetingGateway,
    *,
    staff: ExhibitorStaff,
    meeting_id: uuid.UUID,
    slot_ids: list[uuid.UUID],
    version: int,
) -> MeetingRequest:
    meeting = await gateway.get_meeting_locked(meeting_id)
    if meeting is None:
        await gateway.rollback()
        raise MeetingNotFoundError("meeting not found")
    if meeting.participation_id != staff.participation_id:
        await gateway.rollback()
        raise MeetingForbiddenError("meeting does not belong to this exhibitor")
    if meeting.row_version != version:
        await gateway.rollback()
        raise MeetingVersionConflictError("stale version")
    validate_transition(meeting.status, "PROPOSE_ALTERNATE")

    await _release_all_held_slots(gateway, meeting)
    reserved_slot = await _reserve_first_available(
        gateway, slot_ids=slot_ids, participation_id=staff.participation_id
    )

    existing_requests = await gateway.get_slot_requests(meeting.meeting_id)
    next_order = len(existing_requests) + 1
    for slot_id in slot_ids:
        await gateway.add_slot_request(
            MeetingSlotRequest(
                meeting_slot_request_id=uuid.uuid4(),
                meeting_id=meeting.meeting_id,
                availability_slot_id=slot_id,
                preference_order=next_order,
                status="SELECTED" if slot_id == reserved_slot.availability_slot_id else "PENDING",
            )
        )
        next_order += 1

    previous_status = meeting.status
    meeting.status = "counter_proposed"
    meeting.row_version += 1

    await gateway.add_status_history(
        _record_status_history(
            meeting,
            previous_status=previous_status,
            changed_by_user_id=staff.user_id,
            reason_code=None,
        )
    )
    await gateway.add_audit_log(
        _record_audit(
            meeting, actor_user_id=staff.user_id, actor_role="EXHIBITOR", action_type="UPDATE"
        )
    )
    await gateway.commit()
    return meeting


# --------------------------------------------------------------------------
# 연락처 뷰 조립 (세 조건 게이트 적용 지점)
# --------------------------------------------------------------------------


async def build_contact_view(
    gateway: MeetingGateway,
    *,
    meeting: MeetingRequest,
    viewer_staff: ExhibitorStaff | None,
) -> dict[str, str | None] | None:
    """세 조건을 모두 만족할 때만 dict를 반환한다. 그 전에는 항상 None.

    ``viewer_staff``가 주어지면(참가업체 포털에서 조회) 최초 열람 시 disclosed_at을
    기록하고 감사로그(VIEW)를 남긴다 - ``meetings.py``의 buyer-summary 경로와 동일한 관례다.
    """

    contact_share = await gateway.get_contact_share(meeting.meeting_id)
    if not contact_reveal_allowed(meeting_status=meeting.status, contact_share=contact_share):
        return None
    assert contact_share is not None  # contact_reveal_allowed가 이미 보장

    buyer_profile = await gateway.get_profile(meeting.buyer_profile_id)
    if buyer_profile is None or buyer_profile.user_id is None:
        return None
    identity = await gateway.get_identity_by_user_id(buyer_profile.user_id)
    if identity is None:
        return None

    field_values = {
        "NAME": decrypt_meeting_text(identity.name_enc, purpose="identity-name"),
        "PHONE": decrypt_meeting_text(identity.phone_enc, purpose="identity-phone"),
        "BUSINESS_EMAIL": decrypt_meeting_text(identity.email_enc, purpose="identity-email"),
    }
    contact = {
        field: value
        for field in contact_share.shared_fields
        if (value := field_values.get(field)) is not None
    }

    if contact_share.disclosed_at is None:
        contact_share.disclosed_at = datetime.now(UTC)
        contact_share.disclosed_to_user_id = viewer_staff.user_id if viewer_staff else None
        await gateway.add_audit_log(
            _record_audit(
                meeting,
                actor_user_id=viewer_staff.user_id if viewer_staff else None,
                actor_role="EXHIBITOR",
                action_type="VIEW",
            )
        )
        await gateway.commit()

    return {
        "name": contact.get("NAME"),
        "business_email": contact.get("BUSINESS_EMAIL"),
        "business_phone": contact.get("PHONE"),
        "title": None,
    }
