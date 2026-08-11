"""LLM 백엔드 추상화. ``ai/query_interpreter.py``의 ``QueryInterpreterBackend`` Protocol과
동일한 관례를 따른다 - 지금 이 저장소에는 실제 LLM 프로바이더 어댑터가 없으므로(그 트랙도
"LLM은 지금 단계에 넣지 않는다"), 여기서도 실제 네트워크 호출을 구현하지 않는다. 대신 이
Protocol 뒤에 나중에 실제 프로바이더(OpenAI/Claude/사내 게이트웨이 등)를 꽂을 수 있게 경계만
만들어 둔다 - 그때도 ``ExtractionBackend.extract(sections) -> str`` 시그니처는 그대로다.

테스트/평가 하네스는 항상 ``FakeExtractionBackend``(결정적, 네트워크 없음)만 쓴다 - 이 트랙의
OWNED PATHS 지시("no live LLM call needed - use a fake/deterministic provider")와 일치한다.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from ai.extraction.prompt_builder import PromptSections


class ExtractionBackend(Protocol):
    def extract(self, sections: PromptSections) -> str:
        """``sections.render()``에 대응하는 모델의 원시 응답(JSON 문자열)을 반환한다."""
        ...


class UnconfiguredExtractionBackend:
    """실제 프로바이더가 아직 연결되지 않았을 때의 기본 백엔드. 조용히 가짜 데이터를
    돌려주는 대신 명시적으로 실패해, 통합 전까지 "동작하는 것처럼 보이지만 아무것도 추출하지
    않는" 상태를 방지한다."""

    def extract(self, sections: PromptSections) -> str:
        raise NotImplementedError(
            "no ExtractionBackend configured - wire a real LLM provider adapter "
            "(see ai/extraction/provider.py:ExtractionBackend) or pass a "
            "FakeExtractionBackend for tests"
        )


@dataclass
class FakeExtractionBackend:
    """테스트/평가 전용 결정적 백엔드.

    ``response`` - 항상 이 고정 문자열을 반환.
    ``responder`` - 주어지면 ``response`` 대신 ``responder(sections)``를 호출해 매 요청마다
    다른 응답을 만들 수 있다(예: 여러 문서를 순서대로 처리하는 시나리오).
    ``calls`` - 프롬프트 구성이 실제로 무엇을 백엔드에 보냈는지 테스트가 검사할 수 있도록
    호출마다 받은 ``PromptSections``를 기록한다.
    """

    response: str = "{}"
    responder: Callable[[PromptSections], str] | None = None
    calls: list[PromptSections] = field(default_factory=list)

    def extract(self, sections: PromptSections) -> str:
        self.calls.append(sections)
        if self.responder is not None:
            return self.responder(sections)
        return self.response
