"""BACKEND-ANALYTICS (WAVE 2E) - role-scoped read API over the analytics data mart.

Modules
-------
- ``access.py``       role resolution/authorization (4 analytics roles).
- ``suppression.py``  small-group suppression + defensive PII redaction.
- ``queries.py``      per-endpoint service functions (query the real
                      ``analytics.*`` mart tables landed by WORKER-ANALYTICS in
                      ``app/models/analytics.py``, plus a small set of
                      read-only structural-headcount tables - see that
                      module's docstring) used by
                      ``app/api/v1/routers/analytics.py``.

Note: an earlier draft of this package had a ``tables.py`` module modelling a
*provisional* fact/dim shape written before WORKER-ANALYTICS's tables landed.
It has been removed - ``queries.py`` now imports the real ORM classes from
``app.models.analytics`` directly (see ``app/schemas/analytics.py``'s
"Reconciliation note" docstring for the full history).
"""
