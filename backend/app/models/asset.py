from enum import StrEnum

from pydantic import BaseModel

from app.models.common import OrgScopedCreate, OrgScopedModel


class AssetType(StrEnum):
    LOGO = "logo"
    COLOUR = "colour"


class AssetStatus(StrEnum):
    APPROVED = "approved"
    DEPRECATED = "deprecated"


class AssetCreate(OrgScopedCreate):
    type: AssetType
    name: str
    status: AssetStatus
    file_path: str | None = None
    hex_value: str | None = None


class Asset(OrgScopedModel):
    type: AssetType
    name: str
    status: AssetStatus
    file_path: str | None = None
    hex_value: str | None = None


class AssetUpdate(BaseModel):
    name: str | None = None
    status: AssetStatus | None = None
    hex_value: str | None = None
