"""Tests for BACKEND-017: interaction.feedback model + migration.

No live Postgres is reachable in this environment. Following the project's established
convention (test_checkin_model.py, test_favorite_model.py): DDL-level guarantees (CHECK
constraints, FK boundaries, indexes) are proven by compiling the SQLAlchemy table definition to
PostgreSQL DDL text, not against a live database.

Also covers the comment-encryption round trip (app/services/feedback/service.py::
encrypt_comment/decrypt_comment) and the preference-vs-situational-vs-review-queue reason-code
partition (app/models/feedback.py) documented in this task's business rule.
"""

from __future__ import annotations

import base64

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

import app.models  # noqa: F401  # registers every domain module on Base.metadata
from app.core.config import Settings
from app.db.base import Base
from app.models.feedback import (
    FEEDBACK_RATINGS,
    FEEDBACK_REASON_CODES,
    PREFERENCE_REASON_CODES,
    REVIEW_QUEUE_REASON_CODES,
    SITUATIONAL_REASON_CODES,
    Feedback,
)
from app.services.feedback.service import decrypt_comment, encrypt_comment


def _table_ddl() -> str:
    return str(CreateTable(Feedback.__table__).compile(dialect=postgresql.dialect()))


def _index_ddl(index_name: str) -> str:
    (index,) = [idx for idx in Feedback.__table__.indexes if idx.name == index_name]
    return str(CreateIndex(index).compile(dialect=postgresql.dialect()))


def _settings() -> Settings:
    return Settings(
        SECRET_KEY="feedback-unit-test-secret",
        AUTH_TOKEN_PEPPER="feedback-unit-test-pepper",
        AUTH_ENCRYPTION_KEY_B64=base64.urlsafe_b64encode(b"k" * 32).decode(),
    )


SETTINGS = _settings()


# ---------------------------------------------------------------------------
# Registration / table shape.
# ---------------------------------------------------------------------------


def test_feedback_registers_on_base_metadata() -> None:
    assert "interaction.feedback" in Base.metadata.tables
    assert Base.metadata.tables["interaction.feedback"] is Feedback.__table__


def test_feedback_table_is_in_interaction_schema() -> None:
    assert Feedback.__table__.schema == "interaction"
    assert Feedback.__table__.name == "feedback"


def test_feedback_rating_constants_match_interface_spec() -> None:
    assert FEEDBACK_RATINGS == ("VERY_RELEVANT", "RELEVANT", "NOT_RELEVANT")


def test_feedback_rating_check_is_present_and_named_per_convention() -> None:
    ddl = _table_ddl()
    # app/db/base.py NAMING_CONVENTION: "ck": "ck_%(table_name)s_%(constraint_name)s".
    assert (
        "CONSTRAINT ck_feedback_feedback_rating_allowed "
        "CHECK (rating IN ('VERY_RELEVANT', 'RELEVANT', 'NOT_RELEVANT'))" in ddl
    )


def test_feedback_has_no_owner_columns() -> None:
    """db-erd §16.3: ownership is derived from visit_session, never duplicated here - same
    convention as app/models/checkin.py::CheckIn."""

    columns = Feedback.__table__.columns
    assert "user_id" not in columns
    assert "guest_session_id" not in columns


def test_feedback_has_no_update_or_delete_columns() -> None:
    """db-erd §16.3: "원본 피드백은 수정하지 않는다" - append-only, no updated_at/deleted_at."""

    columns = Feedback.__table__.columns
    assert "updated_at" not in columns
    assert "deleted_at" not in columns


def test_feedback_visit_session_fk_is_the_established_composite_boundary_shape() -> None:
    ddl = _table_ddl()
    assert (
        "CONSTRAINT fk_feedback_visit_session_boundary FOREIGN KEY"
        "(tenant_id, event_id, visit_session_id) REFERENCES profile.visit_session "
        "(tenant_id, event_id, visit_session_id)" in ddl
    )


def test_feedback_recommendable_fk_is_the_established_composite_boundary_shape() -> None:
    ddl = _table_ddl()
    assert (
        "CONSTRAINT fk_feedback_recommendable_boundary FOREIGN KEY"
        "(tenant_id, event_id, recommendable_id) REFERENCES exhibition.recommendable "
        "(tenant_id, event_id, recommendable_id)" in ddl
    )
    assert (
        "CONSTRAINT fk_feedback_event_boundary FOREIGN KEY(tenant_id, event_id) "
        "REFERENCES exhibition.event (tenant_id, event_id)" in ddl
    )


def test_feedback_match_result_fk_is_nullable_plain_column_fk() -> None:
    ddl = _table_ddl()
    assert (
        "CONSTRAINT fk_feedback_match_result_id_match_result FOREIGN KEY(match_result_id) "
        "REFERENCES matching.match_result (match_result_id)" in ddl
    )
    assert Feedback.__table__.columns["match_result_id"].nullable is True


def test_feedback_required_columns_are_not_nullable() -> None:
    columns = Feedback.__table__.columns
    for name in (
        "feedback_id",
        "tenant_id",
        "event_id",
        "visit_session_id",
        "recommendable_id",
        "rating",
        "positive_reasons",
        "negative_reasons",
        "created_at",
    ):
        assert columns[name].nullable is False, name


def test_feedback_comment_enc_column_is_binary_and_nullable() -> None:
    column = Feedback.__table__.columns["comment_enc"]
    assert column.nullable is True
    assert column.type.python_type is bytes


def test_feedback_client_event_partial_unique_index_is_correctly_scoped() -> None:
    ddl = _index_ddl("uq_feedback_active_client_event")
    assert "UNIQUE" in ddl
    assert "(tenant_id, event_id, client_event_id)" in ddl
    assert "WHERE client_event_id IS NOT NULL" in ddl


def test_feedback_lookup_indexes_cover_expected_query_shapes() -> None:
    ddl = _index_ddl("ix_feedback_visit_session_created")
    assert "(tenant_id, event_id, visit_session_id, created_at)" in ddl
    ddl = _index_ddl("ix_feedback_recommendable_created")
    assert "(tenant_id, event_id, recommendable_id, created_at)" in ddl


def test_feedback_is_not_confused_with_check_in_or_favorite() -> None:
    from app.models.checkin import CheckIn
    from app.models.favorite import Favorite

    assert Feedback.__table__.name not in (CheckIn.__table__.name, Favorite.__table__.name)
    assert "feedback_id" in Feedback.__table__.columns
    assert "feedback_id" not in CheckIn.__table__.columns
    assert "feedback_id" not in Favorite.__table__.columns


# ---------------------------------------------------------------------------
# Critical business rule: preference vs. situational vs. review-queue reason codes must never
# blur into a single category (docs/frontend-backend-ai-interface-spec.md §13.2's processing
# table; docs/db-erd-table-spec.md §16.3's "상황 원인은 취향 가중치에 적용하지 않는다").
# ---------------------------------------------------------------------------


def test_reason_code_categories_are_pairwise_disjoint() -> None:
    preference = set(PREFERENCE_REASON_CODES)
    situational = set(SITUATIONAL_REASON_CODES)
    review = set(REVIEW_QUEUE_REASON_CODES)

    assert preference.isdisjoint(situational)
    assert preference.isdisjoint(review)
    assert situational.isdisjoint(review)


def test_reason_code_categories_exactly_partition_the_full_set() -> None:
    union = set(PREFERENCE_REASON_CODES) | set(SITUATIONAL_REASON_CODES) | set(
        REVIEW_QUEUE_REASON_CODES
    )
    assert union == set(FEEDBACK_REASON_CODES)


def test_reason_code_categories_match_interface_spec_processing_table() -> None:
    """docs/frontend-backend-ai-interface-spec.md §13.2's exact table content."""

    assert PREFERENCE_REASON_CODES == ("TASTE", "PRICE")
    assert SITUATIONAL_REASON_CODES == ("CONGESTION", "SOLD_OUT_OR_CLOSED")
    assert REVIEW_QUEUE_REASON_CODES == ("EXPLANATION_ERROR",)


def test_schema_reason_code_literal_is_derived_from_this_module_not_hand_duplicated() -> None:
    """app/schemas/feedback.py::FeedbackReasonCode must be built from FEEDBACK_REASON_CODES
    (Literal[*FEEDBACK_REASON_CODES]), not a separately hand-typed Literal - otherwise the two
    sets can silently drift (e.g. a reason code added here without the API boundary accepting
    it, or vice versa)."""

    import typing

    from app.schemas.feedback import FeedbackReasonCode

    assert set(typing.get_args(FeedbackReasonCode)) == set(FEEDBACK_REASON_CODES)


# ---------------------------------------------------------------------------
# Comment encryption round trip (app/core/auth.py::encrypt_secret/decrypt_secret envelope).
# ---------------------------------------------------------------------------


def test_comment_encryption_round_trips() -> None:
    ciphertext = encrypt_comment("맛이 예상보다 짰어요", settings=SETTINGS)
    assert ciphertext is not None
    assert decrypt_comment(ciphertext, settings=SETTINGS) == "맛이 예상보다 짰어요"


def test_comment_ciphertext_never_contains_the_plaintext() -> None:
    plaintext = "이 부스는 설명과 실제 상품이 달랐습니다"
    ciphertext = encrypt_comment(plaintext, settings=SETTINGS)
    assert ciphertext is not None
    assert plaintext.encode("utf-8") not in ciphertext


def test_comment_encryption_is_none_for_none_input() -> None:
    assert encrypt_comment(None, settings=SETTINGS) is None
    assert decrypt_comment(None, settings=SETTINGS) is None


def test_comment_decryption_fails_closed_on_wrong_purpose() -> None:
    """A value encrypted under a different purpose tag (e.g. a meeting message) must never be
    readable as a feedback comment - see app/core/auth.py::encrypt_secret's AAD binding."""

    from app.core.auth import encrypt_secret

    foreign_ciphertext = encrypt_secret(
        "다른 목적의 평문", purpose="meeting-message", settings=SETTINGS
    )
    assert decrypt_comment(foreign_ciphertext, settings=SETTINGS) is None


def test_comment_decryption_fails_closed_on_plaintext_garbage() -> None:
    assert decrypt_comment(b"not-actually-encrypted", settings=SETTINGS) is None
