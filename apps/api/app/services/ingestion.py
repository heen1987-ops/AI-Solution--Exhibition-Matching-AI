"""원천 데이터(방문객·참가업체·제품) 멱등 upsert 공용 로직.

app/api/v1/routers/imports.py(배치 import)와 app/api/v1/routers/webhooks.py(실시간 웹훅)가
이 모듈을 공유한다. 두 라우터는 "언제, 몇 건씩 들어오는가"만 다르고 "원천 레코드 1건을 내부
엔터티에 어떻게 반영하는가"는 완전히 같아야 하므로(설계문서 8.1/8.2절이 같은 source_record_id
+ source_updated_at 멱등 규칙을 공유한다) 로직을 한 곳에 모았다.

멱등 upsert 규칙 (설계문서 8.1절)
---------------------------------
1. (source_system_id, object_type, source_record_id)로 integration.external_reference를 찾는다.
2. 없으면 새 내부 엔터티를 만들고 external_reference를 새로 만든다.
3. 있고 source_updated_at이 저장된 값보다 새로우면 내부 엔터티를 갱신하고 external_reference를
   갱신한다.
4. 있고 source_updated_at이 저장된 값 이하이면 오래된 재전송이므로 아무것도 바꾸지 않는다
   (skipped_stale=True로 보고한다 - 오류가 아니라 정상적인 멱등 무시다).

이 모듈이 던지는 IngestionError는 "이 행 하나가 잘못됐다"는 신호다. 호출부(라우터)가 이를
잡아 배치 전체를 막지 않고 오류 목록 항목 하나로 변환해야 한다(설계문서 8.1절 "잘못된 행은
전체 배치를 중단하지 않고 오류 격리 목록으로 보낸다").
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import compute_lookup_hmac
from app.models.exhibitor import (
    EventProduct,
    Exhibitor,
    ExhibitorBusinessType,
    ExhibitorParticipation,
    ExhibitorStaff,
    Product,
    ProductImage,
)
from app.models.identity import UserAccount, UserIdentity
from app.models.integration import ExternalReference, SourceSystem
from app.models.profile import ProfileAttribute, UserProfile
from app.schemas.imports import (
    ExhibitorImportRow,
    ProductImportRow,
    TaxonomyAttributeRef,
    VisitorImportRow,
)


class IngestionError(Exception):
    """행 단위 처리 실패. 라우터가 잡아서 ImportRowError/SyncRowError로 변환한다.

    message는 사용자에게 노출해도 안전한 문구여야 한다 (내부 예외 원문을 그대로 담지 않는다 -
    인터페이스 명세 4.4절).
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class UpsertOutcome:
    internal_id: UUID
    created: bool
    skipped_stale: bool = False


def hash_payload(payload: dict[str, Any]) -> bytes:
    """integration.external_reference.source_payload_hash용 변경검사 해시.

    dict 키 순서에 좌우되지 않도록 정렬 직렬화한 뒤 SHA-256을 취한다. 보안 목적이 아니라
    순수 변경 감지용이라 HMAC이 아닌 평문 해시로 충분하다.
    """

    normalized = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(normalized.encode("utf-8")).digest()


async def get_or_create_source_system(
    db: AsyncSession, *, tenant_id: UUID, system_code: str, sync_type: str = "API"
) -> SourceSystem:
    stmt = select(SourceSystem).where(
        SourceSystem.tenant_id == tenant_id, SourceSystem.system_code == system_code
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        return existing

    source_system = SourceSystem(
        tenant_id=tenant_id,
        system_code=system_code,
        system_name=system_code,
        sync_type=sync_type,
        active=True,
    )
    db.add(source_system)
    await db.flush()
    return source_system


async def _find_external_reference(
    db: AsyncSession, *, source_system_id: UUID, object_type: str, external_id: str
) -> ExternalReference | None:
    stmt = select(ExternalReference).where(
        ExternalReference.source_system_id == source_system_id,
        ExternalReference.object_type == object_type,
        ExternalReference.external_id == external_id,
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def _upsert_external_reference(
    db: AsyncSession,
    *,
    existing: ExternalReference | None,
    source_system_id: UUID,
    object_type: str,
    external_id: str,
    internal_id: UUID,
    source_updated_at: datetime,
    payload_hash: bytes,
) -> None:
    if existing is None:
        db.add(
            ExternalReference(
                source_system_id=source_system_id,
                object_type=object_type,
                external_id=external_id,
                internal_id=internal_id,
                source_updated_at=source_updated_at,
                source_payload_hash=payload_hash,
                sync_status="SYNCED",
            )
        )
    else:
        existing.source_updated_at = source_updated_at
        existing.source_payload_hash = payload_hash
        existing.sync_status = "SYNCED"
        existing.last_synced_at = func.now()


async def _apply_taxonomy_business_types(
    db: AsyncSession, *, exhibitor_id: UUID, categories: list[TaxonomyAttributeRef]
) -> None:
    """08 문서 4.2절 "복수 유형 가능" - 매 동기화마다 전체 목록을 교체한다(멱등 PUT과 동일 의미)."""

    await db.execute(
        delete(ExhibitorBusinessType).where(
            ExhibitorBusinessType.exhibitor_id == exhibitor_id
        )
    )
    for ref in categories:
        db.add(
            ExhibitorBusinessType(
                exhibitor_id=exhibitor_id,
                taxonomy_version_id=ref.taxonomy_version_id,
                concept_id=ref.concept_id,
            )
        )


async def _replace_external_sync_profile_attributes(
    db: AsyncSession,
    *,
    profile_id: UUID,
    requirement_level: str,
    refs: list[TaxonomyAttributeRef],
) -> None:
    """방문객 관심분야·관람목적을 EXTERNAL_SYNC 출처 속성으로 동기화한다.

    사용자가 앱에서 직접 고른 속성(USER_SELECTED 등)은 건드리지 않고, 이전 동기화로 생긴
    EXTERNAL_SYNC 속성만 지우고 다시 넣는다 - 원천 재전송 시 매번 새 행이 누적되는 것을 막는다.
    """

    await db.execute(
        delete(ProfileAttribute).where(
            ProfileAttribute.profile_id == profile_id,
            ProfileAttribute.source_type == "EXTERNAL_SYNC",
            ProfileAttribute.requirement_level == requirement_level,
        )
    )
    for priority, ref in enumerate(refs, start=1):
        db.add(
            ProfileAttribute(
                profile_id=profile_id,
                taxonomy_version_id=ref.taxonomy_version_id,
                concept_id=ref.concept_id,
                attribute_code=ref.attribute_code,
                value_json={"value": ref.value},
                requirement_level=requirement_level,
                priority=priority,
                source_type="EXTERNAL_SYNC",
                confidence=1,
            )
        )


async def upsert_visitor(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    event_id: UUID,
    source_system_id: UUID,
    row: VisitorImportRow,
) -> UpsertOutcome:
    """방문객 사전등록 레코드를 profile.user_profile(+user_account, identity.user_identity)로
    반영한다. 반환하는 internal_id는 profile.user_profile.profile_id다.

    TODO(식별정보 암호화): identity.user_identity.name_enc/phone_enc/email_enc는 KMS 기반
    봉투 암호화가 준비되기 전까지 NULL로 남긴다(app/models/identity.py 모듈 docstring이 이미
    이 책임을 "애플리케이션 서비스 계층"으로 미뤄 두었다). 조회에 필요한 phone_hmac/
    email_hmac만 채운다.
    """

    existing_ref = await _find_external_reference(
        db,
        source_system_id=source_system_id,
        object_type="VISITOR",
        external_id=row.source_record_id,
    )
    if existing_ref is not None and row.source_updated_at <= existing_ref.source_updated_at:
        return UpsertOutcome(existing_ref.internal_id, created=False, skipped_stale=True)

    payload_hash = hash_payload(row.model_dump(mode="json"))

    if existing_ref is None:
        account = UserAccount(authentication_state="PHONE_VERIFIED")
        db.add(account)
        await db.flush()

        identity = UserIdentity(user_id=account.user_id)
        db.add(identity)

        profile = UserProfile(
            tenant_id=tenant_id,
            event_id=event_id,
            user_id=account.user_id,
            user_type="GENERAL_VISITOR",
            profile_status="DRAFT",
        )
        db.add(profile)
        await db.flush()
    else:
        profile = await db.get(UserProfile, existing_ref.internal_id)
        if profile is None:
            raise IngestionError(
                "VISITOR_PROFILE_MISSING",
                "이전에 연계된 방문객 프로파일을 찾을 수 없습니다.",
            )
        identity_stmt = select(UserIdentity).where(UserIdentity.user_id == profile.user_id)
        identity = (await db.execute(identity_stmt)).scalar_one_or_none()
        if identity is None:
            identity = UserIdentity(user_id=profile.user_id)
            db.add(identity)

    if row.phone:
        identity.phone_hmac = compute_lookup_hmac(row.phone)
        identity.phone_verified_at = identity.phone_verified_at or row.source_updated_at
    if row.email:
        identity.email_hmac = compute_lookup_hmac(row.email)

    await _replace_external_sync_profile_attributes(
        db,
        profile_id=profile.profile_id,
        requirement_level="PREFERRED",
        refs=[*row.interest_categories, *row.visit_goals],
    )

    await _upsert_external_reference(
        db,
        existing=existing_ref,
        source_system_id=source_system_id,
        object_type="VISITOR",
        external_id=row.source_record_id,
        internal_id=profile.profile_id,
        source_updated_at=row.source_updated_at,
        payload_hash=payload_hash,
    )

    return UpsertOutcome(profile.profile_id, created=existing_ref is None)


async def upsert_exhibitor(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    event_id: UUID,
    source_system_id: UUID,
    row: ExhibitorImportRow,
) -> UpsertOutcome:
    """참가업체 신청 레코드를 exhibition.exhibitor(+business_type, participation, staff)로
    반영한다. 반환하는 internal_id는 exhibition.exhibitor.exhibitor_id다.

    참가업체 신청은 업체 상시정보와 "이번 행사 참가" 신청이 한 폼에서 함께 들어오므로
    (설계문서 2.3절), 이 함수는 Exhibitor 마스터와 이 event_id에 대한
    ExhibitorParticipation을 함께 만든다(08 문서 20절 "기존 참가신청 데이터 수신 → 업체
    기본 프로파일 생성" 절차와 일치).
    """

    existing_ref = await _find_external_reference(
        db,
        source_system_id=source_system_id,
        object_type="EXHIBITOR",
        external_id=row.source_record_id,
    )
    if existing_ref is not None and row.source_updated_at <= existing_ref.source_updated_at:
        return UpsertOutcome(existing_ref.internal_id, created=False, skipped_stale=True)

    payload_hash = hash_payload(row.model_dump(mode="json"))

    if existing_ref is None:
        exhibitor = Exhibitor(tenant_id=tenant_id, company_name=row.legal_name)
        db.add(exhibitor)
        await db.flush()
    else:
        exhibitor = await db.get(Exhibitor, existing_ref.internal_id)
        if exhibitor is None:
            raise IngestionError("EXHIBITOR_MISSING", "이전에 연계된 업체를 찾을 수 없습니다.")
        exhibitor.company_name = row.legal_name

    # 08 문서 2.3절 "etc_text(양조장 이야기)"를 담을 전용 컬럼이 exhibition.exhibitor에
    # 없어(실제 모델 컬럼 확인 결과) 상시 소개정보 컬럼인 company_summary에 담는다.
    # display_name(간판명)도 마찬가지로 전용 컬럼이 없어 이번 범위에서는 저장하지 않는다.
    # TODO(exhibition 도메인 후속 마이그레이션): brand/display_name 컬럼 추가 여부 결정.
    if row.story:
        exhibitor.company_summary = row.story
    if row.website_url:
        exhibitor.website_url = row.website_url
    if row.region is not None:
        exhibitor.region_taxonomy_version_id = row.region.taxonomy_version_id
        exhibitor.region_concept_id = row.region.concept_id

    # exhibitor.business_type_taxonomy_version_id/concept_id("대표 유형" 단일 컬럼, db-erd
    # 12.2절)는 여기서 채우지 않는다 - 08 4.2절은 복수 유형을 전제하고, 그 전체 목록의 정본은
    # 아래 ExhibitorBusinessType이다. 대표 유형 하나를 자동으로 고르는 규칙은 정해지지 않아
    # NULL로 남긴다(CHECK business_type_pair_complete는 두 컬럼이 모두 NULL이면 통과한다).
    await db.flush()
    await _apply_taxonomy_business_types(
        db, exhibitor_id=exhibitor.exhibitor_id, categories=row.categories
    )

    participation_stmt = select(ExhibitorParticipation).where(
        ExhibitorParticipation.tenant_id == tenant_id,
        ExhibitorParticipation.event_id == event_id,
        ExhibitorParticipation.exhibitor_id == exhibitor.exhibitor_id,
    )
    participation = (await db.execute(participation_stmt)).scalar_one_or_none()
    if participation is None:
        participation = ExhibitorParticipation(
            tenant_id=tenant_id,
            event_id=event_id,
            exhibitor_id=exhibitor.exhibitor_id,
            participation_status="APPLIED",
            promotion_summary=row.promotion_description,
        )
        db.add(participation)
        await db.flush()
    elif row.promotion_description:
        participation.promotion_summary = row.promotion_description

    if row.manager_name:
        staff_stmt = select(ExhibitorStaff).where(
            ExhibitorStaff.participation_id == participation.participation_id,
            ExhibitorStaff.display_name == row.manager_name,
        )
        staff = (await db.execute(staff_stmt)).scalar_one_or_none()
        if staff is None:
            # TODO(담당자 연락처 저장 경로 미정): exhibition.exhibitor_staff에는 전화번호/
            # 이메일 컬럼이 없다(db-erd 12.4절도 명시하지 않는다). manager_phone/
            # manager_email은 당장은 저장하지 않으며, 후속 마이그레이션에서 컬럼을 추가하거나
            # identity 도메인과 연결하는 방법을 정해야 한다.
            db.add(
                ExhibitorStaff(
                    participation_id=participation.participation_id,
                    display_name=row.manager_name,
                )
            )

    await _upsert_external_reference(
        db,
        existing=existing_ref,
        source_system_id=source_system_id,
        object_type="EXHIBITOR",
        external_id=row.source_record_id,
        internal_id=exhibitor.exhibitor_id,
        source_updated_at=row.source_updated_at,
        payload_hash=payload_hash,
    )

    return UpsertOutcome(exhibitor.exhibitor_id, created=existing_ref is None)


async def upsert_product(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    event_id: UUID,
    source_system_id: UUID,
    row: ProductImportRow,
) -> UpsertOutcome:
    """제품 레코드를 exhibition.product(+event_product, product_image)로 반영한다.

    부모 업체는 같은 배치 안에서 먼저 처리돼 있거나, 이전에 이미 연계되어 있어야 한다
    (row.exhibitor_source_record_id로 integration.external_reference를 조회한다).
    """

    existing_ref = await _find_external_reference(
        db,
        source_system_id=source_system_id,
        object_type="PRODUCT",
        external_id=row.source_record_id,
    )
    if existing_ref is not None and row.source_updated_at <= existing_ref.source_updated_at:
        return UpsertOutcome(existing_ref.internal_id, created=False, skipped_stale=True)

    exhibitor_ref = await _find_external_reference(
        db,
        source_system_id=source_system_id,
        object_type="EXHIBITOR",
        external_id=row.exhibitor_source_record_id,
    )
    if exhibitor_ref is None:
        raise IngestionError(
            "EXHIBITOR_NOT_FOUND",
            "부모 업체(exhibitor_source_record_id)가 먼저 연계되어 있어야 합니다.",
        )
    exhibitor_id = exhibitor_ref.internal_id

    payload_hash = hash_payload(row.model_dump(mode="json"))

    if existing_ref is None:
        product = Product(exhibitor_id=exhibitor_id, product_name=row.product_name)
        db.add(product)
    else:
        product = await db.get(Product, existing_ref.internal_id)
        if product is None:
            raise IngestionError("PRODUCT_MISSING", "이전에 연계된 제품을 찾을 수 없습니다.")
        if product.exhibitor_id != exhibitor_id:
            raise IngestionError(
                "PRODUCT_EXHIBITOR_MISMATCH", "제품이 이미 다른 업체에 연계되어 있습니다."
            )
        product.product_name = row.product_name

    if row.category is not None:
        product.category_taxonomy_version_id = row.category.taxonomy_version_id
        product.category_concept_id = row.category.concept_id
    if row.raw_description:
        product.product_summary = row.raw_description
    if row.alcohol_percentage is not None:
        product.alcohol_percentage = row.alcohol_percentage

    await db.flush()

    participation_stmt = select(ExhibitorParticipation).where(
        ExhibitorParticipation.tenant_id == tenant_id,
        ExhibitorParticipation.event_id == event_id,
        ExhibitorParticipation.exhibitor_id == exhibitor_id,
    )
    participation = (await db.execute(participation_stmt)).scalar_one_or_none()
    if participation is None:
        raise IngestionError(
            "PARTICIPATION_NOT_FOUND",
            "이 행사에 대한 업체 참가정보가 아직 없습니다. 업체 import를 먼저 처리하세요.",
        )

    event_product_stmt = select(EventProduct).where(
        EventProduct.event_id == event_id, EventProduct.product_id == product.product_id
    )
    event_product = (await db.execute(event_product_stmt)).scalar_one_or_none()
    if event_product is None:
        db.add(
            EventProduct(
                tenant_id=tenant_id,
                event_id=event_id,
                participation_id=participation.participation_id,
                product_id=product.product_id,
            )
        )

    if row.image_urls:
        existing_keys_stmt = select(ProductImage.storage_key).where(
            ProductImage.product_id == product.product_id
        )
        existing_keys = {row_[0] for row_ in (await db.execute(existing_keys_stmt)).all()}
        next_order_stmt = select(
            func.coalesce(func.max(ProductImage.display_order), -1)
        ).where(ProductImage.product_id == product.product_id)
        next_order = (await db.execute(next_order_stmt)).scalar_one() + 1
        for url in row.image_urls:
            if url in existing_keys:
                continue
            # TODO(미디어 파이프라인): storage_key에 원천 URL을 임시로 담는다. 접근통제·
            # 악성파일 검사(설계문서 9절)를 거치는 실제 오브젝트 스토리지 업로드가 준비되면
            # 이 값을 실제 key로 교체해야 한다.
            db.add(
                ProductImage(
                    product_id=product.product_id,
                    storage_key=url,
                    display_order=next_order,
                    approval_status="PENDING",
                )
            )
            next_order += 1

    await _upsert_external_reference(
        db,
        existing=existing_ref,
        source_system_id=source_system_id,
        object_type="PRODUCT",
        external_id=row.source_record_id,
        internal_id=product.product_id,
        source_updated_at=row.source_updated_at,
        payload_hash=payload_hash,
    )

    return UpsertOutcome(product.product_id, created=existing_ref is None)
