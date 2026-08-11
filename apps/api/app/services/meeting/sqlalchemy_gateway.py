"""``MeetingGateway`` 프로토콜(buyer_matching.py)의 실제 SQLAlchemy/PostgreSQL 구현.

동시성·원자성 처리는 ``app/api/v1/routers/meetings.py``가 이미 검증한 것과 동일한 기법을
그대로 재사용한다: 슬롯 점유는 "SELECT 후 UPDATE"가 아니라 단일 조건부
UPDATE(``WHERE status='OPEN' AND reserved_count < capacity``)로 원자적으로 수행하고,
상담 자체(``meeting`` 행)의 상태 전이는 ``SELECT ... FOR UPDATE``로 행을 먼저 잠근 뒤
``row_version`` 낙관적 잠금을 검사한다. 통합 저장소에는 상담 표면이 하나뿐이므로 이
게이트웨이와 라우터는 반드시 같은 전략을 쓴다 - 두 코드 경로가 같은 테이블을 다르게
잠그면 이중예약 방지가 무너진다.
"""

from __future__ import annotations

import functools
import uuid

from meet_ai.ontology import Catalog, load_catalog
from meet_ai.ontology.catalog import stable_uuid
from sqlalchemy import case, func, literal, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.consent import AuditLog
from app.models.exhibitor import ExhibitorParticipation, ExhibitorStaff, Product
from app.models.identity import UserAccount, UserIdentity
from app.models.meeting import (
    AvailabilitySlot,
    MeetingContactShare,
    MeetingRequest,
    MeetingSlotRequest,
    MeetingStatusHistory,
)
from app.models.profile import UserProfile

#: U-14 화면의 상담주제 칩과 동일한 최선노력 네임스페이스 보정(meetings.py와 동일한 이유로
#: BIZ_GOAL을 잠정 채택 - 상담주제 전용 네임스페이스가 6단계 온톨로지에 생기면 교체).
_TOPIC_NAMESPACE_FALLBACKS: tuple[str, ...] = ("BIZ_GOAL",)


@functools.lru_cache(maxsize=1)
def _catalog() -> Catalog:
    return load_catalog()


@functools.lru_cache(maxsize=1)
def _concept_id_to_code() -> dict[uuid.UUID, str]:
    catalog = _catalog()
    return {stable_uuid("concept", item["code"]): item["code"] for item in catalog.concepts}


class SqlAlchemyMeetingGateway:
    """``buyer_matching.MeetingGateway``의 프로덕션 구현."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_profile(self, profile_id: uuid.UUID) -> UserProfile | None:
        return await self._db.get(UserProfile, profile_id)

    async def get_account(self, user_id: uuid.UUID) -> UserAccount | None:
        return await self._db.get(UserAccount, user_id)

    async def get_participation_for_exhibitor(
        self, *, tenant_id: uuid.UUID, event_id: uuid.UUID, exhibitor_id: uuid.UUID
    ) -> ExhibitorParticipation | None:
        stmt = select(ExhibitorParticipation).where(
            ExhibitorParticipation.tenant_id == tenant_id,
            ExhibitorParticipation.event_id == event_id,
            ExhibitorParticipation.exhibitor_id == exhibitor_id,
        )
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def get_participation(
        self, participation_id: uuid.UUID
    ) -> ExhibitorParticipation | None:
        return await self._db.get(ExhibitorParticipation, participation_id)

    async def get_product(self, product_id: uuid.UUID) -> Product | None:
        return await self._db.get(Product, product_id)

    async def get_staff(self, staff_id: uuid.UUID) -> ExhibitorStaff | None:
        staff = await self._db.get(ExhibitorStaff, staff_id)
        if staff is None or not staff.active:
            return None
        return staff

    async def get_identity_by_user_id(self, user_id: uuid.UUID) -> UserIdentity | None:
        stmt = select(UserIdentity).where(UserIdentity.user_id == user_id)
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def get_meeting(self, meeting_id: uuid.UUID) -> MeetingRequest | None:
        return await self._db.get(MeetingRequest, meeting_id)

    async def get_meeting_locked(self, meeting_id: uuid.UUID) -> MeetingRequest | None:
        stmt = (
            select(MeetingRequest)
            .where(MeetingRequest.meeting_id == meeting_id)
            .with_for_update()
        )
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def list_by_buyer(self, buyer_profile_id: uuid.UUID) -> list[MeetingRequest]:
        stmt = (
            select(MeetingRequest)
            .where(MeetingRequest.buyer_profile_id == buyer_profile_id)
            .order_by(MeetingRequest.created_at.desc())
        )
        return list((await self._db.execute(stmt)).scalars().all())

    async def list_by_participation(
        self, participation_id: uuid.UUID
    ) -> list[MeetingRequest]:
        stmt = (
            select(MeetingRequest)
            .where(MeetingRequest.participation_id == participation_id)
            .order_by(MeetingRequest.created_at.desc())
        )
        return list((await self._db.execute(stmt)).scalars().all())

    async def get_slot(self, slot_id: uuid.UUID) -> AvailabilitySlot | None:
        return await self._db.get(AvailabilitySlot, slot_id)

    async def reserve_slot(
        self, *, slot_id: uuid.UUID, participation_id: uuid.UUID
    ) -> AvailabilitySlot | None:
        new_reserved_count = AvailabilitySlot.reserved_count + 1
        stmt = (
            update(AvailabilitySlot)
            .where(
                AvailabilitySlot.availability_slot_id == slot_id,
                AvailabilitySlot.participation_id == participation_id,
                AvailabilitySlot.status == "OPEN",
                AvailabilitySlot.reserved_count < AvailabilitySlot.capacity,
                AvailabilitySlot.start_at > func.now(),
            )
            .values(
                reserved_count=new_reserved_count,
                status=case(
                    (new_reserved_count >= AvailabilitySlot.capacity, literal("FULL")),
                    else_=AvailabilitySlot.status,
                ),
                row_version=AvailabilitySlot.row_version + 1,
            )
            .returning(AvailabilitySlot)
        )
        result = await self._db.execute(stmt)
        return result.scalars().first()

    async def release_slot(self, slot_id: uuid.UUID) -> None:
        new_reserved_count = AvailabilitySlot.reserved_count - 1
        stmt = (
            update(AvailabilitySlot)
            .where(
                AvailabilitySlot.availability_slot_id == slot_id,
                AvailabilitySlot.reserved_count > 0,
            )
            .values(
                reserved_count=new_reserved_count,
                status=case(
                    (AvailabilitySlot.status == "BLOCKED", literal("BLOCKED")),
                    (new_reserved_count < AvailabilitySlot.capacity, literal("OPEN")),
                    else_=AvailabilitySlot.status,
                ),
                row_version=AvailabilitySlot.row_version + 1,
            )
        )
        await self._db.execute(stmt)

    async def get_slot_requests(self, meeting_id: uuid.UUID) -> list[MeetingSlotRequest]:
        stmt = select(MeetingSlotRequest).where(MeetingSlotRequest.meeting_id == meeting_id)
        return list((await self._db.execute(stmt)).scalars().all())

    async def add_slot_request(self, slot_request: MeetingSlotRequest) -> None:
        self._db.add(slot_request)

    async def get_contact_share(self, meeting_id: uuid.UUID) -> MeetingContactShare | None:
        stmt = select(MeetingContactShare).where(MeetingContactShare.meeting_id == meeting_id)
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def add_contact_share(self, contact_share: MeetingContactShare) -> None:
        self._db.add(contact_share)

    async def add_meeting(self, meeting: MeetingRequest) -> None:
        self._db.add(meeting)

    async def add_status_history(self, entry: MeetingStatusHistory) -> None:
        self._db.add(entry)

    async def add_audit_log(self, entry: AuditLog) -> None:
        self._db.add(entry)

    async def resolve_topic_concept(
        self, topic_code: str
    ) -> tuple[uuid.UUID, uuid.UUID, str] | None:
        catalog = _catalog()
        candidates = [topic_code]
        if "." not in topic_code:
            candidates.extend(f"{ns}.{topic_code}" for ns in _TOPIC_NAMESPACE_FALLBACKS)
        for candidate in candidates:
            try:
                catalog.get(candidate)
            except KeyError:
                continue
            return (
                stable_uuid("taxonomy-version", catalog.version),
                stable_uuid("concept", candidate),
                candidate,
            )
        return None

    async def concept_code_for(self, concept_id: uuid.UUID | None) -> str | None:
        if concept_id is None:
            return None
        return _concept_id_to_code().get(concept_id)

    async def commit(self) -> None:
        await self._db.commit()

    async def rollback(self) -> None:
        await self._db.rollback()
