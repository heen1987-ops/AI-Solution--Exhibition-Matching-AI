"""Request Validator: 추천 요청 자체의 형식·정합성을 점수 계산 전에 확정한다.

근거 문서: docs/05-ai-matching-engine-architecture.md 5.1절 Request Validator.

구현 범위
----------
5.1절 검증 항목 중 "프로파일 존재·완성도"는 profile_resolver가 이미 처리한 뒤(프로파일이
없거나 버전이 없으면 예외로 실패)이므로 여기서는 그 결과와 요청 자체의 정합성만 본다.
연령확인·개인화 동의 여부는 profile.user_consent 조회가 필요한데 이 커밋에는 아직
연결하지 않았다(TODO). 지금 구현된 항목은 사용자 유형과 추천 유형의 정합성, limit 값
범위뿐이다.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.profile import UserProfile

#: 05단계 5.1절 policy_route 계약: 사용자 유형별로 서로 다른 정책 경로를 태운다.
_ALLOWED_RECOMMENDATION_TYPES: dict[str, frozenset[str]] = {
    "GENERAL_VISITOR": frozenset({"BOOTH", "PRODUCT", "PROGRAM", "MIXED"}),
    "BUYER": frozenset({"EXHIBITOR", "PRODUCT", "MIXED"}),
}


class InvalidRecommendationRequestError(Exception):
    def __init__(self, missing_fields: tuple[str, ...]) -> None:
        super().__init__(f"invalid recommendation request: {missing_fields}")
        self.missing_fields = missing_fields


@dataclass(frozen=True)
class ValidatedRequest:
    profile: UserProfile
    recommendation_type: str
    limit: int
    policy_route: str


def validate_request(
    *,
    profile: UserProfile,
    recommendation_type: str,
    limit: int,
) -> ValidatedRequest:
    missing: list[str] = []

    allowed_types = _ALLOWED_RECOMMENDATION_TYPES.get(profile.user_type, frozenset())
    if recommendation_type not in allowed_types:
        missing.append("recommendation_type")
    if limit < 1 or limit > 200:
        missing.append("limit")

    if missing:
        raise InvalidRecommendationRequestError(tuple(missing))

    policy_route = f"{profile.user_type.lower()}_matching_v1"
    return ValidatedRequest(
        profile=profile,
        recommendation_type=recommendation_type,
        limit=limit,
        policy_route=policy_route,
    )
