"""⑪ Explanation Generator - docs/05-ai-matching-engine-architecture.md 5.11절.

최종 추천 결과에 대해 사용자가 이해할 수 있는 추천 이유를 생성한다. 05번 문서 10.1절
"AI 설명 생성 실패" 절은 "미리 정의된 추천 이유 템플릿 사용"을 정상적인 대체 경로로 이미
전제하므로, 이번 MVP는 처음부터 템플릿 방식만 구현한다(LLM 자연어 생성은 이 작업 범위
밖이며, 아래 ``_GENERAL_TEMPLATES``/``_BUYER_TEMPLATES``만 교체·확장하면 된다).

생성 방식(5.11절 그대로):
    1. 점수 기여도가 높은 특성 추출 - ``candidate.features`` 값 상위 순.
    2. 노출 가능한 근거인지 정책 검증 - 템플릿 자체가 허용된 근거 코드 집합이므로 이 목록에
       없는 신호(성별·연령·내부 점수·스폰서 여부 등)는 애초에 후보가 될 수 없다.
    3. 템플릿으로 문장 생성.
    4. 입력 사실과 문장 일치 검증 - 템플릿 문자열 자체가 특성값에서 기계적으로 도출되므로
       항상 일치한다(자유 생성 문장이 아니기 때문에 별도 검증 단계가 필요 없음).
    5. 사용자 화면에 최대 2~3개 표시.

금지 근거(5.11절): 성별·연령 기반 추정, 사용자가 입력하지 않은 소비성향, 업체 미제공
품질·효능 주장, 내부 점수·가중치, 다른 사용자의 개인 데이터, 광고비·스폰서 여부. 이 템플릿
집합은 위 항목을 애초에 다루지 않는다.
"""

from __future__ import annotations

from app.services.matching.types import (
    MatchCandidate,
    MatchReasonDraft,
    ResolvedProfile,
)

#: feature 키 -> (reason_code, 문장 템플릿). 값이 0.5 이상일 때만 근거로 채택한다.
_GENERAL_TEMPLATES: dict[str, tuple[str, str]] = {
    "taste_match": ("TASTE_MATCH", "선호하신 맛 특성과 잘 맞습니다."),
    "aroma_match": ("AROMA_MATCH", "선호하신 향과 잘 맞습니다."),
    "category_match": ("CATEGORY_MATCH", "관심 있으신 주종과 일치합니다."),
    "alcohol_match": ("ALCOHOL_MATCH", "선호하신 도수대와 맞습니다."),
    "price_match": ("PRICE_MATCH", "희망 가격대에서 만나볼 수 있습니다."),
    "availability_score": ("AVAILABILITY", "지금 시음하거나 구매할 수 있습니다."),
    "usage_match": ("GOAL_MATCH", "찾고 계신 목적과 잘 맞는 제품입니다."),
}

_BUYER_TEMPLATES: dict[str, tuple[str, str]] = {
    "category_match": ("CATEGORY_MATCH", "찾고 계신 제품군과 일치합니다."),
    "channel_match": ("CHANNEL_MATCH", "희망하신 유통채널과 일치합니다."),
    "region_match": ("REGION_MATCH", "희망하신 공급지역과 일치합니다."),
    "moq_match": ("MOQ_MATCH", "희망하신 주문 조건에 맞는 최소주문수량입니다."),
    "capacity_match": ("CAPACITY_MATCH", "필요하신 물량을 공급할 수 있는 역량입니다."),
    "oem_availability": ("OEM_AVAILABLE", "OEM 거래가 가능합니다."),
    "private_label_availability": (
        "PRIVATE_LABEL_AVAILABLE",
        "PB·자체브랜드 거래가 가능합니다.",
    ),
    "export_availability": ("EXPORT_AVAILABLE", "수출 거래가 가능합니다."),
    "preferred_buyer_match": (
        "PREFERRED_BUYER_MATCH",
        "업체가 희망하는 바이어 유형과 일치합니다.",
    ),
}

_FEATURE_MIN_THRESHOLD = 0.5
_MAX_REASONS = 3


def _reason(
    code: str, text: str, evidence_refs: list[str], *, contribution: float | None
) -> MatchReasonDraft:
    return MatchReasonDraft(
        code=code,
        text=text,
        evidence_refs=evidence_refs,
        contribution_score=contribution,
        generated_by="TEMPLATE",
    )


def _context_reasons(candidate: MatchCandidate) -> list[MatchReasonDraft]:
    reasons: list[MatchReasonDraft] = []
    if candidate.availability.get("meeting"):
        reasons.append(
            _reason(
                "MEETING_AVAILABLE",
                "현재 상담 가능한 시간이 있습니다.",
                [f"availability_slot:participation:{candidate.participation_id}"],
                contribution=candidate.score_components.get("context_score"),
            )
        )
    if (
        candidate.estimated_walk_minutes is not None
        and candidate.estimated_walk_minutes <= 10
    ):
        reasons.append(
            _reason(
                "NEARBY",
                f"현재 위치에서 도보 {candidate.estimated_walk_minutes}분 거리입니다.",
                [f"booth:{candidate.object_id}:location"],
                contribution=candidate.score_components.get("context_score"),
            )
        )
    return reasons


def generate_explanations(
    candidates: list[MatchCandidate], *, profile: ResolvedProfile
) -> None:
    templates = _BUYER_TEMPLATES if profile.user_type == "BUYER" else _GENERAL_TEMPLATES

    for candidate in candidates:
        reasons = _context_reasons(candidate)

        ranked = sorted(
            (
                (key, value)
                for key, value in candidate.features.items()
                if key in templates
                and value is not None
                and value >= _FEATURE_MIN_THRESHOLD
            ),
            key=lambda item: item[1],
            reverse=True,
        )
        for key, value in ranked:
            if len(reasons) >= _MAX_REASONS:
                break
            code, text = templates[key]
            reasons.append(
                _reason(
                    code,
                    text,
                    [f"{candidate.object_type.lower()}:{candidate.object_id}:{key}"],
                    contribution=value,
                )
            )

        if not reasons:
            reasons.append(
                _reason(
                    "GENERAL_MATCH",
                    "현재 조건에 맞춰 추천드리는 항목입니다.",
                    [f"{candidate.object_type.lower()}:{candidate.object_id}"],
                    contribution=None,
                )
            )

        reasons = reasons[:_MAX_REASONS]
        for index, reason in enumerate(reasons):
            reason.display_order = index
        candidate.reasons = reasons
