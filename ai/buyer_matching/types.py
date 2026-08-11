"""AI-BUYER-MATCH(WAVE 2C)가 주고받는 순수 데이터 구조.

ai/types.py(AI_SEARCH 트랙)와 같은 원칙을 따른다 - 파이프라인 단계마다 새 dataclass를
만드는 대신, 이 모듈이 정의하는 소수의 구조를 hard_filter/score_b2e/score_e2b/pipeline
사이에서 그대로 주고받는다. 이 모듈 자체는 SQLAlchemy나 DB에 의존하지 않는 순수 라이브러리다
(BACKEND-BUYER-MATCH 트랙이 ORM 객체를 이 dataclass로 매핑해 호출한다).

여기 등장하는 코드값(product/technology/business_goal/channel/region/cooperation_type 등)은
전부 ``src/meet_ai/ontology/catalog.v1.json``(PRODUCT_CATEGORY/INGREDIENT/SUPPLY_CAPACITY/
BUSINESS_GOAL/CHANNEL/REGION/TRADE_TYPE/BUYER_TYPE concept_type)에 실재하는 코드여야 한다
(DECISION-004). 이 라이브러리는 코드 문자열을 불투명(opaque)하게 다루며 카탈로그 검증은
호출자/평가 하네스의 책임이다 - ai/evaluation/buyer_matching이 실제 카탈로그 코드만 쓰는지
검증한다.

결정성(Determinism): 이 패키지 어디에도 ``datetime.now()``/``uuid4()`` 같은 비결정 호출이
없다. "행사 참가가 지금 활성 상태인가" 같은 시각 의존 판단은 호출자가 이미 계산해
``participation_status`` 같은 값으로 넘겨준다 - 이 라이브러리 내부에서 시각을 재는 일은 없다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union

# 호출자가 SQLAlchemy PK로 uuid.UUID를 쓰든 평가 하네스가 문자열을 쓰든 상관없이 받아들이는
# 불투명 식별자 타입.
Identifier = Union[str, "uuid.UUID"]  # noqa: F821 - 순수 타입힌트 목적의 전방참조, uuid 미임포트로 결합도를 낮춤

# --------------------------------------------------------------------------
# 상태값 상수. apps/api/app/models/exhibitor.py의 동명 상수와 같은 원칙(단일 진실 공급원,
# 애플리케이션 코드와 검증 로직이 같은 튜플을 참조)을 따르되, 이 패키지는 DB에 의존하지
# 않으므로 값 목록만 여기 복제해 둔다. 값이 갈리면 그건 CONTRACTS 트랙과의 통합 시점에
# 명시적으로 맞춰야 한다(이 파일이 그 매핑의 단일 지점이 되도록 주석에 원본 위치를 남긴다).
# --------------------------------------------------------------------------

#: apps/api/app/models/exhibitor.py MASTER_APPROVAL_STATUSES와 동일한 값 집합.
EXHIBITOR_APPROVAL_STATUSES: tuple[str, ...] = ("DRAFT", "APPROVED", "REJECTED")
_EXHIBITOR_APPROVAL_ALLOWED: frozenset[str] = frozenset({"APPROVED"})

#: apps/api/app/models/exhibitor.py PARTICIPATION_STATUSES와 동일한 값 집합.
PARTICIPATION_STATUSES: tuple[str, ...] = ("APPLIED", "APPROVED", "CANCELLED")
_PARTICIPATION_ACTIVE_ALLOWED: frozenset[str] = frozenset({"APPROVED"})

#: apps/api/app/models/exhibitor.py TRADE_AVAILABILITY_STATUSES와 동일한 값 집합
#: ("미등록과 불가능 분리" - boolean이 아니라 5단계).
TRADE_AVAILABILITY_STATUSES: tuple[str, ...] = ("YES", "NO", "CONDITIONAL", "NEGOTIABLE", "UNKNOWN")

#: apps/api/app/models/exhibitor.py VISIBILITY_LEVELS와 동일한 값 집합.
VISIBILITY_LEVELS: tuple[str, ...] = (
    "PUBLIC",
    "BUYER_ONLY",
    "MATCHED_BUYER_ONLY",
    "MEETING_ACCEPTED",
    "PRIVATE",
)
#: 매칭 단계는 아직 상담이 수락되기 이전이다 - PROJECT_SCOPE.md 절대 규칙("meeting.status ==
#: ACCEPTED 이전에는 연락처를 절대 노출하지 않는다")과 일관되게, MATCHED_BUYER_ONLY 이상은
#: 이 라이브러리가 다루는 "후보 제안" 단계에서는 아직 노출 대상이 아니다.
_VISIBILITY_ALLOWED_PRE_MEETING: frozenset[str] = frozenset({"PUBLIC", "BUYER_ONLY"})

#: 바이어 계정 검증상태. apps/api/app/models 어디에도 바이어 전용 검증상태 enum이 아직 없어
#: (grep 확인됨 - profile.py BuyerNeed는 business_email_verified/company_verified 두 boolean만
#: 가짐) 이 라이브러리가 정의하는 최소 4단계. BACKEND-BUYER-MATCH가 실제 UserProfile/BuyerNeed
#: 필드를 이 값으로 매핑한다(예: company_verified True -> VERIFIED, business_email_verified만
#: True -> PENDING, 둘 다 False -> UNVERIFIED). Blocker Score 낮음(가역적, 매핑 위치만의
#: 문제) - 표준 확정 전 안전한 기본값으로 채택.
BUYER_VERIFICATION_STATUSES: tuple[str, ...] = ("UNVERIFIED", "PENDING", "VERIFIED", "REJECTED")
_BUYER_VERIFICATION_ALLOWED: frozenset[str] = frozenset({"PENDING", "VERIFIED"})
_BUYER_VERIFICATION_TRUST: dict[str, float] = {
    "VERIFIED": 1.0,
    "PENDING": 0.6,
    "UNVERIFIED": 0.2,
    "REJECTED": 0.0,
}

#: apps/api/app/models/exhibitor.py BUYER_PREFERENCE_LEVELS와 동일한 값 집합.
PREFERENCE_LEVELS: tuple[str, ...] = ("REQUIRED", "PREFERRED", "EXCLUDED")

GRADES: tuple[str, ...] = ("HIGH", "MEDIUM", "POSSIBLE", "LOW")

HARD_FILTER_NAMES: tuple[str, ...] = (
    "BUYER_VERIFICATION",
    "EXHIBITOR_APPROVAL",
    "PARTICIPATION_ACTIVE",
    "VISIBILITY_SCOPE",
    "REQUIRED_PRODUCT_TECH",
    "REQUIRED_REGION",
    "MOQ_CEILING",
    "REQUIRED_COOPERATION_TYPE",
    "NEW_TRADE_AVAILABLE",
    "MEETING_AVAILABLE",
)


@dataclass(frozen=True)
class BuyerProfile:
    """매칭 입력이 되는 바이어 쪽 신호. 필수 아닌 필드는 전부 "정보 없음/선호 없음"을
    의미하는 기본값(빈 튜플 또는 None)을 가진다 - 없으면 해당 요구조건 없음으로 취급한다.
    """

    buyer_id: Identifier
    verification_status: str

    # 08 8.3절 "바이어 유형" 단일값(BUYER_TYPE.* 코드). e2b buyer_type 컴포넌트가 쓴다.
    buyer_type_code: str | None = None

    # 필수/선호 제품·기술 코드(PRODUCT_CATEGORY/INGREDIENT/SUPPLY_CAPACITY 등). hard_filter는
    # required_*만 강제하고, preferred_*는 score_b2e의 product_tech 컴포넌트 가점에만 쓰인다.
    required_product_codes: tuple[str, ...] = ()
    preferred_product_codes: tuple[str, ...] = ()
    required_technology_codes: tuple[str, ...] = ()
    preferred_technology_codes: tuple[str, ...] = ()

    business_goal_codes: tuple[str, ...] = ()  # BUSINESS_GOAL.*
    channel_codes: tuple[str, ...] = ()  # CHANNEL.*

    required_region_codes: tuple[str, ...] = ()  # REGION.* - hard_filter가 강제
    preferred_region_codes: tuple[str, ...] = ()  # REGION.* - 가점만

    # 08 문서 "MOQ 상한" - 바이어가 감당 가능한 최대 최소발주수량. None이면 상한 제약 없음.
    moq_ceiling: int | None = None
    monthly_order_min: int | None = None
    monthly_order_max: int | None = None

    required_cooperation_type_codes: tuple[str, ...] = ()  # TRADE_TYPE.* - hard_filter가 강제
    preferred_cooperation_type_codes: tuple[str, ...] = ()  # TRADE_TYPE.* - 가점만

    require_new_trade_available: bool = False
    require_meeting_available: bool = False


@dataclass(frozen=True)
class ExhibitorBuyerPreferenceSignal:
    """exhibition.buyer_preference(ExhibitorBuyerPreference) 여러 행을 차원별로 집계한
    입력. 08 27.4절 REQUIRED/PREFERRED/EXCLUDED 3단계를 차원(buyer_type/channel/region/
    cooperation_type)마다 별도 코드 집합으로 보존한다 - score_e2b는 이 신호가 있을 때만
    계산된다(임무 지시: "exhibitor declared buyer-preferences exist"일 때만).
    """

    required_buyer_type_codes: tuple[str, ...] = ()
    preferred_buyer_type_codes: tuple[str, ...] = ()
    excluded_buyer_type_codes: tuple[str, ...] = ()

    required_channel_codes: tuple[str, ...] = ()
    preferred_channel_codes: tuple[str, ...] = ()
    excluded_channel_codes: tuple[str, ...] = ()

    required_region_codes: tuple[str, ...] = ()
    preferred_region_codes: tuple[str, ...] = ()
    excluded_region_codes: tuple[str, ...] = ()

    # buyer_preference 원본 테이블에는 cooperation_type 차원이 없지만(buyer_type/channel/
    # region 3개뿐), 임무 지시가 score_e2b에 0.15*cooperation_type 항을 명시적으로 요구한다.
    # BACKEND-BUYER-MATCH가 exhibitor의 다른 거래유형 선호 신호(예: trade_condition/capability)
    # 를 이 필드로 매핑해 채운다 - 비어 있으면 이 컴포넌트는 단순히 "정보 없음"으로 빠진다.
    required_cooperation_type_codes: tuple[str, ...] = ()
    preferred_cooperation_type_codes: tuple[str, ...] = ()
    excluded_cooperation_type_codes: tuple[str, ...] = ()

    volume_min: int | None = None
    volume_max: int | None = None


@dataclass(frozen=True)
class ExhibitorCandidate:
    """매칭 입력이 되는 (참가)업체 쪽 신호 한 건."""

    exhibitor_id: Identifier
    approval_status: str  # EXHIBITOR_APPROVAL_STATUSES (== MASTER_APPROVAL_STATUSES)
    participation_status: str  # PARTICIPATION_STATUSES
    visibility_scope: str = "PUBLIC"  # VISIBILITY_LEVELS

    product_codes: tuple[str, ...] = ()  # PRODUCT_CATEGORY/INGREDIENT 등 확정 보유 코드
    technology_codes: tuple[str, ...] = ()  # SUPPLY_CAPACITY.* 확정 보유 코드
    cooperation_type_codes: tuple[str, ...] = ()  # TRADE_TYPE.* 확정 보유 코드
    # product_codes/technology_codes/cooperation_type_codes 세 우주에 걸쳐 "업체가 이미
    # 명시적으로 답변한(있다 또는 없다 모두 포함)" 코드 전체. 이 안에 없는 코드는 "아직 정보
    # 없음(UNKNOWN)"이고, 이 안에는 있지만 위 *_codes에는 없는 코드는 "명시적으로 없다고 확인
    # 됨(NO)"이다. hard_filter가 이 둘을 구분해 "미제출(UNKNOWN)은 정보 필요로 별도 표시,
    # 확정 NO와 함께 통과 실패로 처리"하도록 돕는다(임무 지시의 OEM 예시).
    declared_capability_codes: tuple[str, ...] = ()

    business_goal_codes: tuple[str, ...] = ()  # BUSINESS_GOAL.*
    channel_codes: tuple[str, ...] = ()  # CHANNEL.*
    supply_region_codes: tuple[str, ...] = ()  # REGION.*

    moq: int | None = None  # 최소발주수량. None이면 미확인(UNKNOWN).
    monthly_capacity: int | None = None  # SupplyCapability.monthly_capacity 상당.
    lead_time_days: int | None = None  # SupplyCapability.lead_time_days 상당.

    new_trade_available: str = "UNKNOWN"  # TRADE_AVAILABILITY_STATUSES
    meeting_available: bool | None = None  # None이면 미확인.

    trade_readiness_score: float | None = None  # 0..100, exhibitor_profile.trade_readiness_score
    data_trust_score: float | None = None  # 0..100, 검증완료도 등에서 파생되는 신뢰 신호

    # None이면 "이 업체는 희망 바이어 프로파일을 선언하지 않았다" -> score_e2b는 계산되지
    # 않는다(임무 지시).
    buyer_preference: ExhibitorBuyerPreferenceSignal | None = None


@dataclass(frozen=True)
class HardFilterResult:
    """hard_filter()가 후보 한 건에 대해 반환하는 결과."""

    exhibitor_id: Identifier
    passed: bool
    failed_filters: tuple[str, ...] = ()  # HARD_FILTER_NAMES 중 실패한 항목들
    info_codes: tuple[str, ...] = ()  # reason_codes.INFO_* 중 해당하는 것들
    # required_product_codes/required_technology_codes/required_cooperation_type_codes 중
    # UNKNOWN이라 통과시키지 못한 개별 온톨로지 코드들(NO로 확정된 코드와 구분하기 위함).
    unknown_required_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ComponentScore:
    """score_b2e/score_e2b 내부의 가중치 항목 하나. value가 None이면 "신호 없음"이며
    최종 점수 산정에서 제외되고 남은 항목들의 가중치로 재정규화된다(임무 지시:
    "graceful handling ... rather than zeroing blindly").
    """

    name: str
    weight: float
    value: float | None  # 0.0 ~ 1.0, None = 신호 없음


@dataclass(frozen=True)
class BuyerToExhibitorScore:
    """score_b2e()의 반환값."""

    exhibitor_id: Identifier
    score: float  # 0..100
    components: tuple[ComponentScore, ...]
    reason_codes: tuple[str, ...]
    info_codes: tuple[str, ...]


@dataclass(frozen=True)
class ExhibitorToBuyerScore:
    """score_e2b()의 반환값."""

    exhibitor_id: Identifier
    score: float  # 0..100
    components: tuple[ComponentScore, ...]
    reason_codes: tuple[str, ...]
    info_codes: tuple[str, ...]


@dataclass(frozen=True)
class BuyerMatchResult:
    """pipeline.evaluate_candidates()가 후보 한 건에 대해 반환하는 최종 결과."""

    exhibitor_id: Identifier
    hard_filter: HardFilterResult
    b2e: BuyerToExhibitorScore | None  # hard_filter 실패 시 None(점수화 자체를 하지 않음)
    e2b: ExhibitorToBuyerScore | None  # 업체가 희망 바이어 프로파일을 선언하지 않았으면 None
    final_score: float | None  # mutual_score(harmonic mean) 또는 b2e.score, hard_filter 실패 시 None
    grade: str | None  # GRADES, hard_filter 실패 시 None
    reason_codes: tuple[str, ...] = ()
    info_codes: tuple[str, ...] = ()
    included_in_primary: bool = False  # hard_filter 통과 AND grade != LOW
