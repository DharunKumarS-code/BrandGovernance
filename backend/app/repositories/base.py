from typing import Generic, TypeVar

from bson import ObjectId
from pydantic import BaseModel
from pymongo import ReturnDocument

from app.core.db import db
from app.models.common import utcnow

CreateT = TypeVar("CreateT", bound=BaseModel)
ModelT = TypeVar("ModelT", bound=BaseModel)


def _as_object_id(value: ObjectId | str) -> ObjectId:
    return value if isinstance(value, ObjectId) else ObjectId(value)


class Repository(Generic[CreateT, ModelT]):
    """Thin CRUD layer over one MongoDB collection.

    Every collection except `organisations` is scoped by organisation_id,
    so a caller can never read or mutate another org's records by id alone.
    """

    def __init__(self, collection_name: str, model: type[ModelT], org_scoped: bool = True):
        self.collection = db[collection_name]
        self.model = model
        self.org_scoped = org_scoped

    def _filter(self, id: ObjectId | str, organisation_id: ObjectId | str | None) -> dict:
        query: dict = {"_id": _as_object_id(id)}
        if self.org_scoped and organisation_id is not None:
            query["organisation_id"] = _as_object_id(organisation_id)
        return query

    async def create(self, data: CreateT) -> ModelT:
        doc = data.model_dump()
        now = utcnow()
        doc["created_at"] = now
        doc["updated_at"] = now
        result = await self.collection.insert_one(doc)
        doc["_id"] = result.inserted_id
        return self.model.model_validate(doc)

    async def get(self, id: ObjectId | str, organisation_id: ObjectId | str | None = None) -> ModelT | None:
        doc = await self.collection.find_one(self._filter(id, organisation_id))
        return self.model.model_validate(doc) if doc else None

    async def list(
        self,
        organisation_id: ObjectId | str | None = None,
        filter: dict | None = None,
        limit: int = 100,
        skip: int = 0,
    ) -> list[ModelT]:
        query = dict(filter or {})
        if self.org_scoped and organisation_id is not None:
            query["organisation_id"] = _as_object_id(organisation_id)
        cursor = self.collection.find(query).skip(skip).limit(limit)
        return [self.model.model_validate(doc) async for doc in cursor]

    async def update(
        self,
        id: ObjectId | str,
        changes: dict,
        organisation_id: ObjectId | str | None = None,
    ) -> ModelT | None:
        changes = dict(changes)
        changes["updated_at"] = utcnow()
        doc = await self.collection.find_one_and_update(
            self._filter(id, organisation_id),
            {"$set": changes},
            return_document=ReturnDocument.AFTER,
        )
        return self.model.model_validate(doc) if doc else None

    async def delete(self, id: ObjectId | str, organisation_id: ObjectId | str | None = None) -> bool:
        result = await self.collection.delete_one(self._filter(id, organisation_id))
        return result.deleted_count > 0

    async def delete_many(self, filter: dict) -> int:
        result = await self.collection.delete_many(filter)
        return result.deleted_count

    async def count(self, organisation_id: ObjectId | str | None = None, filter: dict | None = None) -> int:
        query = dict(filter or {})
        if self.org_scoped and organisation_id is not None:
            query["organisation_id"] = _as_object_id(organisation_id)
        return await self.collection.count_documents(query)
