"""AI-EXTRACTION 트랙(WAVE 2D) - 마스킹된 문서 세그먼트로부터 근거기반(grounded) 속성 후보
JSON을 산출하는 모듈. 공개 진입점은 ``GroundedExtractor``다.
"""

from __future__ import annotations

from ai.extraction.extractor import ExtractionRun, GroundedExtractor
from ai.extraction.provider import (
    ExtractionBackend,
    FakeExtractionBackend,
    UnconfiguredExtractionBackend,
)
from ai.extraction.types import (
    Attribute,
    Conflict,
    ConflictEvidence,
    Entity,
    ExtractionResult,
    MissingCriticalField,
    TextSegment,
    ValidationIssue,
    adapt_worker_segments,
)

__all__ = [
    "Attribute",
    "Conflict",
    "ConflictEvidence",
    "Entity",
    "ExtractionBackend",
    "ExtractionResult",
    "ExtractionRun",
    "FakeExtractionBackend",
    "GroundedExtractor",
    "MissingCriticalField",
    "TextSegment",
    "UnconfiguredExtractionBackend",
    "ValidationIssue",
    "adapt_worker_segments",
]
