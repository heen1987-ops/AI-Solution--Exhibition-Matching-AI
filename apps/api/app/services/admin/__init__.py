"""BACKEND-007 admin service layer - exhibitor master-approval + booth operating-status.

``app/api/v1/routers/admin.py`` and nothing else should reach into
``app.services.admin.exhibitor_approval`` / ``app.services.admin.booth_status`` directly for
the business logic; import the submodules (not re-exported flat here, since both submodules
also export same-named typed-error base classes that would collide on a single ``__all__``).
"""

from __future__ import annotations
