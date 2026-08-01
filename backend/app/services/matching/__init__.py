"""Typed matching service layer for the modular backend.

The first published unit contains profile resolution, normalized feature
construction, and the stage 11 through 13 score adapters.  Candidate retrieval,
hard-filter persistence, orchestration, result persistence, and public API
modules are published as separate verified units so incomplete cross-domain
foreign keys are never introduced merely to expose the scorer.
"""
