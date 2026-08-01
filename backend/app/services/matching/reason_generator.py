"""18단계 추천 이유 생성 (템플릿 기반).

근거 문서: docs/05-ai-matching-engine-architecture.md 5.11절 Explanation Generator.
그 절이 정의하는 5단계 프로세스(①점수 기여도가 높은 특성 추출 ②노출 가능한 근거인지
정책 검증 ③템플릿 또는 LLM으로 문장 생성 ④입력 사실과 문장 일치 검증 ⑤사용자 화면에
최대 2~3개 표시) 중 이 모듈은 ①③⑤를 코드로, ②④는 "정적으로 검수된 템플릿만 쓴다"는
설계로 만족시킨다: `_REASON_TEMPLATES`에 없는 구성요소는 절대 노출하지 않으므로 지어낸
문장이 나올 수 없고, 템플릿 문구 자체가 내부 점수·가중치·구성요소 코드명을 언급하지
않도록 미리 작성해 "금지 근거"(5.11절: 내부 점수/가중치 노출 금지 등) 위반을 원천
차단한다.

orchestrator.py의 이전 구현(`_template_reason_text`)은
`f"'{top_component}' 조건이 높은 비중으로 일치합니다."`처럼 내부 구성요소 이름
("sensory" 등)을 문장에 그대로 노출해 이 금지 근거를 위반하고 있었다 - 이 모듈이 그
자리를 대체한다.

구현 범위와 남은 작업
----------------------
- CONSUMER_SCORE_V1 방향(DirectionalScoreResult.contributions가 있는 경로)만 다룬다.
  ReciprocalScoreResult(BUYER/EXHIBITOR 양면 적합도)는 contributions 필드 자체가 없어
  (src/meet_ai/scoring/engine.py) 같은 방식으로 재사용할 수 없다 - orchestrator.py의
  `_template_reciprocal_reason_text`(match_status 기반, 내부 점수 비노출)는 그대로 둔다.
- LLM 생성 경로(5.11절 "③ 템플릿 또는 LLM")는 아직 연결하지 않았다 - `generated_by`는
  항상 "TEMPLATE"이다.
- `_REASON_TEMPLATES`에 없는 구성요소(behavior/trust 등, feature_builder.py가 아직
  None만 반환하는 구성요소)는 애초에 `contributions`에 나타나지 않는다(None은 가중치
  분모에서 제외되므로 기여도 자체가 없다) - 그래도 방어적으로 템플릿이 없으면 건너뛴다.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from meet_ai.scoring import DirectionalScoreResult

#: 구성요소 이름 -> 사용자 문구. 05단계 5.11절 "금지 근거"(내부 점수·가중치·구성요소
#: 코드명 노출 금지)를 지키기 위해 문구 자체에 숫자나 내부 이름을 넣지 않는다.
#: CONSUMER_SCORE_V1/BUYER_SCORE_V1 두 정책의 구성요소를 모두 포함한다(price처럼 겹치는
#: 이름은 같은 문구를 쓴다) - 지금은 BUYER 경로에서 이 함수를 쓰지 않지만(모듈 docstring
#: "구현 범위" 참고), 정책이 바뀌어도 재사용할 수 있게 남겨둔다.
_REASON_TEMPLATES: Mapping[str, str] = {
    "goal": "이번 방문 목적과 잘 맞는 후보입니다.",
    "category": "찾으시는 주종과 일치합니다.",
    "sensory": "선호하시는 맛·향과 잘 맞습니다.",
    "price": "설정하신 가격대에 맞습니다.",
    "alcohol": "선호하시는 도수와 맞습니다.",
    "service": "원하시는 시음·구매가 가능합니다.",
    "usage": "선물·자가소비 등 사용 목적과 맞습니다.",
    "business_goal": "사업 목적과 맞는 후보입니다.",
    "product": "찾으시는 제품군과 일치합니다.",
    "channel": "원하시는 유통채널을 지원합니다.",
    "moq": "설정하신 최소주문수량 조건에 맞습니다.",
    "region": "원하시는 공급지역과 일치합니다.",
}

#: 05단계 5.11절 "⑤ 사용자 화면에 최대 2~3개 표시".
_MAX_REASONS = 3

#: 문구가 정의된 구성요소가 하나도 기여하지 않았을 때(예: 가격만 일치했는데 가격에
#: 대응하는 문구가 없는 정책일 경우) 쓰는 대체 문구. 내부 정보를 전혀 언급하지 않는다.
_FALLBACK_REASON_TEXT = "조건에 부합하는 후보입니다."


@dataclass(frozen=True)
class GeneratedReason:
    """matching.match_reason 한 행에 대응한다(db-erd 15.4절)."""

    reason_code: str
    reason_text: str
    contribution_score: Decimal
    display_order: int


def generate_directional_reasons(
    result: DirectionalScoreResult, *, max_reasons: int = _MAX_REASONS
) -> Sequence[GeneratedReason]:
    """기여도(contributions) 상위 구성요소부터 최대 max_reasons개의 문구를 만든다.

    05단계 5.11절 1단계(기여도 추출)를 그대로 따른다: contributions 값 내림차순 정렬.
    문구가 없는 구성요소는 건너뛴다 - 억지로 일반 문구를 붙이면 "사실과 문장 일치
    검증"(4단계)을 통과할 수 없다(그 구성요소가 실제로 왜 기여했는지 설명하는 문장이
    아니게 된다).
    """

    ranked = sorted(
        result.contributions.items(), key=lambda item: item[1], reverse=True
    )
    reasons: list[GeneratedReason] = []
    for component, contribution in ranked:
        template = _REASON_TEMPLATES.get(component)
        if template is None:
            continue
        reasons.append(
            GeneratedReason(
                reason_code=f"{component.upper()}_MATCH",
                reason_text=template,
                contribution_score=contribution,
                display_order=len(reasons),
            )
        )
        if len(reasons) >= max_reasons:
            break

    if not reasons:
        reasons.append(
            GeneratedReason(
                reason_code="GENERAL_MATCH",
                reason_text=_FALLBACK_REASON_TEXT,
                contribution_score=Decimal(0),
                display_order=0,
            )
        )
    return reasons
