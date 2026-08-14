"""업체 공개 거래조건 요약 + 협력유형/희망 바이어 뷰 API 계약.

WAVE2C BACKEND-EXHIBITOR-PREFERENCE. 모델은 ``app/models/exhibitor_preference.py`` 참고
(그 파일 docstring에 이 트랙이 기존 ``TradeCondition``/``ExhibitorBuyerPreference``와
왜, 어떻게 나뉘는지 전체 근거가 있다).

``app/schemas/partner.py``의 ``TaxonomyRef``/``TradeAvailabilityStatus``와 개념적으로
동일한 타입을 이 파일에서 다시 선언한다 - 모델 계층과 동일하게, 여러 에이전트가 동시에
건드리는 파일을 이 트랙이 직접 import하지 않기 위한 의도적 중복이다.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

TradeAvailabilityStatus = Literal["YES", "NO", "CONDITIONAL", "NEGOTIABLE", "UNKNOWN"]
PreferenceApprovalStatus = Literal["DRAFT", "APPROVED", "REJECTED"]


class TaxonomyRef(BaseModel):
    """이미 해석된 온톨로지 개념 참조 (taxonomy_version_id, concept_id)."""

    taxonomy_version_id: UUID
    concept_id: UUID


# ---------------------------------------------------------------------------
# 업체 단위 거래 개방도 선언 (exhibitor_trade_availability) - 이 트랙이 저장하는 유일한
# "가용성" 필드 2개. 나머지(oem/pb/export/moq/lead_time/channel/region)는 아래
# ExhibitorPublicTradePreferenceRead에서 기존 TradeCondition/TradeConditionTerm을 조회한
# 값으로 채워진다 - 저장은 하지 않는다.
# ---------------------------------------------------------------------------


class ExhibitorTradeAvailabilityUpdate(BaseModel):
    """PUT /exhibitor-preference/{exhibitor_id}/availability 요청.

    필드를 ``None``으로 두면 "미제공"(값을 바꾸지 않음)이지 "UNKNOWN으로 설정"이 아니다 -
    부분수정 의미다. 명시적으로 UNKNOWN을 선언하려면 값 자체를 ``"UNKNOWN"``으로 보내야
    한다. 이 구분이 "UNKNOWN이 절대 암묵적으로 YES/NO로 치환되지 않는다"는 요구사항의
    핵심이다: 요청에 없는 필드는 DB의 기존 값(최초 생성 시에는 컬럼 기본값 UNKNOWN)을
    그대로 유지할 뿐, 서비스 계층이 그 값을 추론해서 채우지 않는다.
    """

    new_trade_available: TradeAvailabilityStatus | None = None
    meeting_available: TradeAvailabilityStatus | None = None


class ExhibitorTradeAvailabilityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    exhibitor_id: UUID
    new_trade_available: TradeAvailabilityStatus
    meeting_available: TradeAvailabilityStatus
    approval_status: PreferenceApprovalStatus


# ---------------------------------------------------------------------------
# 협력유형 선호 (exhibitor_cooperation_type) - TRADE.* 온톨로지, 다대다 교체(PUT).
# ---------------------------------------------------------------------------


class ExhibitorCooperationTypeReplaceRequest(BaseModel):
    """PUT /exhibitor-preference/{exhibitor_id}/cooperation-types 요청.

    전체 교체(PUT) 의미 - BuyerPreferenceReplaceRequest(partner.py)와 동일한 관례.
    빈 목록을 보내면 기존 선호 협력유형을 모두 비활성화한다(행 삭제가 아니라
    ``active=False``로 남긴다 - 감사 추적을 위해, exhibitor.py의 다른 "active" 플래그
    필드들과 동일한 관례).
    """

    cooperation_types: list[TaxonomyRef] = Field(default_factory=list)


class ExhibitorCooperationTypeRead(BaseModel):
    exhibitor_cooperation_type_id: UUID
    cooperation_type: TaxonomyRef
    active: bool


class ExhibitorCooperationTypeListResponse(BaseModel):
    exhibitor_id: UUID
    items: list[ExhibitorCooperationTypeRead]


# ---------------------------------------------------------------------------
# 합성 읽기 뷰 (GET /exhibitor-preference/{exhibitor_id}) - 저장소 여러 개를 조합한다.
# ---------------------------------------------------------------------------


class MinOrderScale(BaseModel):
    """08 27.4절 volume_min/volume_max(ExhibitorBuyerPreference)를 그대로 노출한다."""

    min: int | None = None
    max: int | None = None


class ExhibitorPublicTradePreferenceRead(BaseModel):
    """공개 거래조건 요약.

    new_trade_available/meeting_available은 이 트랙의 전용 저장소(exhibitor_trade_
    availability)에서, 나머지는 기존 exhibitor.TradeCondition(업체 공통조건, APPROVED만)과
    TradeConditionTerm에서 합성한다. 대응하는 승인된 공통조건이 없으면 oem/pb/export는
    "UNKNOWN", moq/expected_lead_time_days는 ``None``으로 남는다 - 절대 NO로 임의 치환하지
    않는다.
    """

    exhibitor_id: UUID
    new_trade_available: TradeAvailabilityStatus
    oem_available: TradeAvailabilityStatus
    pb_available: TradeAvailabilityStatus
    export_available: TradeAvailabilityStatus
    meeting_available: TradeAvailabilityStatus
    distribution_channel_codes: list[str] = Field(default_factory=list)
    supply_region_codes: list[str] = Field(default_factory=list)
    moq: int | None = None
    expected_lead_time_days: int | None = None
    source_trade_condition_approved: bool = Field(
        description=(
            "oem/pb/export/moq/expected_lead_time_days/채널/지역 코드의 출처가 된 승인된"
            " TradeCondition 공통조건이 있었는지 여부. false면 위 필드들은 모두 미선언"
            " 상태(UNKNOWN/빈 목록/None)다."
        )
    )


class ExhibitorBuyerPreferenceSummaryRead(BaseModel):
    """희망 바이어 선호 요약.

    preferred_buyer_types/preferred_channels/preferred_regions/min_order_scale은 기존
    ``ExhibitorBuyerPreference``(exhibition.buyer_preference, partner.py가 CRUD 소유)를
    그대로 읽어 조합한다 - 이 트랙은 저장하지 않는다. cooperation_types만 이 트랙 소유
    저장소(exhibitor_cooperation_type)에서 온다.
    """

    preferred_buyer_types: list[str] = Field(default_factory=list)
    preferred_channels: list[str] = Field(default_factory=list)
    preferred_regions: list[str] = Field(default_factory=list)
    min_order_scale: MinOrderScale = Field(default_factory=MinOrderScale)
    cooperation_types: list[str] = Field(default_factory=list)
    has_buyer_preference: bool = Field(
        description=(
            "위 다섯 차원(buyer_type/channel/region/volume/cooperation_type) 중 하나라도"
            " 선언된 행이 있으면 true. false는 '선호 없음'이 아니라 '미선언'을 뜻하며,"
            " 다운스트림 매칭은 이를 감점 신호로 쓰면 안 된다(PROJECT_SCOPE 규칙)."
        )
    )


class ExhibitorPreferenceRead(BaseModel):
    """GET /exhibitor-preference/{exhibitor_id} 응답 전체."""

    exhibitor_id: UUID
    trade: ExhibitorPublicTradePreferenceRead
    buyer_preference: ExhibitorBuyerPreferenceSummaryRead
