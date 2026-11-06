from pydantic import BaseModel

from app.models.common import MongoBaseModel


class OrganisationCreate(BaseModel):
    name: str


class Organisation(MongoBaseModel):
    name: str
