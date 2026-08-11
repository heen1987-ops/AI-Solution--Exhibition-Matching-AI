"""WAVE 2E BACKEND-EVENT-COLLECTION service package.

Client-reported UI event ingestion (impressions/clicks/search submissions the server cannot
otherwise observe). See ``app/models/interaction_event.py`` and
``app/schemas/interaction_event.py`` module docstrings for the prior-art map: the durable
event rows land in the *existing* ``interaction.interaction_event`` /
``interaction.client_event_dedupe`` tables (``app/models/matching.py``), and only the
rejection ledger (``interaction.event_ingestion_failure``) is new to this track.

Modules
-------
- ``masking``    : free-text search-query PII masking + context allow-listing.
- ``validation`` : per-item schema/timestamp/kiosk-identity validation.
- ``rate_limit`` : lightweight in-process beacon rate limiting.
- ``ingestion``  : the orchestrating service the router calls.
"""
