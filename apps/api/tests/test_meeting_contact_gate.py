"""연락처 공개 3-게이트 불변식 (통합 MERGE STEP 15).

제품 불변식: 상담 연락처는 (1) 상담이 확정(accepted)되고 (2) 바이어가 공유에 동의했고
(3) 참가업체가 이 상담에 한해 공유를 명시적으로 켠 경우에만 공개된다. 셋 중 하나라도
빠지면 절대 공개하지 않는다.

통합 전 main의 ``routers/meetings.py``는 (1)과 (2)만 확인했다. 즉 업체 opt-in 없이도
바이어 이름/전화/이메일이 파트너 포털에 노출됐다. 이 파일의 마지막 테스트가 그 결함에
대한 회귀 테스트다 - 통합 전 코드에서는 반드시 실패한다.

DB는 다른 라우터 테스트(test_kiosk_api.py, test_recommendation_api.py)와 동일한 관례로
``get_db`` dependency_override + 인메모리 fake 세션으로 대체한다.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.v1.routers import meetings as meetings_router
from app.core.auth import encrypt_secret
from app.core.config import get_settings
from app.db.session import get_db
from app.main import app
from app.models.exhibitor import ExhibitorStaff
from app.models.identity import UserIdentity
from app.models.meeting import MeetingContactShare, MeetingRequest
from app.models.profile import BuyerNeed, UserProfile
from app.services.meeting.buyer_matching import contact_reveal_allowed

_PREFIX = get_settings().API_V1_PREFIX


# ---------------------------------------------------------------------------
# 1. 순수 도메인 규칙 (worktree tests/test_meeting_buyer_flow.py에서 이관)
# ---------------------------------------------------------------------------


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
        accepted_at=datetime.now(UTC) if buyer_consent else None,
        exhibitor_enabled_at=datetime.now(UTC) if exhibitor_enabled else None,
    )
    assert (
        contact_reveal_allowed(meeting_status=status, contact_share=contact_share)
        is expected
    )


def test_contact_reveal_allowed_is_false_when_buyer_never_consented() -> None:
    assert contact_reveal_allowed(meeting_status="accepted", contact_share=None) is False


# ---------------------------------------------------------------------------
# 2. 엔드포인트 회귀: GET /partner/meetings/{id}/buyer-summary
# ---------------------------------------------------------------------------


class _ScalarResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


class _FakeSession:
    """buyer-summary 핸들러가 실제로 부르는 호출만 지원하는 최소 세션."""

    def __init__(
        self,
        *,
        staff: ExhibitorStaff,
        meeting: MeetingRequest,
        contact_share: MeetingContactShare | None,
        buyer_profile: UserProfile,
        identity: UserIdentity,
    ) -> None:
        self._staff = staff
        self._meeting = meeting
        self._contact_share = contact_share
        self._buyer_profile = buyer_profile
        self._identity = identity
        self.added: list[Any] = []
        self.commit_count = 0

    async def get(self, entity: Any, key: uuid.UUID) -> Any:
        if entity is ExhibitorStaff:
            return self._staff if key == self._staff.staff_id else None
        if entity is MeetingRequest:
            return self._meeting if key == self._meeting.meeting_id else None
        if entity is UserProfile:
            return self._buyer_profile if key == self._buyer_profile.profile_id else None
        raise AssertionError(f"unexpected get({entity})")

    async def execute(self, statement: Any) -> _ScalarResult:
        entities = {
            description.get("entity")
            for description in statement.column_descriptions
        }
        if BuyerNeed in entities:
            return _ScalarResult(None)
        if MeetingContactShare in entities:
            return _ScalarResult(self._contact_share)
        if UserIdentity in entities:
            return _ScalarResult(self._identity)
        raise AssertionError(f"unexpected statement: {statement}")

    def add(self, row: Any) -> None:
        self.added.append(row)

    async def commit(self) -> None:
        self.commit_count += 1


def _build_world(
    *, exhibitor_enabled: bool
) -> tuple[_FakeSession, uuid.UUID, uuid.UUID]:
    settings = get_settings()
    participation_id = uuid.uuid4()
    staff = ExhibitorStaff(
        staff_id=uuid.uuid4(),
        participation_id=participation_id,
        user_id=uuid.uuid4(),
        active=True,
    )
    buyer_profile = UserProfile(profile_id=uuid.uuid4(), user_id=uuid.uuid4())
    meeting = MeetingRequest(
        meeting_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        event_id=uuid.uuid4(),
        participation_id=participation_id,
        buyer_profile_id=buyer_profile.profile_id,
        status="accepted",
    )
    contact_share = MeetingContactShare(
        meeting_contact_share_id=uuid.uuid4(),
        meeting_id=meeting.meeting_id,
        consent_policy_id=uuid.uuid4(),
        shared_fields=["NAME", "PHONE", "BUSINESS_EMAIL"],
        accepted_at=datetime.now(UTC),
        exhibitor_enabled_at=datetime.now(UTC) if exhibitor_enabled else None,
    )
    identity = UserIdentity(
        user_id=buyer_profile.user_id,
        name_enc=encrypt_secret("홍길동", purpose="identity-name", settings=settings),
        phone_enc=encrypt_secret(
            "010-0000-0000", purpose="identity-phone", settings=settings
        ),
        email_enc=encrypt_secret(
            "buyer@example.com", purpose="identity-email", settings=settings
        ),
    )
    session = _FakeSession(
        staff=staff,
        meeting=meeting,
        contact_share=contact_share,
        buyer_profile=buyer_profile,
        identity=identity,
    )
    return session, meeting.meeting_id, staff.staff_id


def _call_buyer_summary(session: _FakeSession, meeting_id: uuid.UUID, staff_id: uuid.UUID):
    async def _override_db():
        yield session

    async def _override_staff() -> uuid.UUID:
        return staff_id

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[meetings_router._staff_header] = _override_staff
    try:
        with TestClient(app) as client:
            return client.get(f"{_PREFIX}/partner/meetings/{meeting_id}/buyer-summary")
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(meetings_router._staff_header, None)


def test_buyer_summary_hides_contact_when_exhibitor_never_enabled_sharing() -> None:
    """통합 전 main 코드에서는 실패해야 하는 회귀 테스트.

    상담은 accepted이고 바이어 동의(accepted_at)도 있지만 업체가 공유를 켜지 않았다
    (exhibitor_enabled_at IS NULL) - 연락처는 절대 공개되면 안 된다.
    """

    session, meeting_id, staff_id = _build_world(exhibitor_enabled=False)
    response = _call_buyer_summary(session, meeting_id, staff_id)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["contact"] is None
    assert data["contact_disclosed"] is False
    # 공개하지 않았으므로 열람 감사로그도 남지 않고 disclosed_at도 찍히지 않는다.
    assert session.added == []
    assert session._contact_share is not None
    assert session._contact_share.disclosed_at is None


def test_buyer_summary_reveals_contact_when_all_three_gates_pass() -> None:
    session, meeting_id, staff_id = _build_world(exhibitor_enabled=True)
    response = _call_buyer_summary(session, meeting_id, staff_id)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["contact_disclosed"] is True
    assert data["contact"]["NAME"] == "홍길동"
    assert data["contact"]["PHONE"] == "010-0000-0000"
    assert data["contact"]["BUSINESS_EMAIL"] == "buyer@example.com"
    # 공개 시에는 감사로그(VIEW)가 반드시 남는다.
    assert len(session.added) == 1
    assert session._contact_share is not None
    assert session._contact_share.disclosed_at is not None
