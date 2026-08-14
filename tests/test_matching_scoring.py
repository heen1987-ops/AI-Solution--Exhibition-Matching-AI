from __future__ import annotations

import unittest
from decimal import Decimal

from meet_ai.scoring import (
    BUYER_SCORE_V1,
    CONSUMER_SCORE_V1,
    EXHIBITOR_SCORE_V1,
    EligibilityDecision,
    IneligibleCandidateError,
    ScoreCap,
    ScoreValidationError,
    ScoringPolicy,
    calculate_directional_score,
    calculate_reciprocal_score,
)


class DirectionalScoringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.eligible = EligibilityDecision(True, "filter-evaluation-001")

    def test_published_default_weights_total_one(self) -> None:
        for policy in (CONSUMER_SCORE_V1, BUYER_SCORE_V1, EXHIBITOR_SCORE_V1):
            with self.subTest(policy=policy.version):
                self.assertEqual(Decimal(1), sum(policy.weights.values()))

    def test_consumer_design_example_uses_the_weighted_sum(self) -> None:
        result = calculate_directional_score(
            CONSUMER_SCORE_V1,
            {
                "goal": "1.00",
                "category": "1.00",
                "sensory": "0.90",
                "price": "1.00",
                "alcohol": "1.00",
                "service": "1.00",
                "usage": "1.00",
                "behavior": "0.50",
                "trust": "0.95",
            },
            eligibility=self.eligible,
            confidence="0.88",
        )

        # The source design prints 95.75, but its published weights and component
        # values add up to 95.95. The executable policy is the canonical contract.
        self.assertEqual(Decimal("95.95"), result.final_score)
        self.assertEqual("R5", result.grade)
        self.assertEqual(Decimal("0.88"), result.confidence)

    def test_missing_components_are_removed_and_weights_renormalized(self) -> None:
        result = calculate_directional_score(
            CONSUMER_SCORE_V1,
            {
                "goal": "1",
                "category": "0.5",
                "sensory": None,
                "alcohol": None,
                "price": "0.5",
                "service": "0.5",
                "usage": "0.5",
                "behavior": "0.5",
                "trust": "0.5",
            },
            eligibility=self.eligible,
        )

        self.assertEqual(
            Decimal("0.20") / Decimal("0.74"), result.effective_weights["goal"]
        )
        self.assertEqual(("alcohol", "sensory"), result.missing_components)

    def test_explicit_zero_is_scored_as_mismatch_not_missing(self) -> None:
        result = calculate_directional_score(
            ScoringPolicy("test-v1", "TEST", {"known": "0.5", "mismatch": "0.5"}),
            {"known": "1", "mismatch": "0"},
            eligibility=self.eligible,
        )

        self.assertEqual(Decimal("50.0"), result.final_score)
        self.assertEqual((), result.missing_components)

    def test_hard_filter_failure_cannot_be_recovered_by_score(self) -> None:
        failed = EligibilityDecision(False, "filter-evaluation-002", ("MOQ_MISMATCH",))

        with self.assertRaises(IneligibleCandidateError):
            calculate_directional_score(
                BUYER_SCORE_V1,
                {name: "1" for name in BUYER_SCORE_V1.weights},
                eligibility=failed,
            )

    def test_most_restrictive_cap_is_applied_and_recorded(self) -> None:
        result = calculate_directional_score(
            CONSUMER_SCORE_V1,
            {name: "1" for name in CONSUMER_SCORE_V1.weights},
            eligibility=self.eligible,
            caps=(
                ScoreCap("LOW_CANDIDATE_TRUST", "70"),
                ScoreCap("ONE_INDEPENDENT_REASON", "65"),
            ),
        )

        self.assertEqual(Decimal(100), result.uncapped_score)
        self.assertEqual(Decimal(65), result.final_score)
        self.assertEqual(("ONE_INDEPENDENT_REASON",), result.applied_cap_codes)
        self.assertEqual("R3", result.grade)

    def test_buyer_design_example_scores_96_70(self) -> None:
        result = calculate_directional_score(
            BUYER_SCORE_V1,
            {
                "business_goal": "1",
                "product": "1",
                "channel": "1",
                "price": "1",
                "moq": "1",
                "capacity": "1",
                "region": "1",
                "cooperation": "0.70",
                "meeting": "0.90",
                "trust": "0.95",
            },
            eligibility=self.eligible,
        )

        self.assertEqual(Decimal("96.7000"), result.final_score)
        self.assertEqual("B5", result.grade)

    def test_fingerprint_is_stable_and_changes_with_policy_version(self) -> None:
        components = {name: "0.75" for name in CONSUMER_SCORE_V1.weights}
        first = calculate_directional_score(
            CONSUMER_SCORE_V1, components, eligibility=self.eligible
        )
        second = calculate_directional_score(
            CONSUMER_SCORE_V1,
            dict(reversed(tuple(components.items()))),
            eligibility=self.eligible,
        )
        changed_policy = ScoringPolicy(
            "consumer-score-v1.1",
            CONSUMER_SCORE_V1.audience,
            dict(CONSUMER_SCORE_V1.weights),
            grade_prefix="R",
        )
        changed = calculate_directional_score(
            changed_policy, components, eligibility=self.eligible
        )

        self.assertEqual(first.calculation_fingerprint, second.calculation_fingerprint)
        self.assertNotEqual(
            first.calculation_fingerprint, changed.calculation_fingerprint
        )

    def test_unknown_component_is_rejected(self) -> None:
        with self.assertRaises(ScoreValidationError):
            calculate_directional_score(
                CONSUMER_SCORE_V1,
                {"goal": "1", "unpublished_signal": "1"},
                eligibility=self.eligible,
            )


class ReciprocalScoringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.eligible = EligibilityDecision(True, "filter-evaluation-003")

    def test_balanced_design_example_scores_86_88(self) -> None:
        result = calculate_reciprocal_score(
            buyer_to_exhibitor_score="92",
            exhibitor_to_buyer_score="88",
            buyer_confidence="0.90",
            exhibitor_confidence="0.90",
            acceptance_capacity_score="0.90",
            eligibility=self.eligible,
        )

        self.assertEqual(
            Decimal("89.96"), result.reciprocal_base_score.quantize(Decimal("0.01"))
        )
        self.assertEqual(
            Decimal("86.88"), result.final_reciprocal_score.quantize(Decimal("0.01"))
        )
        self.assertEqual("R5", result.grade)
        self.assertEqual("MUTUAL_MATCH", result.match_status)
        self.assertEqual("REQUEST_MEETING", result.recommended_action)

    def test_low_direction_uses_harmonic_mean_and_gate(self) -> None:
        result = calculate_reciprocal_score(
            buyer_to_exhibitor_score="95",
            exhibitor_to_buyer_score="25",
            buyer_confidence="1",
            exhibitor_confidence="1",
            acceptance_capacity_score="1",
            eligibility=self.eligible,
        )

        self.assertEqual(
            Decimal("39.58"), result.reciprocal_base_score.quantize(Decimal("0.01"))
        )
        self.assertEqual(Decimal(45), result.minimum_direction_cap)
        self.assertLessEqual(result.final_reciprocal_score, Decimal(45))
        self.assertEqual("NOT_RECIPROCAL", result.match_status)
        self.assertEqual("DO_NOT_PUSH", result.recommended_action)

    def test_zero_direction_is_safe_and_not_reciprocal(self) -> None:
        result = calculate_reciprocal_score(
            buyer_to_exhibitor_score="90",
            exhibitor_to_buyer_score="0",
            buyer_confidence="1",
            exhibitor_confidence="0",
            acceptance_capacity_score="1",
            eligibility=self.eligible,
        )

        self.assertEqual(Decimal(0), result.reciprocal_base_score)
        self.assertEqual(Decimal(0), result.confidence_score)
        self.assertEqual(Decimal(0), result.final_reciprocal_score)

    def test_reciprocal_fingerprint_is_reproducible(self) -> None:
        kwargs = {
            "buyer_to_exhibitor_score": "78",
            "exhibitor_to_buyer_score": "85",
            "buyer_confidence": "0.8",
            "exhibitor_confidence": "0.9",
            "acceptance_capacity_score": "0.7",
            "eligibility": self.eligible,
        }

        first = calculate_reciprocal_score(**kwargs)
        second = calculate_reciprocal_score(**kwargs)
        self.assertEqual(first.calculation_fingerprint, second.calculation_fingerprint)

    def test_external_cap_is_applied_and_fingerprinted(self) -> None:
        result = calculate_reciprocal_score(
            buyer_to_exhibitor_score="95",
            exhibitor_to_buyer_score="95",
            buyer_confidence="1",
            exhibitor_confidence="1",
            acceptance_capacity_score="1",
            eligibility=self.eligible,
            caps=(ScoreCap("EXHIBITOR_PREFERENCE_UNCONFIRMED", 80),),
        )

        self.assertEqual(Decimal(80), result.final_reciprocal_score)
        self.assertIsNone(result.minimum_direction_cap)
        self.assertEqual(
            ("EXHIBITOR_PREFERENCE_UNCONFIRMED",),
            result.applied_cap_codes,
        )
        self.assertEqual(64, len(result.calculation_fingerprint))

    def test_reciprocal_hard_filter_failure_is_not_scored(self) -> None:
        failed = EligibilityDecision(
            False, "filter-evaluation-004", ("EXCLUSIVE_CONTRACT_CONFLICT",)
        )

        with self.assertRaises(IneligibleCandidateError):
            calculate_reciprocal_score(
                buyer_to_exhibitor_score="100",
                exhibitor_to_buyer_score="100",
                buyer_confidence="1",
                exhibitor_confidence="1",
                acceptance_capacity_score="1",
                eligibility=failed,
            )


if __name__ == "__main__":
    unittest.main()
