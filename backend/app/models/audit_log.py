from typing import Any

from app.models.common import OrgScopedCreate, OrgScopedModel, PyObjectId


class AuditLogCreate(OrgScopedCreate):
    actor_id: PyObjectId
    action: str
    entity_type: str
    entity_id: PyObjectId
    details: dict[str, Any] = {}


class AuditLog(OrgScopedModel):
    actor_id: PyObjectId
    action: str
    entity_type: str
    entity_id: PyObjectId
    details: dict[str, Any]
