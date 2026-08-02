"""Deterministic Kiosk Search Score from the frozen Wave-2 contract."""

from __future__ import annotations

import math
from dataclasses import dataclass


def clamp_unit(value: float) -> float:
    if not math.isfinite(value):
        return 0.0
    return min(max(value, 0.0), 1.0)


@dataclass(frozen=True, slots=True)
class KioskSearchSignals:
    semantic: float
    keyword: float
    category: float
    data_quality: float
    booth_availability: float


def score_kiosk_search(signals: KioskSearchSignals) -> float:
    """Return the frozen five-signal score without fallback renormalization."""

    return (
        0.45 * clamp_unit(signals.semantic)
        + 0.30 * clamp_unit(signals.keyword)
        + 0.15 * clamp_unit(signals.category)
        + 0.05 * clamp_unit(signals.data_quality)
        + 0.05 * clamp_unit(signals.booth_availability)
    )
