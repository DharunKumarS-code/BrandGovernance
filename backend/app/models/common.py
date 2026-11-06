from datetime import datetime, timezone
from typing import Annotated, Any

from bson import ObjectId
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, PlainSerializer


def _validate_object_id(value: Any) -> ObjectId:
    if isinstance(value, ObjectId):
        return value
    if isinstance(value, str) and ObjectId.is_valid(value):
        return ObjectId(value)
    raise ValueError(f"Invalid ObjectId: {value!r}")


PyObjectId = Annotated[
    ObjectId,
    BeforeValidator(_validate_object_id),
    PlainSerializer(str, return_type=str, when_used="json"),
]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MongoBaseModel(BaseModel):
    """Base for documents read back from MongoDB."""

    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
    )

    id: PyObjectId = Field(alias="_id")
    created_at: datetime
    updated_at: datetime


class OrgScopedModel(MongoBaseModel):
    """Base for every collection except `organisations` itself."""

    organisation_id: PyObjectId


class OrgScopedCreate(BaseModel):
    """Base for create payloads of every collection except `organisations`."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    organisation_id: PyObjectId
