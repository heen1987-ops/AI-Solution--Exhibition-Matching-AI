from __future__ import annotations

import json
import unittest
from decimal import Decimal

from meet_ai.ontology.catalog import (
    CANONICAL_EVENTS,
    Catalog,
    CatalogValidationError,
    emit_postgres_seed,
    load_catalog,
    normalize_text,
)


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_catalog()

    def test_published_catalog_is_valid(self) -> None:
        self.catalog.validate()
        self.assertEqual("1.0.0", self.catalog.version)

    def test_required_implementation_codes_exist(self) -> None:
        required = {
            "PROFILE.GENERAL_VISITOR",
            "PROFILE.BUSINESS_BUYER",
            "GOAL.GIFT_SEARCH",
            "ALCOHOL.DISTILLED",
            "TASTE.DRY",
            "TASTE.SMOOTH",
            "ALCOHOL_LEVEL.HIGH",
            "PRICE_BAND.K20_TO_K50",
            "BUYER.BOTTLE_SHOP",
            "CHANNEL.BOTTLE_SHOP",
            "TRADE.REGULAR_SUPPLY",
            "REGION.KR.SEOUL",
            "CAPACITY.REGULAR_SUPPLY",
            "MEETING.DISTRIBUTION",
            "SERVICE.PURCHASE",
            "BOOTH_STATUS.OPEN",
        }
        self.assertFalse(required - self.catalog.by_code.keys())

    def test_numeric_bands_have_explicit_boundaries(self) -> None:
        cases = [
            ("alcohol_percentage", "0", "ALCOHOL_LEVEL.ZERO"),
            ("alcohol_percentage", "0.1", "ALCOHOL_LEVEL.VERY_LOW"),
            ("alcohol_percentage", "5", "ALCOHOL_LEVEL.LOW"),
            ("alcohol_percentage", "20", "ALCOHOL_LEVEL.HIGH"),
            ("alcohol_percentage", "40", "ALCOHOL_LEVEL.VERY_HIGH"),
            ("price_krw", "20000", "PRICE_BAND.UNDER_20K"),
            ("price_krw", "20001", "PRICE_BAND.K20_TO_K50"),
            ("price_krw", "50000", "PRICE_BAND.K20_TO_K50"),
            ("price_krw", "100001", "PRICE_BAND.OVER_100K"),
        ]
        for metric, value, expected in cases:
            with self.subTest(metric=metric, value=value):
                self.assertEqual(
                    expected, self.catalog.derive_band(metric, Decimal(value))
                )

    def test_synonyms_are_normalized_and_contextual(self) -> None:
        self.assertEqual("목 넘김이 좋은", normalize_text("  목 넘김이   좋은  "))
        matches = self.catalog.resolve_synonym("막걸리", context="PRODUCT")
        self.assertEqual(
            ("ALCOHOL.TAKJU",), tuple(item.concept_code for item in matches)
        )
        ambiguous = self.catalog.resolve_synonym("향긋한", context="CONSUMER")
        self.assertGreaterEqual(len(ambiguous), 2)

    def test_ancestor_matching_is_reproducible(self) -> None:
        score = self.catalog.match_strength(
            "ALCOHOL.TRADITIONAL_KOREAN", "ALCOHOL.TAKJU", ancestor_decay=Decimal("0.9")
        )
        self.assertEqual(Decimal("0.81"), score)
        self.assertEqual(
            Decimal(1), self.catalog.match_strength("TASTE.DRY", "TASTE.DRY")
        )

    def test_event_mappings_use_interface_contract(self) -> None:
        mapped = {item["event_type"] for item in self.catalog.event_mappings}
        self.assertTrue(mapped)
        self.assertFalse(mapped - CANONICAL_EVENTS)

    def test_unknown_is_not_a_requirement_level(self) -> None:
        self.assertNotIn("UNKNOWN", self.catalog.metadata["requirement_levels"])
        self.assertIn("UNKNOWN", self.catalog.metadata["knowledge_states"])

    def test_invalid_parent_is_rejected(self) -> None:
        payload = json.loads(json.dumps(self.catalog.payload))
        payload["concepts"][0]["parent"] = "MISSING.PARENT"
        with self.assertRaises(CatalogValidationError):
            Catalog(payload).validate()

    def test_seed_sql_uses_deterministic_identifiers_and_publishes_last(self) -> None:
        first = emit_postgres_seed(self.catalog)
        second = emit_postgres_seed(self.catalog)
        self.assertEqual(first, second)
        self.assertIn("INSERT INTO ontology.concept_revision", first)
        self.assertLess(
            first.index("INSERT INTO ontology.concept_revision"),
            first.index("SET status = 'PUBLISHED'"),
        )


if __name__ == "__main__":
    unittest.main()
