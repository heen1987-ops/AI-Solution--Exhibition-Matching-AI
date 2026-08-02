"""Deterministic shadow-only reciprocal-rank fusion.

This module deliberately does not participate in ``execute_matching``.  It
compares a candidate fusion policy with the published weighted-v1 order while
keeping that public order immutable.  Missing and unknown business signals are
diagnostic states, never numeric zeroes.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Any

HYBRID_RRF_SHADOW_COMMAND_V1 = "hybrid-rrf-shadow-command-v1.0"
HYBRID_RRF_SHADOW_RESULT_V1 = "hybrid-rrf-shadow-result-v1.0"
HYBRID_RRF_SHADOW_VERSION = "hybrid-rrf-shadow-v1.0"
RRF_RANK_CONSTANT = 60


class HybridShadowValidationError(ValueError):
    """Raised when a shadow command cannot be reproduced unambiguously."""


class RecallChannel(str, Enum):
    STRUCTURED = "STRUCTURED"
    KEYWORD = "KEYWORD"
    VECTOR = "VECTOR"


class RecallChannelState(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_INVOKED = "NOT_INVOKED"


def _fingerprint(payload: object) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _normalized_texts(values: tuple[str, ...], *, field: str) -> tuple[str, ...]:
    normalized = tuple(sorted(value.strip() for value in values))
    if any(not value for value in normalized):
        raise HybridShadowValidationError(f"{field} must contain non-empty strings")
    if len(normalized) != len(set(normalized)):
        raise HybridShadowValidationError(f"{field} must not contain duplicates")
    return normalized


@dataclass(frozen=True, slots=True)
class RecallChannelRanking:
    channel: RecallChannel | str
    state: RecallChannelState | str
    ranked_candidate_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        try:
            channel = RecallChannel(self.channel)
            state = RecallChannelState(self.state)
        except ValueError as exc:
            raise HybridShadowValidationError(str(exc)) from exc
        candidate_ids = tuple(item.strip() for item in self.ranked_candidate_ids)
        if any(not item for item in candidate_ids):
            raise HybridShadowValidationError(
                "ranked_candidate_ids must contain non-empty strings"
            )
        if len(candidate_ids) != len(set(candidate_ids)):
            raise HybridShadowValidationError(
                f"{channel.value} ranked_candidate_ids must not contain duplicates"
            )
        if state is not RecallChannelState.AVAILABLE and candidate_ids:
            raise HybridShadowValidationError(
                f"{channel.value} {state.value} cannot contain a ranking"
            )
        object.__setattr__(self, "channel", channel)
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "ranked_candidate_ids", candidate_ids)


@dataclass(frozen=True, slots=True)
class CandidateSignalDiagnostics:
    candidate_id: str
    unknown_signals: tuple[str, ...] = ()
    missing_signals: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        candidate_id = self.candidate_id.strip()
        if not candidate_id:
            raise HybridShadowValidationError("candidate_id must be non-empty")
        unknown = _normalized_texts(self.unknown_signals, field="unknown_signals")
        missing = _normalized_texts(self.missing_signals, field="missing_signals")
        overlap = sorted(set(unknown) & set(missing))
        if overlap:
            raise HybridShadowValidationError(
                f"signals cannot be both UNKNOWN and MISSING: {overlap}"
            )
        object.__setattr__(self, "candidate_id", candidate_id)
        object.__setattr__(self, "unknown_signals", unknown)
        object.__setattr__(self, "missing_signals", missing)


@dataclass(frozen=True, slots=True)
class HybridRrfShadowCommand:
    candidate_ids: tuple[str, ...]
    published_ranking: tuple[str, ...]
    channels: tuple[RecallChannelRanking, ...]
    candidate_signals: tuple[CandidateSignalDiagnostics, ...] = ()
    contract_version: str = HYBRID_RRF_SHADOW_COMMAND_V1

    def __post_init__(self) -> None:
        if self.contract_version != HYBRID_RRF_SHADOW_COMMAND_V1:
            raise HybridShadowValidationError(
                f"unsupported command contract: {self.contract_version}"
            )
        candidate_ids = _normalized_texts(self.candidate_ids, field="candidate_ids")
        if not candidate_ids:
            raise HybridShadowValidationError("candidate_ids must be non-empty")
        published = tuple(item.strip() for item in self.published_ranking)
        if len(published) != len(set(published)) or set(published) != set(candidate_ids):
            raise HybridShadowValidationError(
                "published_ranking must contain every candidate exactly once"
            )

        channels_by_name = {item.channel: item for item in self.channels}
        if len(channels_by_name) != len(self.channels):
            raise HybridShadowValidationError("channels must not contain duplicates")
        if set(channels_by_name) != set(RecallChannel):
            raise HybridShadowValidationError(
                "channels must contain STRUCTURED, KEYWORD, and VECTOR"
            )
        for channel in (RecallChannel.STRUCTURED, RecallChannel.KEYWORD):
            if channels_by_name[channel].state is not RecallChannelState.AVAILABLE:
                raise HybridShadowValidationError(
                    f"{channel.value} must be AVAILABLE for weighted-v1 comparison"
                )
        unknown_candidates = sorted(
            {
                candidate_id
                for channel in self.channels
                for candidate_id in channel.ranked_candidate_ids
            }
            - set(candidate_ids)
        )
        if unknown_candidates:
            raise HybridShadowValidationError(
                f"channel rankings contain unknown candidates: {unknown_candidates}"
            )

        diagnostics_by_id = {item.candidate_id: item for item in self.candidate_signals}
        if len(diagnostics_by_id) != len(self.candidate_signals):
            raise HybridShadowValidationError(
                "candidate_signals must not contain duplicate candidate_id"
            )
        unknown_diagnostics = sorted(set(diagnostics_by_id) - set(candidate_ids))
        if unknown_diagnostics:
            raise HybridShadowValidationError(
                f"candidate_signals contain unknown candidates: {unknown_diagnostics}"
            )

        fallback_recalled = set(
            channels_by_name[RecallChannel.STRUCTURED].ranked_candidate_ids
        ) | set(channels_by_name[RecallChannel.KEYWORD].ranked_candidate_ids)
        if fallback_recalled != set(candidate_ids):
            raise HybridShadowValidationError(
                "STRUCTURED/KEYWORD union must preserve every published candidate"
            )

        object.__setattr__(self, "candidate_ids", candidate_ids)
        object.__setattr__(self, "published_ranking", published)
        object.__setattr__(
            self,
            "channels",
            tuple(sorted(self.channels, key=lambda item: item.channel.value)),
        )
        object.__setattr__(
            self,
            "candidate_signals",
            tuple(sorted(self.candidate_signals, key=lambda item: item.candidate_id)),
        )


@dataclass(frozen=True, slots=True)
class HybridShadowCandidate:
    candidate_id: str
    rank: int
    rrf_score: Decimal | None
    channel_ranks: Mapping[str, int | None]
    unknown_signals: tuple[str, ...]
    missing_signals: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HybridRrfShadowResult:
    contract_version: str
    shadow_version: str
    shadow_only: bool
    promotion_allowed: bool
    published_ranking: tuple[str, ...]
    shadow_ranking: tuple[HybridShadowCandidate, ...]
    fallback_applied: bool
    fallback_reason: str | None
    unknown_signal_count: int
    missing_signal_count: int
    input_fingerprint: str
    result_fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "shadow_version": self.shadow_version,
            "shadow_only": self.shadow_only,
            "promotion_allowed": self.promotion_allowed,
            "published_ranking": list(self.published_ranking),
            "shadow_ranking": [
                {
                    "candidate_id": item.candidate_id,
                    "rank": item.rank,
                    "rrf_score": (
                        None if item.rrf_score is None else str(item.rrf_score)
                    ),
                    "channel_ranks": dict(item.channel_ranks),
                    "unknown_signals": list(item.unknown_signals),
                    "missing_signals": list(item.missing_signals),
                }
                for item in self.shadow_ranking
            ],
            "fallback_applied": self.fallback_applied,
            "fallback_reason": self.fallback_reason,
            "unknown_signal_count": self.unknown_signal_count,
            "missing_signal_count": self.missing_signal_count,
            "input_fingerprint": self.input_fingerprint,
            "result_fingerprint": self.result_fingerprint,
        }


def _command_payload(command: HybridRrfShadowCommand) -> dict[str, Any]:
    return {
        "contract_version": command.contract_version,
        "candidate_ids": list(command.candidate_ids),
        "published_ranking": list(command.published_ranking),
        "channels": [
            {
                "channel": item.channel.value,
                "state": item.state.value,
                "ranked_candidate_ids": list(item.ranked_candidate_ids),
            }
            for item in command.channels
        ],
        "candidate_signals": [asdict(item) for item in command.candidate_signals],
    }


def execute_hybrid_rrf_shadow(
    command: HybridRrfShadowCommand,
) -> HybridRrfShadowResult:
    """Evaluate RRF without mutating or replacing the published ranking."""

    channels = {item.channel: item for item in command.channels}
    vector = channels[RecallChannel.VECTOR]
    fallback_applied = vector.state is not RecallChannelState.AVAILABLE
    fallback_reason = vector.state.value if fallback_applied else None
    diagnostics = {item.candidate_id: item for item in command.candidate_signals}
    channel_ranks = {
        channel.value: {
            candidate_id: rank
            for rank, candidate_id in enumerate(item.ranked_candidate_ids, start=1)
        }
        for channel, item in channels.items()
    }

    scores: dict[str, Decimal | None]
    if fallback_applied:
        ordered_ids = command.published_ranking
        scores = {candidate_id: None for candidate_id in command.candidate_ids}
    else:
        scores = {}
        for candidate_id in command.candidate_ids:
            score = sum(
                (
                    Decimal(1) / Decimal(RRF_RANK_CONSTANT + rank)
                    if (rank := channel_ranks[channel.value].get(candidate_id))
                    is not None
                    else Decimal(0)
                )
                for channel in RecallChannel
                if channels[channel].state is RecallChannelState.AVAILABLE
            )
            scores[candidate_id] = score.quantize(Decimal("0.000000000001"))
        ordered_ids = tuple(
            sorted(command.candidate_ids, key=lambda item: (-scores[item], item))
        )

    ranked = tuple(
        HybridShadowCandidate(
            candidate_id=candidate_id,
            rank=rank,
            rrf_score=scores[candidate_id],
            channel_ranks=MappingProxyType(
                {
                    channel.value: channel_ranks[channel.value].get(candidate_id)
                    for channel in RecallChannel
                }
            ),
            unknown_signals=diagnostics.get(
                candidate_id, CandidateSignalDiagnostics(candidate_id)
            ).unknown_signals,
            missing_signals=diagnostics.get(
                candidate_id, CandidateSignalDiagnostics(candidate_id)
            ).missing_signals,
        )
        for rank, candidate_id in enumerate(ordered_ids, start=1)
    )
    input_fingerprint = _fingerprint(_command_payload(command))
    result_payload = {
        "contract_version": HYBRID_RRF_SHADOW_RESULT_V1,
        "shadow_version": HYBRID_RRF_SHADOW_VERSION,
        "shadow_only": True,
        "promotion_allowed": False,
        "published_ranking": list(command.published_ranking),
        "shadow_ranking": [
            {
                "candidate_id": item.candidate_id,
                "rank": item.rank,
                "rrf_score": None if item.rrf_score is None else str(item.rrf_score),
                "channel_ranks": dict(item.channel_ranks),
                "unknown_signals": list(item.unknown_signals),
                "missing_signals": list(item.missing_signals),
            }
            for item in ranked
        ],
        "fallback_applied": fallback_applied,
        "fallback_reason": fallback_reason,
        "input_fingerprint": input_fingerprint,
    }
    return HybridRrfShadowResult(
        contract_version=HYBRID_RRF_SHADOW_RESULT_V1,
        shadow_version=HYBRID_RRF_SHADOW_VERSION,
        shadow_only=True,
        promotion_allowed=False,
        published_ranking=command.published_ranking,
        shadow_ranking=ranked,
        fallback_applied=fallback_applied,
        fallback_reason=fallback_reason,
        unknown_signal_count=sum(len(item.unknown_signals) for item in ranked),
        missing_signal_count=sum(len(item.missing_signals) for item in ranked),
        input_fingerprint=input_fingerprint,
        result_fingerprint=_fingerprint(result_payload),
    )
