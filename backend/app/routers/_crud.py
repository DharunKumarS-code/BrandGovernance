"""Generic organisation-scoped CRUD router factory.

brand_facts, terminology and claim_policies all follow the same shape
(create/list/get/update/delete behind the demo org context), so this one
factory avoids writing the same five endpoints three times.

Request bodies are accepted as plain dicts and validated manually against
the real Create/Update model (via `model_validate`) rather than being
declared as the route's parameter type. FastAPI decomposes a pydantic model
used directly as a parameter type into per-field `ModelField`s that build
their own standalone schema outside the model's own `model_config`, which
breaks for any field typed `PyObjectId` (bson.ObjectId needs
`arbitrary_types_allowed`, which only applies via the model's config when
the model is validated as a whole). Validating manually sidesteps that.
"""

from typing import Any

from bson.errors import InvalidId
from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, ValidationError

from app.core.demo_context import DemoContext, get_demo_context
from app.repositories.base import Repository


def _validation_error_response(exc: ValidationError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, exc.errors())


def make_crud_router(
    *,
    prefix: str,
    tag: str,
    repo: Repository,
    create_model: type[BaseModel],
    update_model: type[BaseModel],
) -> APIRouter:
    router = APIRouter(prefix=prefix, tags=[tag])

    @router.post("", status_code=status.HTTP_201_CREATED)
    async def create_item(payload: dict[str, Any] = Body(...), context: DemoContext = Depends(get_demo_context)) -> Any:
        try:
            data = create_model.model_validate({**payload, "organisation_id": context.organisation_id})
        except ValidationError as exc:
            raise _validation_error_response(exc)
        created = await repo.create(data)
        return created.model_dump(mode="json")

    @router.get("")
    async def list_items(context: DemoContext = Depends(get_demo_context)) -> Any:
        items = await repo.list(organisation_id=context.organisation_id, limit=1000)
        return [item.model_dump(mode="json") for item in items]

    @router.get("/{item_id}")
    async def get_item(item_id: str, context: DemoContext = Depends(get_demo_context)) -> Any:
        try:
            item = await repo.get(item_id, organisation_id=context.organisation_id)
        except InvalidId:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid id format.")
        if item is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
        return item.model_dump(mode="json")

    @router.patch("/{item_id}")
    async def update_item(
        item_id: str, payload: dict[str, Any] = Body(...), context: DemoContext = Depends(get_demo_context)
    ) -> Any:
        try:
            parsed = update_model.model_validate(payload)
        except ValidationError as exc:
            raise _validation_error_response(exc)
        changes = parsed.model_dump(exclude_unset=True)  # python mode: keep ObjectId/datetime native for Mongo
        if not changes:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "No fields supplied to update.")
        try:
            updated = await repo.update(item_id, changes, organisation_id=context.organisation_id)
        except InvalidId:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid id format.")
        if updated is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
        return updated.model_dump(mode="json")

    @router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_item(item_id: str, context: DemoContext = Depends(get_demo_context)) -> None:
        try:
            deleted = await repo.delete(item_id, organisation_id=context.organisation_id)
        except InvalidId:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid id format.")
        if not deleted:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")

    return router
