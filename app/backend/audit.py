"""
Activity/audit log helpers.

A single org-scoped feed of "who did what": build a record, write it, serialize
it. The builder/serializer are pure and unit-tested; ``record_activity`` writes a
row (best-effort — auditing must never break the action it's logging).
"""

from __future__ import annotations

import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def build_activity(*, action: str, organization_id: int, user_id: Optional[int] = None,
                   entity_type: Optional[str] = None, entity_id: Optional[int] = None,
                   details: Optional[dict] = None) -> dict:
    """ORM kwargs for an ActivityLog row (details serialized to JSON)."""
    return {
        "action": action,
        "organization_id": organization_id,
        "user_id": user_id,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "details": json.dumps(details) if details else None,
    }


def record_activity(db, *, action: str, organization_id: int, user_id: Optional[int] = None,
                    entity_type: Optional[str] = None, entity_id: Optional[int] = None,
                    details: Optional[dict] = None) -> None:
    """Write an activity row. Best-effort: never raises into the caller."""
    try:
        import models
        db.add(models.ActivityLog(**build_activity(
            action=action, organization_id=organization_id, user_id=user_id,
            entity_type=entity_type, entity_id=entity_id, details=details)))
        db.commit()
    except Exception as exc:  # noqa: BLE001 — auditing must not break the action
        logger.warning("activity log write failed (%s): %s", action, exc)
        try:
            db.rollback()
        except Exception:
            pass


def activity_to_dict(row) -> dict:
    """Serialize an ActivityLog row for the API."""
    try:
        details = json.loads(row.details) if row.details else None
    except (json.JSONDecodeError, TypeError):
        details = None
    return {
        "id": getattr(row, "id", None),
        "action": row.action,
        "user_id": row.user_id,
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "details": details,
        "created_at": row.created_at.isoformat() if getattr(row, "created_at", None) else None,
    }
