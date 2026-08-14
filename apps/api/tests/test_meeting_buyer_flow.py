"""바이어<->업체 매칭 상담 흐름 (통합 MERGE STEP 22).

이 파일은 WAVE 2C worktree의 ``tests/test_meeting_buyer_flow.py``를 통합 저장소의 단일
상담 표면으로 재타겟한 것이다. 원본은 등록되지 않은 두 번째 라우터
(``meeting_buyer_extension.py``, ``/buyer/meeting-requests`` · ``/partner/meeting-requests``)
를 대상으로 했지만, 통합 저장소에는 상담 표면이 ``app/api/v1/routers/meetings.py`` 하나뿐이다
(그 라우터를 등록하면 같은 ``interaction.meeting`` 행이 어느 URL로 호출됐는지에 따라 다른
연락처 공개 규칙을 적용받게 된다). 따라서 여기서는 두 층을 검증한다:

1. 서비스 계층(``app/services/meeting/buyer_matching.py``)의 오케스트레이션 함수를 DB 없이
   순수 파이썬 인메모리 ``FakeMeetingGateway``로 직접 호출해 상태 머신·연락처 공개 3-게이트·
   크로스테넌트 차단·감사로그 기록을 검증한다. ``app/models/meeting.py``의 ORM 클래스는
   세션에 붙기 전까지 평범한 파이썬 객체이므로 실제 ``MeetingRequest``/``AvailabilitySlot``/
   ``MeetingContactShare`` 인스턴스를 그대로 쓴다 - DB도 목킹된 SQLAlchemy 세션도 필요 없다.
2. HTTP 계층은 실제 ``/api/v1/meetings`` · ``/api/v1/partner/meetings`` 경로를 TestClient로
   호출한다. 인증은 ``X-Profile-Id``/``X-Staff-Id`` 헤더가 아니라 principal 파생 의존성
   (``meetings._buyer_profile_header`` / ``_staff_header``)의 ``dependency_overrides``로
   주입한다 - 통합 저장소에는 클라이언트가 주장하는 행위자 헤더가 존재하지 않는다.

암호화 메모: 원본 worktree는 평문 UTF-8 placeholder를 썼다. 통합 저장소는 AESGCM 봉투
암호화를 쓰므로 식별정보 fixture도 ``encrypt_secret``으로 만든다 - 평문 바이트를 넣으면
fail-closed 복호화기가 정상적으로 None을 돌려주기 때문이다.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.v1.routers import meetings as meetings_router
from app.core.auth import encrypt_secret
from app.core.config import get_settings
from app.db.session import get_db
from app.main import app
from app.models.consent import AuditLog
from app.models.exhibitor import ExhibitorParticipation, ExhibitorStaff, Product
from app.models.identity import UserAccount, UserIdentity
from app.models.meeting import (
    MEETING_REJECT_REASON_CODES,
    AvailabilitySlot,
    MeetingContactShare,
    MeetingRequest,
    MeetingSlotRequest,
    MeetingStatusHistory,
)
from app.models.profile import BuyerNeed, UserProfile
from app.schemas.meeting import BuyerMeetingRequestCreate, ExhibitorRejectRequest
from app.services.meeting import buyer_matching as svc

_UTC = UTC
_TOPIC_CODE = "BIZ_GOAL.DISTRIBUTION"
_PREFIX = get_settings().API_V1_PREFIX


class FakeMeetingGateway:
    """``buyer_matching.MeetingGateway``의 DB-free 인메모리 구현 (테스트 전용)."""

    def __init__(self) -> None:
        self.profiles: dict[uuid.UUID, UserProfile] = {}
        self.accounts: dict[uuid.UUID, UserAccount] = {}
        self.participations: dict[uuid.UUID, ExhibitorParticipation] = {}
        self.products: dict[uuid.UUID, Product] = {}
        self.staff: dict[uuid.UUID, ExhibitorStaff] = {}
        self.identities: dict[uuid.UUID, UserIdentity] = {}
        self.meetings: dict[uuid.UUID, MeetingRequest] = {}
        self.slots: dict[uuid.UUID, AvailabilitySlot] = {}
        self.slot_requests: dict[uuid.UUID, MeetingSlotRequest] = {}
        self.contact_shares: dict[uuid.UUID, MeetingContactShare] = {}
        self.status_history: list[MeetingStatusHistory] = []
        self.audit_log: list[AuditLog] = []
        self.commit_count = 0
        self.rollback_count = 0
        # topic_code -> (taxonomy_version_id, concept_id, resolved_code)
        self.topic_catalog: dict[str, tuple[uuid.UUID, uuid.UUID, str]] = {
            _TOPIC_CODE: (uuid.uuid4(), uuid.uuid4(), _TOPIC_CODE)
        }
        self.concept_codes: dict[uuid.UUID, str] = {
            resolved[1]: resolved[2] for resolved in self.topic_catalog.values()
        }

    async def get_profile(self, profile_id: uuid.UUID) -> UserProfile | None:
        return self.profiles.get(profile_id)

    async def get_account(self, user_id: uuid.UUID) -> UserAccount | None:
        return self.accounts.get(user_id)

    async def get_participation_for_exhibitor(
        self, *, tenant_id: uuid.UUID, event_id: uuid.UUID, exhibitor_id: uuid.UUID
    ) -> ExhibitorParticipation | None:
        for participation in self.participations.values():
            if (
                participation.tenant_id == tenant_id
                and participation.event_id == event_id
                and participation.exhibitor_id == exhibitor_id
            ):
                return participation
        return None

    async def get_participation(
        self, participation_id: uuid.UUID
    ) -> ExhibitorParticipation | None:
        return self.participations.get(participation_id)

    async def get_product(self, product_id: uuid.UUID) -> Product | None:
        return self.products.get(product_id)

    async def get_staff(self, staff_id: uuid.UUID) -> ExhibitorStaff | None:
        staff = self.staff.get(staff_id)
        if staff is None or not staff.active:
            return None
        return staff

    async def get_identity_by_user_id(self, user_id: uuid.UUID) -> UserIdentity | None:
        for identity in self.identities.values():
            if identity.user_id == user_id:
                return identity
        return None

    async def get_meeting(self, meeting_id: uuid.UUID) -> MeetingRequest | None:
        return self.meetings.get(meeting_id)

    async def get_meeting_locked(self, meeting_id: uuid.UUID) -> MeetingRequest | None:
        return self.meetings.get(meeting_id)

    async def list_by_buyer(self, buyer_profile_id: uuid.UUID) -> list[MeetingRequest]:
        return [m for m in self.meetings.values() if m.buyer_profile_id == buyer_profile_id]

    async def list_by_participation(
        self, participation_id: uuid.UUID
    ) -> list[MeetingRequest]:
        return [m for m in self.meetings.values() if m.participation_id == participation_id]

    async def get_slot(self, slot_id: uuid.UUID) -> AvailabilitySlot | None:
        return self.slots.get(slot_id)

    async def reserve_slot(
        self, *, slot_id: uuid.UUID, participation_id: uuid.UUID
    ) -> AvailabilitySlot | None:
        slot = self.slots.get(slot_id)
        if slot is None or slot.participation_id != participation_id:
            return None
        if slot.status != "OPEN" or slot.reserved_count >= slot.capacity:
            return None
        slot.reserved_count += 1
        if slot.reserved_count >= slot.capacity:
            slot.status = "FULL"
        slot.row_version += 1
        return slot

    async def release_slot(self, slot_id: uuid.UUID) -> None:
        slot = self.slots.get(slot_id)
        if slot is None or slot.reserved_count <= 0:
            return
        slot.reserved_count -= 1
        if slot.status != "BLOCKED" and slot.reserved_count < slot.capacity:
            slot.status = "OPEN"
        slot.row_version += 1

    async def get_slot_requests(self, meeting_id: uuid.UUID) -> list[MeetingSlotRequest]:
        return [r for r in self.slot_requests.values() if r.meeting_id == meeting_id]

    async def add_slot_request(self, slot_request: MeetingSlotRequest) -> None:
        self.slot_requests[slot_request.meeting_slot_request_id] = slot_request

    async def get_contact_share(self, meeting_id: uuid.UUID) -> MeetingContactShare | None:
        return self.contact_shares.get(meeting_id)

    async def add_contact_share(self, contact_share: MeetingContactShare) -> None:
        self.contact_shares[contact_share.meeting_id] = contact_share

    async def add_meeting(self, meeting: MeetingRequest) -> None:
        self.meetings[meeting.meeting_id] = meeting

    async def add_status_history(self, entry: MeetingStatusHistory) -> None:
        self.status_history.append(entry)

    async def add_audit_log(self, entry: AuditLog) -> None:
        self.audit_log.append(entry)

    async def resolve_topic_concept(
        self, topic_code: str
    ) -> tuple[uuid.UUID, uuid.UUID, str] | None:
        return self.topic_catalog.get(topic_code)

    async def concept_code_for(self, concept_id: uuid.UUID | None) -> str | None:
        if concept_id is None:
            return None
        return self.concept_codes.get(concept_id)

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _future(hours: int) -> datetime:
    return datetime.now(_UTC) + timedelta(hours=hours)


def _encrypted_identity(user_id: uuid.UUID) -> UserIdentity:
    settings = get_settings()
    return UserIdentity(
        user_id=user_id,
        name_enc=encrypt_secret("김바이어", purpose="identity-name", settings=settings),
        phone_enc=encrypt_secret(
            "010-1234-5678", purpose="identity-phone", settings=settings
        ),
        email_enc=encrypt_secret(
            "buyer@example.com", purpose="identity-email", settings=settings
        ),
    )


class Scenario:
    """단일 업체(P1) + 단일 바이어(BP1) + 이질적 다른 업체/바이어(P2/BP2, 크로스테넌트용)."""

    def __init__(self) -> None:
        self.gateway = FakeMeetingGateway()
        self.tenant_id = uuid.uuid4()
        self.event_id = uuid.uuid4()

        self.exhibitor_id = uuid.uuid4()
        self.participation = ExhibitorParticipation(
            participation_id=uuid.uuid4(),
            tenant_id=self.tenant_id,
            event_id=self.event_id,
            exhibitor_id=self.exhibitor_id,
            participation_status="APPROVED",
            consultation_enabled=True,
        )
        self.gateway.participations[self.participation.participation_id] = self.participation

        self.staff_user_id = uuid.uuid4()
        self.staff = ExhibitorStaff(
            staff_id=uuid.uuid4(),
            participation_id=self.participation.participation_id,
            user_id=self.staff_user_id,
            display_name="담당자",
            active=True,
        )
        self.gateway.staff[self.staff.staff_id] = self.staff

        self.product = Product(
            product_id=uuid.uuid4(),
            exhibitor_id=self.exhibitor_id,
            product_name="테스트 막걸리",
            master_approval_status="APPROVED",
        )
        self.gateway.products[self.product.product_id] = self.product

        self.buyer_user_id = uuid.uuid4()
        self.buyer_profile = UserProfile(
            profile_id=uuid.uuid4(),
            tenant_id=self.tenant_id,
            event_id=self.event_id,
            user_id=self.buyer_user_id,
            user_type="BUYER",
        )
        self.gateway.profiles[self.buyer_profile.profile_id] = self.buyer_profile
        self.gateway.accounts[self.buyer_user_id] = UserAccount(
            user_id=self.buyer_user_id, authentication_state="PHONE_VERIFIED"
        )
        self.identity = _encrypted_identity(self.buyer_user_id)
        self.gateway.identities[uuid.uuid4()] = self.identity

        self.slots: dict[str, AvailabilitySlot] = {}
        for label, hours in (("slot1", 24), ("slot2", 48), ("slot3", 72)):
            slot = AvailabilitySlot(
                availability_slot_id=uuid.uuid4(),
                tenant_id=self.tenant_id,
                event_id=self.event_id,
                participation_id=self.participation.participation_id,
                staff_id=self.staff.staff_id,
                start_at=_future(hours),
                end_at=_future(hours + 1),
                capacity=1,
                reserved_count=0,
                status="OPEN",
                row_version=0,
            )
            self.slots[label] = slot
            self.gateway.slots[slot.availability_slot_id] = slot

        # 크로스테넌트 검증용 완전히 다른 바이어/업체.
        self.other_exhibitor_id = uuid.uuid4()
        self.other_participation = ExhibitorParticipation(
            participation_id=uuid.uuid4(),
            tenant_id=self.tenant_id,
            event_id=self.event_id,
            exhibitor_id=self.other_exhibitor_id,
            participation_status="APPROVED",
            consultation_enabled=True,
        )
        self.gateway.participations[self.other_participation.participation_id] = (
            self.other_participation
        )
        self.other_staff = ExhibitorStaff(
            staff_id=uuid.uuid4(),
            participation_id=self.other_participation.participation_id,
            user_id=uuid.uuid4(),
            display_name="다른 업체 담당자",
            active=True,
        )
        self.gateway.staff[self.other_staff.staff_id] = self.other_staff

        self.other_buyer_user_id = uuid.uuid4()
        self.other_buyer_profile = UserProfile(
            profile_id=uuid.uuid4(),
            tenant_id=self.tenant_id,
            event_id=self.event_id,
            user_id=self.other_buyer_user_id,
            user_type="BUYER",
        )
        self.gateway.profiles[self.other_buyer_profile.profile_id] = self.other_buyer_profile
        self.gateway.accounts[self.other_buyer_user_id] = UserAccount(
            user_id=self.other_buyer_user_id, authentication_state="PHONE_VERIFIED"
        )

    def create_input(
        self, *, slots: list[AvailabilitySlot], contact_share_consent: bool, product: bool = True
    ) -> svc.BuyerMeetingRequestInput:
        return svc.BuyerMeetingRequestInput(
            exhibitor_id=self.exhibitor_id,
            product_id=self.product.product_id if product else None,
            topic_code=_TOPIC_CODE,
            preferred_time_slots=[slot.availability_slot_id for slot in slots],
            order_scale_code="WHOLESALE",
            message="상담 요청드립니다",
            contact_share_consent=contact_share_consent,
        )

    async def create_meeting(
        self, *, slots: list[AvailabilitySlot], contact_share_consent: bool
    ) -> MeetingRequest:
        return await svc.create_meeting_request(
            self.gateway,
            buyer_profile_id=self.buyer_profile.profile_id,
            payload=self.create_input(slots=slots, contact_share_consent=contact_share_consent),
        )


@pytest.fixture
def scenario() -> Scenario:
    return Scenario()


# ---------------------------------------------------------------------------
# 순수 상태 머신 / 게이트 함수 (DB 전혀 필요 없음)
# ---------------------------------------------------------------------------


def test_validate_transition_allows_documented_actions() -> None:
    svc.validate_transition("requested", "ACCEPT")
    svc.validate_transition("requested", "REJECT")
    svc.validate_transition("requested", "PROPOSE_ALTERNATE")
    svc.validate_transition("counter_proposed", "BUYER_SELECT_ALTERNATE")
    svc.validate_transition("accepted", "BUYER_CANCEL")


@pytest.mark.parametrize(
    "status,action",
    [
        ("completed", "ACCEPT"),
        ("completed", "REJECT"),
        ("completed", "PROPOSE_ALTERNATE"),
        ("completed", "BUYER_CANCEL"),
        ("completed", "BUYER_SELECT_ALTERNATE"),
        ("rejected", "ACCEPT"),
        ("cancelled", "REJECT"),
        ("no_show", "ACCEPT"),
        ("requested", "BUYER_SELECT_ALTERNATE"),
        ("accepted", "PROPOSE_ALTERNATE"),
    ],
)
def test_validate_transition_rejects_everything_else(status: str, action: str) -> None:
    with pytest.raises(svc.MeetingInvalidTransitionError):
        svc.validate_transition(status, action)


@pytest.mark.parametrize(
    "status,buyer_consent,exhibitor_enabled,expected",
    [
        ("accepted", True, True, True),
        ("accepted", True, False, False),
        ("accepted", False, True, False),
        ("requested", True, True, False),
        ("rejected", True, True, False),
    ],
)
def test_contact_reveal_allowed_requires_all_three_gates(
    status: str, buyer_consent: bool, exhibitor_enabled: bool, expected: bool
) -> None:
    contact_share = MeetingContactShare(
        meeting_contact_share_id=uuid.uuid4(),
        meeting_id=uuid.uuid4(),
        consent_policy_id=uuid.uuid4(),
        shared_fields=["NAME"],
        accepted_at=datetime.now(_UTC) if buyer_consent else None,
        exhibitor_enabled_at=datetime.now(_UTC) if exhibitor_enabled else None,
    )
    assert (
        svc.contact_reveal_allowed(meeting_status=status, contact_share=contact_share)
        is expected
    )


def test_contact_reveal_allowed_is_false_when_buyer_never_consented() -> None:
    assert svc.contact_reveal_allowed(meeting_status="accepted", contact_share=None) is False


# ---------------------------------------------------------------------------
# 1. 전체 수락 흐름 + 연락처 공개 (세 조건을 하나씩 빼며 검증)
# ---------------------------------------------------------------------------


async def test_full_accept_flow_reveals_contact_only_when_all_three_gates_hold(
    scenario: Scenario,
) -> None:
    meeting = await scenario.create_meeting(
        slots=[scenario.slots["slot1"], scenario.slots["slot2"]], contact_share_consent=True
    )
    assert meeting.status == "requested"
    assert meeting.product_id == scenario.product.product_id
    assert meeting.order_scale_code == "WHOLESALE"

    # 아직 accepted가 아니므로 연락처는 절대 노출되지 않는다.
    contact_before = await svc.build_contact_view(
        scenario.gateway, meeting=meeting, viewer_staff=scenario.staff
    )
    assert contact_before is None

    accepted = await svc.accept_meeting(
        scenario.gateway,
        staff=scenario.staff,
        meeting_id=meeting.meeting_id,
        slot_id=scenario.slots["slot1"].availability_slot_id,
        version=meeting.row_version,
        enable_contact_sharing=True,
    )
    assert accepted.status == "accepted"
    assert accepted.confirmed_start == scenario.slots["slot1"].start_at

    contact = await svc.build_contact_view(
        scenario.gateway, meeting=accepted, viewer_staff=scenario.staff
    )
    assert contact is not None
    assert contact["business_email"] == "buyer@example.com"
    assert contact["business_phone"] == "010-1234-5678"
    assert contact["name"] == "김바이어"

    # 감사로그: CREATE(요청 생성) + UPDATE(수락) + VIEW(연락처 열람) 각 1건 이상.
    action_types = [entry.action_type for entry in scenario.gateway.audit_log]
    assert "CREATE" in action_types
    assert "UPDATE" in action_types
    assert "VIEW" in action_types

    # 상태 전이 이력도 매 전이마다 append-only로 남는다.
    assert [h.new_status for h in scenario.gateway.status_history] == ["requested", "accepted"]


async def test_contact_not_revealed_when_exhibitor_never_enables_sharing(
    scenario: Scenario,
) -> None:
    meeting = await scenario.create_meeting(
        slots=[scenario.slots["slot1"]], contact_share_consent=True
    )
    accepted = await svc.accept_meeting(
        scenario.gateway,
        staff=scenario.staff,
        meeting_id=meeting.meeting_id,
        slot_id=scenario.slots["slot1"].availability_slot_id,
        version=meeting.row_version,
        enable_contact_sharing=False,  # 업체가 켜지 않음
    )
    assert accepted.status == "accepted"
    contact = await svc.build_contact_view(
        scenario.gateway, meeting=accepted, viewer_staff=scenario.staff
    )
    assert contact is None


async def test_contact_not_revealed_when_buyer_never_consented(scenario: Scenario) -> None:
    meeting = await scenario.create_meeting(
        slots=[scenario.slots["slot1"]],
        contact_share_consent=False,  # 바이어가 동의 안 함
    )
    accepted = await svc.accept_meeting(
        scenario.gateway,
        staff=scenario.staff,
        meeting_id=meeting.meeting_id,
        slot_id=scenario.slots["slot1"].availability_slot_id,
        version=meeting.row_version,
        enable_contact_sharing=True,  # 업체는 켰지만
    )
    contact = await svc.build_contact_view(
        scenario.gateway, meeting=accepted, viewer_staff=scenario.staff
    )
    assert contact is None
    # 바이어가 애초에 동의하지 않았으므로 contact_share 행 자체가 없다 - 업체가 만들 수 없다.
    assert scenario.gateway.contact_shares.get(meeting.meeting_id) is None


async def test_plaintext_identity_bytes_are_never_echoed(scenario: Scenario) -> None:
    """봉투 암호화 fail-closed 회귀: 구 평문/손상 데이터는 절대 그대로 반환되지 않는다."""

    scenario.identity.name_enc = b"\xea\xb9\x80\xeb\xb0\x94\xec\x9d\xb4\xec\x96\xb4"
    scenario.identity.phone_enc = b"010-1234-5678"
    scenario.identity.email_enc = b"buyer@example.com"

    meeting = await scenario.create_meeting(
        slots=[scenario.slots["slot1"]], contact_share_consent=True
    )
    accepted = await svc.accept_meeting(
        scenario.gateway,
        staff=scenario.staff,
        meeting_id=meeting.meeting_id,
        slot_id=scenario.slots["slot1"].availability_slot_id,
        version=meeting.row_version,
        enable_contact_sharing=True,
    )
    contact = await svc.build_contact_view(
        scenario.gateway, meeting=accepted, viewer_staff=scenario.staff
    )
    assert contact == {
        "name": None,
        "business_email": None,
        "business_phone": None,
        "title": None,
    }


# ---------------------------------------------------------------------------
# 2. 거절 흐름 + 사유코드 + 연락처 미노출
# ---------------------------------------------------------------------------


async def test_reject_flow_records_reason_code_and_never_reveals_contact(
    scenario: Scenario,
) -> None:
    meeting = await scenario.create_meeting(
        slots=[scenario.slots["slot1"]], contact_share_consent=True
    )
    rejected = await svc.reject_meeting(
        scenario.gateway,
        staff=scenario.staff,
        meeting_id=meeting.meeting_id,
        reason_code="TRADE_CONDITION_MISMATCH",
        version=meeting.row_version,
    )
    assert rejected.status == "rejected"
    history = scenario.gateway.status_history[-1]
    assert history.new_status == "rejected"
    assert history.reason_code == "TRADE_CONDITION_MISMATCH"

    contact = await svc.build_contact_view(
        scenario.gateway, meeting=rejected, viewer_staff=scenario.staff
    )
    assert contact is None

    # 거절 시 점유했던 슬롯은 반환된다 (다른 바이어가 다시 요청할 수 있어야 함).
    slot = scenario.slots["slot1"]
    assert slot.status == "OPEN"
    assert slot.reserved_count == 0


def test_all_documented_reject_reason_codes_are_accepted_by_the_schema() -> None:
    for code in MEETING_REJECT_REASON_CODES:
        ExhibitorRejectRequest(reason_code=code, version=0)


def test_unsupported_reject_reason_code_is_rejected_by_the_schema() -> None:
    with pytest.raises(ValidationError):
        ExhibitorRejectRequest(reason_code="MADE_UP_REASON", version=0)


def test_partner_decision_request_narrows_reason_code_to_the_documented_six() -> None:
    """통합 시 접어 넣은 계약: ``/partner/meetings/{id}/decision``의 reason_code도
    자유 문자열이 아니라 6개 값 Literal이다 (MERGE STEP 22 (c))."""

    from app.schemas.meeting import PartnerDecisionRequest

    for code in MEETING_REJECT_REASON_CODES:
        PartnerDecisionRequest(action="REJECT", version=0, reason_code=code)
    PartnerDecisionRequest(action="REJECT", version=0)  # None도 허용(하위호환)
    with pytest.raises(ValidationError):
        PartnerDecisionRequest(action="REJECT", version=0, reason_code="MADE_UP_REASON")


async def test_service_layer_also_rejects_unsupported_reason_code(scenario: Scenario) -> None:
    """스키마 계층을 우회해도(직접 서비스 함수를 호출해도) 동일하게 막힌다."""

    meeting = await scenario.create_meeting(
        slots=[scenario.slots["slot1"]], contact_share_consent=False
    )
    with pytest.raises(svc.MeetingValidationError):
        await svc.reject_meeting(
            scenario.gateway,
            staff=scenario.staff,
            meeting_id=meeting.meeting_id,
            reason_code="NOT_A_REAL_CODE",
            version=meeting.row_version,
        )


# ---------------------------------------------------------------------------
# 3. 대안 시간 제안 흐름
# ---------------------------------------------------------------------------


async def test_alternate_time_proposal_flow(scenario: Scenario) -> None:
    meeting = await scenario.create_meeting(
        slots=[scenario.slots["slot1"]], contact_share_consent=False
    )
    proposed = await svc.propose_alternate(
        scenario.gateway,
        staff=scenario.staff,
        meeting_id=meeting.meeting_id,
        slot_ids=[
            scenario.slots["slot2"].availability_slot_id,
            scenario.slots["slot3"].availability_slot_id,
        ],
        version=meeting.row_version,
    )
    assert proposed.status == "counter_proposed"
    # 원래 잡았던 slot1은 반환되어야 한다.
    assert scenario.slots["slot1"].status == "OPEN"
    assert scenario.slots["slot1"].reserved_count == 0
    # slot2가 먼저 시도되어 점유된다 (slot_ids 순서상 첫 번째).
    assert scenario.slots["slot2"].reserved_count == 1

    selected = await svc.select_alternate(
        scenario.gateway,
        buyer_profile_id=scenario.buyer_profile.profile_id,
        meeting_id=meeting.meeting_id,
        slot_id=scenario.slots["slot2"].availability_slot_id,
        version=proposed.row_version,
    )
    assert selected.status == "accepted"
    assert selected.confirmed_start == scenario.slots["slot2"].start_at


async def test_buyer_can_cancel_instead_of_selecting_an_alternate(scenario: Scenario) -> None:
    meeting = await scenario.create_meeting(
        slots=[scenario.slots["slot1"]], contact_share_consent=False
    )
    proposed = await svc.propose_alternate(
        scenario.gateway,
        staff=scenario.staff,
        meeting_id=meeting.meeting_id,
        slot_ids=[scenario.slots["slot2"].availability_slot_id],
        version=meeting.row_version,
    )
    cancelled = await svc.cancel_buyer_meeting(
        scenario.gateway,
        buyer_profile_id=scenario.buyer_profile.profile_id,
        meeting_id=meeting.meeting_id,
        version=proposed.row_version,
    )
    assert cancelled.status == "cancelled"
    assert scenario.slots["slot2"].reserved_count == 0


# ---------------------------------------------------------------------------
# 4. 크로스테넌트 접근 차단
# ---------------------------------------------------------------------------


async def test_buyer_cannot_view_another_buyers_meeting(scenario: Scenario) -> None:
    meeting = await scenario.create_meeting(
        slots=[scenario.slots["slot1"]], contact_share_consent=False
    )
    with pytest.raises(svc.MeetingForbiddenError):
        await svc.get_buyer_meeting(
            scenario.gateway,
            buyer_profile_id=scenario.other_buyer_profile.profile_id,
            meeting_id=meeting.meeting_id,
        )


async def test_exhibitor_staff_cannot_view_another_exhibitors_meeting(
    scenario: Scenario,
) -> None:
    meeting = await scenario.create_meeting(
        slots=[scenario.slots["slot1"]], contact_share_consent=False
    )
    with pytest.raises(svc.MeetingForbiddenError):
        await svc.get_partner_meeting(
            scenario.gateway, staff=scenario.other_staff, meeting_id=meeting.meeting_id
        )


async def test_exhibitor_staff_cannot_accept_another_exhibitors_meeting(
    scenario: Scenario,
) -> None:
    meeting = await scenario.create_meeting(
        slots=[scenario.slots["slot1"]], contact_share_consent=False
    )
    with pytest.raises(svc.MeetingForbiddenError):
        await svc.accept_meeting(
            scenario.gateway,
            staff=scenario.other_staff,
            meeting_id=meeting.meeting_id,
            slot_id=scenario.slots["slot1"].availability_slot_id,
            version=meeting.row_version,
            enable_contact_sharing=True,
        )


async def test_list_by_buyer_and_by_participation_are_correctly_scoped(
    scenario: Scenario,
) -> None:
    own_meeting = await scenario.create_meeting(
        slots=[scenario.slots["slot1"]], contact_share_consent=False
    )
    buyer_list = await svc.list_buyer_meetings(
        scenario.gateway, buyer_profile_id=scenario.buyer_profile.profile_id
    )
    assert [m.meeting_id for m in buyer_list] == [own_meeting.meeting_id]
    other_buyer_list = await svc.list_buyer_meetings(
        scenario.gateway, buyer_profile_id=scenario.other_buyer_profile.profile_id
    )
    assert other_buyer_list == []

    partner_list = await svc.list_partner_meetings(scenario.gateway, staff=scenario.staff)
    assert [m.meeting_id for m in partner_list] == [own_meeting.meeting_id]
    other_partner_list = await svc.list_partner_meetings(
        scenario.gateway, staff=scenario.other_staff
    )
    assert other_partner_list == []


# ---------------------------------------------------------------------------
# 5. 잘못된 상태 전이 거부 / 6. 완료된 상담 재개 불가
# ---------------------------------------------------------------------------


async def test_invalid_transition_is_rejected_end_to_end(scenario: Scenario) -> None:
    meeting = await scenario.create_meeting(
        slots=[scenario.slots["slot1"]], contact_share_consent=False
    )
    rejected = await svc.reject_meeting(
        scenario.gateway,
        staff=scenario.staff,
        meeting_id=meeting.meeting_id,
        reason_code="NOT_RELEVANT",
        version=meeting.row_version,
    )
    assert rejected.status == "rejected"

    with pytest.raises(svc.MeetingInvalidTransitionError):
        await svc.accept_meeting(
            scenario.gateway,
            staff=scenario.staff,
            meeting_id=meeting.meeting_id,
            slot_id=scenario.slots["slot1"].availability_slot_id,
            version=rejected.row_version,
            enable_contact_sharing=False,
        )


async def test_completed_meeting_cannot_be_reopened_by_any_action(scenario: Scenario) -> None:
    meeting = await scenario.create_meeting(
        slots=[scenario.slots["slot1"]], contact_share_consent=True
    )
    accepted = await svc.accept_meeting(
        scenario.gateway,
        staff=scenario.staff,
        meeting_id=meeting.meeting_id,
        slot_id=scenario.slots["slot1"].availability_slot_id,
        version=meeting.row_version,
        enable_contact_sharing=True,
    )
    # meetings.py의 E-04 결과기록 흐름이 accepted -> completed로 옮기는 것과 동등한 상태를
    # 시뮬레이션한다 (같은 테이블·같은 상태값을 공유하므로 이 서비스 계층의 액션들도 그
    # 결과를 존중해야 한다).
    accepted.status = "completed"

    with pytest.raises(svc.MeetingInvalidTransitionError):
        await svc.accept_meeting(
            scenario.gateway,
            staff=scenario.staff,
            meeting_id=accepted.meeting_id,
            slot_id=scenario.slots["slot1"].availability_slot_id,
            version=accepted.row_version,
            enable_contact_sharing=True,
        )
    with pytest.raises(svc.MeetingInvalidTransitionError):
        await svc.reject_meeting(
            scenario.gateway,
            staff=scenario.staff,
            meeting_id=accepted.meeting_id,
            reason_code="OTHER",
            version=accepted.row_version,
        )
    with pytest.raises(svc.MeetingInvalidTransitionError):
        await svc.propose_alternate(
            scenario.gateway,
            staff=scenario.staff,
            meeting_id=accepted.meeting_id,
            slot_ids=[scenario.slots["slot2"].availability_slot_id],
            version=accepted.row_version,
        )
    with pytest.raises(svc.MeetingInvalidTransitionError):
        await svc.cancel_buyer_meeting(
            scenario.gateway,
            buyer_profile_id=scenario.buyer_profile.profile_id,
            meeting_id=accepted.meeting_id,
            version=accepted.row_version,
        )
    with pytest.raises(svc.MeetingInvalidTransitionError):
        await svc.select_alternate(
            scenario.gateway,
            buyer_profile_id=scenario.buyer_profile.profile_id,
            meeting_id=accepted.meeting_id,
            slot_id=scenario.slots["slot1"].availability_slot_id,
            version=accepted.row_version,
        )


async def test_stale_version_is_rejected_with_conflict(scenario: Scenario) -> None:
    meeting = await scenario.create_meeting(
        slots=[scenario.slots["slot1"]], contact_share_consent=False
    )
    with pytest.raises(svc.MeetingVersionConflictError):
        await svc.reject_meeting(
            scenario.gateway,
            staff=scenario.staff,
            meeting_id=meeting.meeting_id,
            reason_code="OTHER",
            version=meeting.row_version + 1,
        )


# ---------------------------------------------------------------------------
# 7. 미승인/타업체 제품은 상담에 연결할 수 없다 (승인 경계 불변식)
# ---------------------------------------------------------------------------


async def test_unapproved_product_cannot_be_attached_to_a_meeting(
    scenario: Scenario,
) -> None:
    scenario.product.master_approval_status = "DRAFT"
    with pytest.raises(svc.MeetingValidationError):
        await svc.create_meeting_request(
            scenario.gateway,
            buyer_profile_id=scenario.buyer_profile.profile_id,
            payload=scenario.create_input(
                slots=[scenario.slots["slot1"]], contact_share_consent=False
            ),
        )


async def test_another_exhibitors_product_cannot_be_attached_to_a_meeting(
    scenario: Scenario,
) -> None:
    scenario.product.exhibitor_id = scenario.other_exhibitor_id
    with pytest.raises(svc.MeetingValidationError):
        await svc.create_meeting_request(
            scenario.gateway,
            buyer_profile_id=scenario.buyer_profile.profile_id,
            payload=scenario.create_input(
                slots=[scenario.slots["slot1"]], contact_share_consent=False
            ),
        )


def test_product_belongs_to_participation_rejects_deleted_products() -> None:
    participation = ExhibitorParticipation(
        participation_id=uuid.uuid4(), exhibitor_id=uuid.uuid4()
    )
    product = Product(
        product_id=uuid.uuid4(),
        exhibitor_id=participation.exhibitor_id,
        product_name="삭제된 제품",
        master_approval_status="APPROVED",
        deleted_at=datetime.now(_UTC),
    )
    assert svc.product_belongs_to_participation(product, participation=participation) is False
    assert svc.product_belongs_to_participation(None, participation=participation) is False
    product.deleted_at = None
    assert svc.product_belongs_to_participation(product, participation=participation) is True


# ---------------------------------------------------------------------------
# 스키마 계층: 요청 검증
# ---------------------------------------------------------------------------


def test_buyer_request_schema_caps_preferred_slots_at_three() -> None:
    with pytest.raises(ValidationError):
        BuyerMeetingRequestCreate(
            exhibitor_id=uuid.uuid4(),
            topic_code=_TOPIC_CODE,
            preferred_time_slots=[uuid.uuid4() for _ in range(4)],
        )
    # 3개는 허용된다.
    BuyerMeetingRequestCreate(
        exhibitor_id=uuid.uuid4(),
        topic_code=_TOPIC_CODE,
        preferred_time_slots=[uuid.uuid4() for _ in range(3)],
    )


def test_buyer_request_schema_defaults_contact_share_consent_to_false() -> None:
    payload = BuyerMeetingRequestCreate(
        exhibitor_id=uuid.uuid4(),
        topic_code=_TOPIC_CODE,
        preferred_time_slots=[uuid.uuid4()],
    )
    assert payload.contact_share_consent is False


# ---------------------------------------------------------------------------
# HTTP 계층 — 통합된 단일 상담 표면
# ---------------------------------------------------------------------------


def test_the_meeting_surface_is_a_single_registered_router() -> None:
    """통합의 핵심 불변식: 상담 경로 그룹은 하나뿐이다.

    ``/buyer/meeting-requests`` · ``/partner/meeting-requests``가 다시 등록되면 같은
    ``interaction.meeting`` 행이 호출 URL에 따라 서로 다른 연락처 공개 규칙을 적용받게
    된다 - 그 순간 이 테스트가 깨진다.
    """

    paths = set(app.openapi()["paths"])
    for path in (
        f"{_PREFIX}/exhibitors/{{exhibitor_id}}/availability",
        f"{_PREFIX}/meetings",
        f"{_PREFIX}/meetings/{{meeting_id}}",
        f"{_PREFIX}/meetings/{{meeting_id}}/cancel",
        f"{_PREFIX}/meetings/{{meeting_id}}/respond",
        f"{_PREFIX}/partner/meetings",
        f"{_PREFIX}/partner/meetings/{{meeting_id}}/buyer-summary",
        f"{_PREFIX}/partner/meetings/{{meeting_id}}/decision",
        f"{_PREFIX}/partner/meetings/{{meeting_id}}/outcome",
    ):
        assert path in paths, f"missing unified meeting route: {path}"

    duplicates = [
        path
        for path in paths
        if path.startswith(
            (f"{_PREFIX}/buyer/meeting-requests", f"{_PREFIX}/partner/meeting-requests")
        )
    ]
    assert duplicates == [], f"second meeting surface must not be registered: {duplicates}"


class _Result:
    """meetings.py가 실제로 쓰는 sqlalchemy.Result 부분집합."""

    def __init__(self, rows: list[Any]) -> None:
        self._rows = list(rows)

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None

    def scalar_one(self) -> Any:
        return self._rows[0]

    def scalars(self) -> _Result:
        return self

    def first(self) -> Any:
        return self._rows[0] if self._rows else None

    def all(self) -> list[Any]:
        return list(self._rows)


def _row(obj: Any) -> _Result:
    return _Result([obj])


def _none() -> _Result:
    return _Result([])


def _rows(objs: list[Any]) -> _Result:
    return _Result(objs)


class ScriptedSession:
    """호출 순서대로 소비되는 스크립트형 AsyncSession 대역.

    각 execute() 순서는 apps/api/app/api/v1/routers/meetings.py를 그대로 읽어 추적했고,
    각 사용처에 그 순서를 주석으로 남긴다. 라우터가 예상 밖의 질의를 하나라도 더 하면
    AssertionError로 즉시 드러난다 (예: 연락처를 숨겨야 하는데 identity를 조회하는 회귀).
    """

    def __init__(
        self,
        *,
        get_map: dict[type, Any] | None = None,
        execute_queue: list[_Result] | None = None,
    ) -> None:
        self._get_map = get_map or {}
        self._queue = list(execute_queue or [])
        self.added: list[Any] = []
        self.commits = 0
        self.rollbacks = 0

    async def get(self, model: type, _pk: Any) -> Any:
        return self._get_map.get(model)

    def add(self, row: Any) -> None:
        self.added.append(row)

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        self.commits += 1
        # 실제 Postgres는 INSERT 시 컬럼 기본값(row_version=0, created_at/updated_at=now())을
        # 채운다. 이 대역은 DB에 가지 않으므로 같은 효과만 흉내낸다 - 그러지 않으면 라우터가
        # 직접 만든 객체가 Pydantic 응답 검증에서 None으로 걸린다.
        now = datetime.now(_UTC)
        for row in self.added:
            if getattr(row, "row_version", 0) is None:
                row.row_version = 0
            if getattr(row, "created_at", "unset") is None:
                row.created_at = now
            if getattr(row, "updated_at", "unset") is None:
                row.updated_at = now

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def execute(self, statement: Any) -> _Result:
        if not self._queue:
            raise AssertionError(f"unscripted db.execute() call: {statement}")
        scripted = self._queue.pop(0)
        # 큐 항목이 callable이면 호출 시점에 평가한다 - 핸들러가 방금 db.add()한 행을
        # 뒤이어 다시 SELECT하는 경로(실제 DB라면 그 행이 보인다)를 흉내내기 위해서다.
        return scripted() if callable(scripted) else scripted


def _client(
    session: ScriptedSession,
    *,
    buyer_profile_id: uuid.UUID | None = None,
    staff_id: uuid.UUID | None = None,
) -> TestClient:
    """검증된 principal에서 파생되는 의존성만 override한다 (행위자 헤더는 쓰지 않는다)."""

    async def _override_db() -> Any:
        yield session

    async def _override_buyer() -> uuid.UUID | None:
        return buyer_profile_id

    async def _override_staff() -> uuid.UUID | None:
        return staff_id

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[meetings_router._buyer_profile_header] = _override_buyer
    app.dependency_overrides[meetings_router._staff_header] = _override_staff
    return TestClient(app)


def _clear_overrides() -> None:
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(meetings_router._buyer_profile_header, None)
    app.dependency_overrides.pop(meetings_router._staff_header, None)


class HttpWorld:
    """create -> decision(ACCEPT) -> buyer-summary 세 홉이 공유하는 도메인 객체 묶음."""

    def __init__(self) -> None:
        self.tenant_id = uuid.uuid4()
        self.event_id = uuid.uuid4()
        self.buyer_user_id = uuid.uuid4()
        self.exhibitor_id = uuid.uuid4()
        self.participation_id = uuid.uuid4()

        self.buyer_profile = UserProfile(
            profile_id=uuid.uuid4(),
            tenant_id=self.tenant_id,
            event_id=self.event_id,
            user_id=self.buyer_user_id,
            user_type="BUYER",
        )
        self.account = UserAccount(
            user_id=self.buyer_user_id, authentication_state="PHONE_VERIFIED"
        )
        self.participation = ExhibitorParticipation(
            participation_id=self.participation_id,
            tenant_id=self.tenant_id,
            event_id=self.event_id,
            exhibitor_id=self.exhibitor_id,
            participation_status="APPROVED",
            consultation_enabled=True,
        )
        self.staff = ExhibitorStaff(
            staff_id=uuid.uuid4(),
            participation_id=self.participation_id,
            user_id=uuid.uuid4(),
            display_name="담당자",
            active=True,
        )
        self.product = Product(
            product_id=uuid.uuid4(),
            exhibitor_id=self.exhibitor_id,
            product_name="테스트 막걸리",
            master_approval_status="APPROVED",
        )
        self.slot = AvailabilitySlot(
            availability_slot_id=uuid.uuid4(),
            tenant_id=self.tenant_id,
            event_id=self.event_id,
            participation_id=self.participation_id,
            staff_id=self.staff.staff_id,
            start_at=_future(24),
            end_at=_future(25),
            capacity=1,
            reserved_count=0,
            status="OPEN",
            row_version=0,
        )
        self.identity = _encrypted_identity(self.buyer_user_id)
        self.consent_policy_id = uuid.uuid4()
        self.meeting: MeetingRequest | None = None
        self.contact_share: MeetingContactShare | None = None
        self.slot_request: MeetingSlotRequest | None = None


def test_create_then_accept_over_http_reveals_contact_only_after_accept() -> None:
    """세 홉을 실제 HTTP로 걷는다: 요청 -> 업체 수락(공유 켜기) -> 연락처 열람."""

    from app.models.consent import ConsentPolicy

    world = HttpWorld()
    try:
        # --- hop 1: POST /meetings -------------------------------------
        # 추적한 db 호출 순서: get(UserProfile), get(UserAccount),
        #   execute(participation_stmt), get(Product),
        #   execute(update AvailabilitySlot RETURNING), execute(select ConsentPolicy),
        #   commit, execute(slot join), execute(MeetingContactShare), get(participation)
        create_session: ScriptedSession

        def _persisted_contact_share() -> _Result:
            return _Result(
                [
                    row
                    for row in create_session.added
                    if isinstance(row, MeetingContactShare)
                ]
            )

        create_session = ScriptedSession(
            get_map={
                UserProfile: world.buyer_profile,
                UserAccount: world.account,
                Product: world.product,
                ExhibitorParticipation: world.participation,
            },
            execute_queue=[
                _row(world.participation),
                _row(world.slot),
                _row(ConsentPolicy(consent_policy_id=world.consent_policy_id)),
                _rows([]),
                _persisted_contact_share,
            ],
        )
        client = _client(create_session, buyer_profile_id=world.buyer_profile.profile_id)
        create_response = client.post(
            f"{_PREFIX}/meetings",
            json={
                "exhibitor_id": str(world.exhibitor_id),
                "product_id": str(world.product.product_id),
                "order_scale_code": "WHOLESALE",
                "topic": _TOPIC_CODE,
                "requested_slot_ids": [str(world.slot.availability_slot_id)],
                "contact_share": {
                    "accepted": True,
                    "document_version": "v1",
                    "fields": ["NAME", "PHONE", "BUSINESS_EMAIL"],
                },
            },
        )
        assert create_response.status_code == 201, create_response.text
        body = create_response.json()
        assert body["success"] is True
        assert body["data"]["status"] == "requested"
        # 바이어 동의는 기록되었지만 아직 아무것도 공개되지 않았다 - 응답에는 연락처 필드
        # 자체가 없고(MeetingResponse에는 contact가 없다) 세 번째 게이트는 꺼진 채다.
        assert body["data"]["contact_share_accepted"] is True
        assert set(body["data"]["contact_share_fields"]) == {
            "NAME",
            "PHONE",
            "BUSINESS_EMAIL",
        }
        assert "contact" not in body["data"]
        world.meeting = next(
            row for row in create_session.added if isinstance(row, MeetingRequest)
        )
        world.contact_share = next(
            row for row in create_session.added if isinstance(row, MeetingContactShare)
        )
        world.slot_request = next(
            row for row in create_session.added if isinstance(row, MeetingSlotRequest)
        )
        assert world.meeting.product_id == world.product.product_id
        assert world.meeting.order_scale_code == "WHOLESALE"
        assert world.contact_share.exhibitor_enabled_at is None
        _clear_overrides()

        # --- hop 2: POST /partner/meetings/{id}/decision (ACCEPT) -------
        # 추적한 순서: get(ExhibitorStaff), execute(select meeting FOR UPDATE),
        #   execute(held_stmt), get(AvailabilitySlot), execute(other_selected_stmt),
        #   execute(select MeetingContactShare)  <- enable_contact_sharing=True일 때만,
        #   commit, execute(slot join), execute(MeetingContactShare), get(participation)
        world.slot_request.status = "SELECTED"
        decide_session = ScriptedSession(
            get_map={
                ExhibitorStaff: world.staff,
                AvailabilitySlot: world.slot,
                ExhibitorParticipation: world.participation,
            },
            execute_queue=[
                _row(world.meeting),
                _row(world.slot_request),
                _rows([]),
                _row(world.contact_share),
                _rows([(world.slot_request, world.slot)]),
                _row(world.contact_share),
            ],
        )
        client = _client(decide_session, staff_id=world.staff.staff_id)
        decide_response = client.post(
            f"{_PREFIX}/partner/meetings/{world.meeting.meeting_id}/decision",
            json={
                "action": "ACCEPT",
                "slot_id": str(world.slot.availability_slot_id),
                "version": 0,
                "enable_contact_sharing": True,
            },
        )
        assert decide_response.status_code == 200, decide_response.text
        assert decide_response.json()["data"]["status"] == "accepted"
        assert world.meeting.status == "accepted"
        # 세 번째 게이트가 이제서야 켜진다.
        assert world.contact_share.exhibitor_enabled_at is not None
        assert world.contact_share.exhibitor_enabled_by_staff_id == world.staff.staff_id
        _clear_overrides()

        # --- hop 3: GET /partner/meetings/{id}/buyer-summary ------------
        # 추적한 순서: get(ExhibitorStaff), get(MeetingRequest),
        #   execute(select BuyerNeed), execute(select MeetingContactShare),
        #   get(UserProfile), execute(select UserIdentity), commit
        summary_session = ScriptedSession(
            get_map={
                ExhibitorStaff: world.staff,
                MeetingRequest: world.meeting,
                UserProfile: world.buyer_profile,
            },
            execute_queue=[_none(), _row(world.contact_share), _row(world.identity)],
        )
        client = _client(summary_session, staff_id=world.staff.staff_id)
        summary_response = client.get(
            f"{_PREFIX}/partner/meetings/{world.meeting.meeting_id}/buyer-summary"
        )
        assert summary_response.status_code == 200, summary_response.text
        data = summary_response.json()["data"]
        assert data["contact_disclosed"] is True
        assert data["contact"]["BUSINESS_EMAIL"] == "buyer@example.com"
        assert data["contact"]["PHONE"] == "010-1234-5678"
        assert data["contact"]["NAME"] == "김바이어"
        audit_rows = [
            row for row in summary_session.added if type(row).__name__ == "AuditLog"
        ]
        assert len(audit_rows) == 1
    finally:
        _clear_overrides()


def test_cross_tenant_http_request_is_denied_as_not_found() -> None:
    """다른 바이어/다른 업체의 상담은 '존재 여부'조차 흘리지 않고 404다."""

    participation_id = uuid.uuid4()
    meeting = MeetingRequest(
        meeting_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        event_id=uuid.uuid4(),
        buyer_profile_id=uuid.uuid4(),
        participation_id=participation_id,
        status="requested",
    )
    try:
        session = ScriptedSession(get_map={MeetingRequest: meeting})
        client = _client(session, buyer_profile_id=uuid.uuid4())
        response = client.get(f"{_PREFIX}/meetings/{meeting.meeting_id}")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "RESOURCE_FORBIDDEN"
        _clear_overrides()

        other_staff = ExhibitorStaff(
            staff_id=uuid.uuid4(),
            participation_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            active=True,
        )
        session = ScriptedSession(
            get_map={ExhibitorStaff: other_staff, MeetingRequest: meeting}
        )
        client = _client(session, staff_id=other_staff.staff_id)
        response = client.get(
            f"{_PREFIX}/partner/meetings/{meeting.meeting_id}/buyer-summary"
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "RESOURCE_FORBIDDEN"
    finally:
        _clear_overrides()


def test_reject_over_http_requires_a_documented_reason_code() -> None:
    """거절 사유코드는 6개 값 Literal - 임의 문자열은 핸들러에 닿기 전에 422."""

    participation_id = uuid.uuid4()
    staff = ExhibitorStaff(
        staff_id=uuid.uuid4(),
        participation_id=participation_id,
        user_id=uuid.uuid4(),
        active=True,
    )
    meeting = MeetingRequest(
        meeting_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        event_id=uuid.uuid4(),
        buyer_profile_id=uuid.uuid4(),
        participation_id=participation_id,
        status="requested",
        row_version=0,
        confirmed_slot_id=None,
        # 실제 INSERT를 거치지 않으므로 server_default가 채울 값을 여기서 명시한다.
        created_at=datetime.now(_UTC),
        updated_at=datetime.now(_UTC),
    )
    try:
        class _ExplodingSession(ScriptedSession):
            async def execute(self, statement: Any) -> _Result:
                raise AssertionError(
                    "요청 본문 검증에서 걸려야 하므로 DB에 닿으면 안 된다"
                )

        client = _client(_ExplodingSession(get_map={ExhibitorStaff: staff}), staff_id=staff.staff_id)
        bad = client.post(
            f"{_PREFIX}/partner/meetings/{meeting.meeting_id}/decision",
            json={"action": "REJECT", "version": 0, "reason_code": "NOT_A_REAL_REASON"},
        )
        assert bad.status_code == 422
        _clear_overrides()

        # 추적한 REJECT 순서: get(ExhibitorStaff), execute(meeting FOR UPDATE),
        #   execute(_release_all_held_slots SELECT), commit,
        #   execute(slot join), execute(MeetingContactShare), get(participation)
        session = ScriptedSession(
            get_map={ExhibitorStaff: staff, ExhibitorParticipation: None},
            execute_queue=[_row(meeting), _rows([]), _rows([]), _none()],
        )
        client = _client(session, staff_id=staff.staff_id)
        good = client.post(
            f"{_PREFIX}/partner/meetings/{meeting.meeting_id}/decision",
            json={"action": "REJECT", "version": 0, "reason_code": "SCHEDULE_UNAVAILABLE"},
        )
        assert good.status_code == 200, good.text
        assert good.json()["data"]["status"] == "rejected"
        history = [row for row in session.added if isinstance(row, MeetingStatusHistory)]
        assert len(history) == 1
        assert history[0].reason_code == "SCHEDULE_UNAVAILABLE"
    finally:
        _clear_overrides()


def test_http_meeting_request_rejects_a_product_from_another_exhibitor() -> None:
    """MERGE STEP 22 (b): product_id는 (participation_id, product_id) 복합 FK가 없으므로
    라우터가 애플리케이션 계층에서 소유·승인 여부를 검증해야 한다."""

    world = HttpWorld()
    world.product.exhibitor_id = uuid.uuid4()  # 다른 업체의 제품
    try:
        session = ScriptedSession(
            get_map={
                UserProfile: world.buyer_profile,
                UserAccount: world.account,
                Product: world.product,
            },
            execute_queue=[_row(world.participation)],
        )
        client = _client(session, buyer_profile_id=world.buyer_profile.profile_id)
        response = client.post(
            f"{_PREFIX}/meetings",
            json={
                "exhibitor_id": str(world.exhibitor_id),
                "product_id": str(world.product.product_id),
                "topic": _TOPIC_CODE,
                "requested_slot_ids": [str(world.slot.availability_slot_id)],
            },
        )
        assert response.status_code == 400, response.text
        error = response.json()["error"]
        assert error["code"] == "VALIDATION_FAILED"
        assert error["field_errors"][0]["field"] == "product_id"
        # 슬롯을 점유하기 전에 막혔어야 한다.
        assert session.commits == 0
    finally:
        _clear_overrides()


def test_unauthenticated_meeting_request_never_touches_the_database() -> None:
    """principal이 없으면 401 - 헤더로는 어떤 행위자도 주장할 수 없다."""

    class _ExplodingSession(ScriptedSession):
        async def get(self, model: type, _pk: Any) -> Any:
            raise AssertionError("인증되지 않은 요청은 DB에 닿으면 안 된다")

        async def execute(self, statement: Any) -> _Result:
            raise AssertionError("인증되지 않은 요청은 DB에 닿으면 안 된다")

    try:
        client = _client(_ExplodingSession(), buyer_profile_id=None)
        response = client.post(
            f"{_PREFIX}/meetings",
            headers={"X-Profile-Id": str(uuid.uuid4())},  # 무시되어야 한다
            json={
                "exhibitor_id": str(uuid.uuid4()),
                "topic": _TOPIC_CODE,
                "requested_slot_ids": [str(uuid.uuid4())],
            },
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "AUTH_REQUIRED"
    finally:
        _clear_overrides()


def test_buyer_need_summary_model_is_still_reachable() -> None:
    """buyer-summary가 참조하는 BuyerNeed 모델이 계속 존재하는지 확인 (import 회귀 가드)."""

    assert BuyerNeed.__tablename__ == "buyer_need"
