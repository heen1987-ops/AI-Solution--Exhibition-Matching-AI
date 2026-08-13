"""Compatibility adapter for the common catalog-search engine mode."""

from __future__ import annotations

from meet_ai.engine import CatalogSearchSignals as KioskSearchSignals

from app.services.matching.engine_adapter import execute_catalog_search_score


def score_kiosk_search(signals: KioskSearchSignals) -> float:
    """Return the frozen five-signal score through the shared engine facade."""

    return float(execute_catalog_search_score(signals).normalized_score)
