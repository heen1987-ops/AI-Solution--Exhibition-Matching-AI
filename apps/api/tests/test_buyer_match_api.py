"""BACKEND-BUYER-MATCH (WAVE 2C) 커버리지.

DB가 없는 환경에서 실행 가능하도록, 순수 판정 로직(하드필터/점수/비교 뷰 조립)은 직접
호출해서 검증하고, DB I/O가 필요한 오케스트레이션/라우터 경로는 이 저장소의 다른 라우터
테스트(test_recommendation_api.py, test_kiosk_api.py)와 동일하게 fake와 monkeypatch로
대체한다.

커버 항목 (작업 지시가 명시한 테스트 목록):
    1. 전체 세션 생성 + 조회
    2. 타인 소유 세션 조회 시 403
    3. 미검증(비바이어/비활성) 프로파일 403
    4. compare에 5개 이상 exhibitor_id를 넣으면 거부
    5. compare가 UNKNOWN을 정확히 표시
    6. 하드필터를 위반한 업체는 결과에 절대 나타나지 않음

통합 STEP 21 재배선
--------------------
원본은 ``X-Profile-Id`` 헤더에서 바이어 주체를 읽었다. 그 스텁은 삭제됐고, 주체는
``app.core.router_auth.get_buyer_profile_id``(=meetings.py의 ``_buyer_profile_header``)가
검증된 principal에서 파생한다. 따라서 라우터 테스트는 헤더를 보내는 대신 그 의존성을
``dependency_overrides``로 대체한다.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.v1.routers import buyer_match as buyer_match_router
from app.api.v1.routers import meetings as meetings_router
from app.core.auth import AuthException, auth_exception_handler
from app.core.router_auth import get_buyer_profile_id
from app.db.session import get_db
from app.models.buyer_match import BuyerMatchCandidate, BuyerMatchSession
from app.models.buyer_profile import BuyerProfile
from app.models.exhibitor import Exhibitor, ExhibitorParticipation, TradeCondition
from app.models.profile import BuyerNeed, UserProfile
from app.schemas.buyer_match import BuyerCompareRequest
from app.services.buyer_match import compare as compare_service
from app.services.buyer_match import orchestrator as orchestrator_service
from app.services.buyer_match.access import (
    BuyerAccessDenied,
    BuyerContext,
    resolve_buyer_context,
)
from app.services.buyer_match.eligibility import (
    BuyerCriteria,
    CandidateRow,
    hard_filter,
)
from app.services.buyer_match.orchestrator import (
    BuyerMatchSessionNotAccessible,
    create_buyer_match_session,
    get_buyer_match_session_for_buyer,
)
from app.services.buyer_match.scoring import score_candidate

# apps/api/pyproject.toml sets asyncio_mode = "auto", so ``async def test_*`` functions run
# without an explicit @pytest.mark.asyncio (see tests/security/test_buyer_meeting_privacy.py).


# ---------------------------------------------------------------------------
# Fakes shared across tests
# ---------------------------------------------------------------------------


class _FakeDb:
    """orchestrator.create_buyer_match_session/get_buyer_match_session_for_buyer가
    실제로 호출하는 최소한의 AsyncSession 표면만 흉내낸다."""

    def __init__(self, *, buyer_need: object | None = None) -> None:
        self.added: list[object] = []
        self.commit_count = 0
        self.buyer_need = buyer_need
        self.sessions_by_id: dict[uuid.UUID, BuyerMatchSession] = {}

    async def get(self, model, pk):
        if model.__name__ == "BuyerNeed":
            return self.buyer_need
        if model is BuyerMatchSession:
            return self.sessions_by_id.get(pk)
        return None

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        for obj in self.added:
            if isinstance(obj, BuyerMatchSession) and obj.buyer_match_session_id is None:
                obj.buyer_match_session_id = uuid.uuid4()
                self.sessions_by_id[obj.buyer_match_session_id] = obj

    async def commit(self) -> None:
        self.commit_count += 1

    async def refresh(self, obj, attribute_names=None) -> None:
        if attribute_names and "candidates" in attribute_names and isinstance(
            obj, BuyerMatchSession
        ):
            obj.candidates = [
                c
                for c in self.added
                if isinstance(c, BuyerMatchCandidate)
                and c.buyer_match_session_id == obj.buyer_match_session_id
            ]


def _buyer(tier: str = "VERIFIED") -> BuyerContext:
    return BuyerContext(
        profile_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        event_id=uuid.uuid4(),
        profile_version=3,
        verification_tier=tier,
    )


def _candidate(
    *,
    exhibitor_id: uuid.UUID | None = None,
    region_code: str | None = "REGION.SEOUL",
    oem_status: str | None = "YES",
) -> CandidateRow:
    return CandidateRow(
        exhibitor_id=exhibitor_id or uuid.uuid4(),
        participation_id=uuid.uuid4(),
        category_codes=frozenset({"CATEGORY.TAKJU"}),
        region_code=region_code,
        has_trade_condition=True,
        oem_status=oem_status,
        private_label_status="NO",
        export_status="NEGOTIABLE",
        min_order_quantity=100,
        max_order_quantity=1000,
        wholesale_price_min=10000,
        wholesale_price_max=20000,
        profile_approved=True,
    )


# ---------------------------------------------------------------------------
# 1 & 6. Full session create+fetch, and hard-filter-violating exhibitor exclusion
# ---------------------------------------------------------------------------


async def test_create_and_fetch_session_excludes_hard_filter_violations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    passing = _candidate(region_code="REGION.SEOUL")
    violating = _candidate(region_code="REGION.BUSAN")  # will fail the region hard filter

    async def fake_load_candidate_rows(db, *, tenant_id, event_id):
        return [passing, violating]

    monkeypatch.setattr(
        orchestrator_service, "_load_candidate_rows", fake_load_candidate_rows
    )

    buyer = _buyer("VERIFIED")
    fake_db = _FakeDb()
    criteria = BuyerCriteria(regions=frozenset({"REGION.SEOUL"}))

    session = await create_buyer_match_session(
        fake_db, buyer=buyer, filters=criteria, limit=10
    )

    assert session.candidate_count == 2
    assert session.result_count == 1
    assert session.filtered_count == 1
    persisted_exhibitor_ids = {c.exhibitor_id for c in session.candidates}
    assert persisted_exhibitor_ids == {passing.exhibitor_id}
    assert violating.exhibitor_id not in persisted_exhibitor_ids
    assert fake_db.commit_count == 1

    # Fetch: owner can read it back.
    fetched = await get_buyer_match_session_for_buyer(
        fake_db,
        buyer_match_session_id=session.buyer_match_session_id,
        buyer_profile_id=buyer.profile_id,
    )
    assert fetched.buyer_match_session_id == session.buyer_match_session_id
    assert fetched.result_count == 1


def test_hard_filter_rejects_region_mismatch_directly() -> None:
    criteria = BuyerCriteria(regions=frozenset({"REGION.SEOUL"}))
    outcome = hard_filter(_candidate(region_code="REGION.BUSAN"), criteria)
    assert outcome.passed is False
    assert outcome.reason == "REGION_NOT_MATCHED"


def test_hard_filter_rejects_unknown_oem_when_required() -> None:
    criteria = BuyerCriteria(oem_required=True)
    outcome = hard_filter(_candidate(oem_status="UNKNOWN"), criteria)
    assert outcome.passed is False
    assert outcome.reason == "OEM_NOT_AVAILABLE"


def test_score_candidate_never_asserts_unknown_trade_condition_as_positive() -> None:
    row = CandidateRow(
        exhibitor_id=uuid.uuid4(),
        participation_id=uuid.uuid4(),
        category_codes=frozenset(),
        region_code=None,
        has_trade_condition=False,
    )
    scored = score_candidate(row, BuyerCriteria())
    assert "PRICE_UNKNOWN" in scored.unknown_fields
    assert "OEM_STATUS_UNKNOWN" in scored.unknown_fields
    assert "OEM_AVAILABLE" not in scored.reason_codes


# ---------------------------------------------------------------------------
# 2. Cross-buyer 403
# ---------------------------------------------------------------------------


async def test_fetch_by_non_owner_is_forbidden() -> None:
    owner_id = uuid.uuid4()
    other_buyer_id = uuid.uuid4()
    session = BuyerMatchSession(
        buyer_match_session_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        event_id=uuid.uuid4(),
        buyer_profile_id=owner_id,
        profile_version=1,
        policy_version="test",
        verification_tier="VERIFIED",
        filters_json={},
        candidate_count=0,
        filtered_count=0,
        result_count=0,
        status="ACTIVE",
        generated_at=datetime.now(UTC),
    )
    fake_db = _FakeDb()
    fake_db.sessions_by_id[session.buyer_match_session_id] = session

    with pytest.raises(BuyerMatchSessionNotAccessible) as excinfo:
        await get_buyer_match_session_for_buyer(
            fake_db,
            buyer_match_session_id=session.buyer_match_session_id,
            buyer_profile_id=other_buyer_id,
        )
    assert excinfo.value.code == "BUYER_MATCH_SESSION_FORBIDDEN"


# ---------------------------------------------------------------------------
# 3. Unverified/non-buyer profile -> 403 at the router boundary
# ---------------------------------------------------------------------------


class _FirstResult:
    def __init__(self, value) -> None:
        self._value = value

    def first(self):
        return self._value


class _ScalarResult:
    def __init__(self, value) -> None:
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _AccessFakeDb:
    """access.resolve_buyer_context가 던지는 두 select()문만 흉내낸다.

    첫 select(UserProfile, BuyerNeed)는 column_descriptions에 두 엔티티가 모두 잡히고,
    두 번째 select(BuyerProfile)는 하나만 잡히므로 그 차이로 분기한다
    (tests/test_result_store_contract.py의 _FakeSession과 동일한 기법).
    """

    def __init__(self, *, profile, buyer_need, buyer_profile) -> None:
        self.profile = profile
        self.buyer_need = buyer_need
        self.buyer_profile = buyer_profile

    async def execute(self, statement):
        entity_names = {
            getattr(d.get("entity"), "__name__", None)
            for d in statement.column_descriptions
        }
        if entity_names == {"UserProfile", "BuyerNeed"}:
            value = (self.profile, self.buyer_need) if self.profile is not None else None
            return _FirstResult(value)
        if entity_names == {"BuyerProfile"}:
            return _ScalarResult(self.buyer_profile)
        raise AssertionError(f"unexpected statement entities: {entity_names}")


def _user_profile(**overrides) -> UserProfile:
    defaults = {
        "profile_id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "event_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "user_type": "BUYER",
        "profile_status": "COMPLETE",
        "current_version": 1,
    }
    defaults.update(overrides)
    return UserProfile(**defaults)


async def test_resolve_buyer_context_uses_durable_verification_status_when_present() -> None:
    profile = _user_profile()
    durable = BuyerProfile(
        buyer_profile_id=uuid.uuid4(),
        tenant_id=profile.tenant_id,
        user_id=profile.user_id,
        verification_status="VERIFIED",
    )
    fake_db = _AccessFakeDb(profile=profile, buyer_need=None, buyer_profile=durable)

    context = await resolve_buyer_context(fake_db, profile.profile_id)

    assert context.verification_tier == "VERIFIED"


async def test_resolve_buyer_context_blocks_unverified_durable_status() -> None:
    profile = _user_profile()
    durable = BuyerProfile(
        buyer_profile_id=uuid.uuid4(),
        tenant_id=profile.tenant_id,
        user_id=profile.user_id,
        verification_status="UNVERIFIED",
    )
    fake_db = _AccessFakeDb(profile=profile, buyer_need=None, buyer_profile=durable)

    with pytest.raises(BuyerAccessDenied) as excinfo:
        await resolve_buyer_context(fake_db, profile.profile_id)
    assert excinfo.value.code == "BUYER_NOT_VERIFIED"


async def test_resolve_buyer_context_falls_back_to_limited_without_durable_profile() -> None:
    profile = _user_profile()
    buyer_need = BuyerNeed(
        profile_id=profile.profile_id,
        business_email_verified=True,
        company_verified=True,
    )
    fake_db = _AccessFakeDb(profile=profile, buyer_need=buyer_need, buyer_profile=None)

    context = await resolve_buyer_context(fake_db, profile.profile_id)

    # Even with both self-reported BuyerNeed flags true, absence of an operator-verified
    # durable BuyerProfile row must never be silently upgraded to VERIFIED.
    assert context.verification_tier == "LIMITED"


async def test_resolve_buyer_context_rejects_non_buyer_profile() -> None:
    profile = _user_profile(user_type="GENERAL_VISITOR")
    fake_db = _AccessFakeDb(profile=profile, buyer_need=None, buyer_profile=None)

    with pytest.raises(BuyerAccessDenied) as excinfo:
        await resolve_buyer_context(fake_db, profile.profile_id)
    assert excinfo.value.code == "NOT_A_BUYER_PROFILE"


def _build_test_app(buyer_profile_id: uuid.UUID | None = None) -> FastAPI:
    """Standalone app around just this router.

    Merge STEP 21: the buyer subject is derived from the verified principal by
    ``app.core.router_auth.get_buyer_profile_id`` (the same object meetings.py exposes as
    ``_buyer_profile_header``), never from a request header. Overriding that dependency is
    how a test says "the session resolved to this event profile"; overriding it with a
    ``None``-returning callable is how it says "authenticated, but no buyer profile for the
    current event", which must still be 401 AUTH_REQUIRED.
    """

    app = FastAPI()
    app.add_exception_handler(AuthException, auth_exception_handler)
    app.include_router(buyer_match_router.build_buyer_match_router())
    if buyer_profile_id is not None:
        app.dependency_overrides[get_buyer_profile_id] = lambda: buyer_profile_id
    return app


async def test_router_rejects_non_buyer_profile_with_403(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def deny(db, profile_id):
        raise BuyerAccessDenied("NOT_A_BUYER_PROFILE", "바이어 프로파일이 아닙니다.")

    monkeypatch.setattr(buyer_match_router, "resolve_buyer_context", deny)

    app = _build_test_app(buyer_profile_id=uuid.uuid4())
    app.dependency_overrides[get_db] = lambda: iter([object()])

    with TestClient(app) as client:
        response = client.post("/buyer/matches", json={"filters": {}})
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "NOT_A_BUYER_PROFILE"


def test_router_rejects_a_caller_with_no_session() -> None:
    """STEP 21: sending the old X-Profile-Id header is no longer a way in."""

    app = _build_test_app()
    app.dependency_overrides[get_db] = lambda: iter([object()])

    with TestClient(app) as client:
        for method, path, body in (
            ("POST", "/buyer/matches", {"filters": {}}),
            ("GET", f"/buyer/matches/{uuid.uuid4()}", None),
            ("POST", "/buyer/compare", {"exhibitor_ids": [str(uuid.uuid4())]}),
        ):
            response = client.request(
                method, path, json=body, headers={"X-Profile-Id": str(uuid.uuid4())}
            )
            assert response.status_code == 401, (method, path, response.status_code)
            assert response.json()["code"] == "AUTH_REQUIRED"


def test_an_authenticated_session_without_an_event_buyer_profile_is_401() -> None:
    """``get_buyer_profile_id`` returns None when the session has no profile for the
    current event. The original ``_require_buyer_profile_id``'s ErrorBody-shaped 401 is
    preserved for exactly this case (STEP 21)."""

    app = _build_test_app()
    app.dependency_overrides[get_db] = lambda: iter([object()])
    app.dependency_overrides[get_buyer_profile_id] = lambda: None

    with TestClient(app) as client:
        response = client.post("/buyer/matches", json={"filters": {}})

    assert response.status_code == 401
    detail = response.json()["detail"]
    assert detail["code"] == "AUTH_REQUIRED"
    assert "message" in detail


def test_the_router_module_no_longer_reads_the_subject_from_a_client_header() -> None:
    """STEP 21 regression guard."""

    import inspect

    source = inspect.getsource(buyer_match_router)

    assert not hasattr(buyer_match_router, "_require_buyer_profile_id")
    assert 'Header(alias="X-Profile-Id")' not in source
    assert buyer_match_router.get_buyer_profile_id is get_buyer_profile_id
    # meetings.py re-exports the very same object, so there is one definition of "who is
    # the buyer" across the whole merged repo.
    assert meetings_router._buyer_profile_header is get_buyer_profile_id


# ---------------------------------------------------------------------------
# 4. compare with >4 ids rejected
# ---------------------------------------------------------------------------


def test_compare_request_schema_rejects_more_than_four_ids() -> None:
    with pytest.raises(ValidationError):
        BuyerCompareRequest(exhibitor_ids=[uuid.uuid4() for _ in range(5)])


async def test_router_compare_rejects_more_than_four_ids_with_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    buyer = _buyer("VERIFIED")

    async def allow(db, profile_id):
        return buyer

    monkeypatch.setattr(buyer_match_router, "resolve_buyer_context", allow)

    app = _build_test_app(buyer_profile_id=uuid.uuid4())
    app.dependency_overrides[get_db] = lambda: iter([object()])

    with TestClient(app) as client:
        response = client.post(
            "/buyer/compare",
            json={"exhibitor_ids": [str(uuid.uuid4()) for _ in range(5)]},
        )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# 5. compare shows UNKNOWN correctly
# ---------------------------------------------------------------------------


def test_compare_row_marks_missing_trade_condition_as_unknown_not_blank_or_no() -> None:
    exhibitor = Exhibitor(
        exhibitor_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        company_name="백주양조",
        master_approval_status="APPROVED",
    )
    participation = ExhibitorParticipation(
        participation_id=uuid.uuid4(),
        tenant_id=exhibitor.tenant_id,
        event_id=uuid.uuid4(),
        exhibitor_id=exhibitor.exhibitor_id,
        participation_status="APPROVED",
    )

    row = compare_service.build_compare_row(
        exhibitor_id=exhibitor.exhibitor_id,
        exhibitor=exhibitor,
        region_code=None,
        participation=participation,
        trade_condition=None,
        supply_capability=None,
        product_names=[],
        has_open_slot=None,
    )

    assert row.available is True
    # No trade_condition row at all => explicitly unknown, never a blank/false value.
    assert row.oem.known is False
    assert row.oem.value is None
    assert row.export.known is False
    assert row.order_scale.known is False
    assert row.meeting_availability.known is False


def test_compare_row_distinguishes_declared_unknown_from_missing_data() -> None:
    exhibitor = Exhibitor(
        exhibitor_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        company_name="백주양조",
        master_approval_status="APPROVED",
    )
    participation = ExhibitorParticipation(
        participation_id=uuid.uuid4(),
        tenant_id=exhibitor.tenant_id,
        event_id=uuid.uuid4(),
        exhibitor_id=exhibitor.exhibitor_id,
        participation_status="APPROVED",
    )
    trade_condition = TradeCondition(
        trade_condition_id=uuid.uuid4(),
        participation_id=participation.participation_id,
        oem_status="UNKNOWN",
        private_label_status="NO",
        export_status="YES",
    )

    row = compare_service.build_compare_row(
        exhibitor_id=exhibitor.exhibitor_id,
        exhibitor=exhibitor,
        region_code="REGION.SEOUL",
        participation=participation,
        trade_condition=trade_condition,
        supply_capability=None,
        product_names=["증류식 소주 A"],
        has_open_slot=True,
    )

    # The exhibitor explicitly declared "UNKNOWN" in their own trade condition - this is
    # knowable data (known=True) whose *value* happens to be the string "UNKNOWN", which is
    # different from "we never asked / have no row" (known=False).
    assert row.oem.known is True
    assert row.oem.value == "UNKNOWN"
    assert row.export.known is True
    assert row.export.value == "YES"
    assert row.region.known is True
    assert row.region.value == "REGION.SEOUL"
    assert row.meeting_availability == compare_service.CompareFieldData(True, True)


def test_compare_row_never_exposes_unapproved_exhibitor_data() -> None:
    exhibitor = Exhibitor(
        exhibitor_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        company_name="미승인업체",
        master_approval_status="DRAFT",
    )

    row = compare_service.build_compare_row(
        exhibitor_id=exhibitor.exhibitor_id,
        exhibitor=exhibitor,
        region_code="REGION.SEOUL",
        participation=None,
        trade_condition=None,
        supply_capability=None,
        product_names=["미승인 제품"],
        has_open_slot=True,
    )

    assert row.available is False
    assert row.company_name is None
    assert row.product_tech.known is False
    assert row.region.known is False
