from typing import Any

from bson.errors import InvalidId
from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import ValidationError

from app.core.config import settings
from app.core.demo_context import DemoContext, get_demo_context, get_demo_context_from_query
from app.core.storage import ASSETS_DIR, asset_file_path, delete_if_exists, sniff_image_type, write_bytes
from app.models import AssetCreate, AssetStatus, AssetType, AssetUpdate
from app.repositories import assets

router = APIRouter(prefix="/api/assets", tags=["assets"])

MAX_UPLOAD_BYTES = settings.max_asset_upload_mb * 1024 * 1024

# PNG/JPEG only -- SVG support was removed after the Phase 3 security audit
# found the substring-based script-marker check bypassable (onclick=,
# onmouseover=, SMIL event attributes, external xlink:href references, and
# XXE all passed it undetected). Content is validated by signature (shared
# helper in app/core/storage.py), not by filename extension or
# client-supplied Content-Type, in both directions: on upload and on
# serving (get_asset_file re-sniffs the bytes on disk rather than trusting
# the stored extension).


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_colour_asset(
    body: dict[str, Any] = Body(...), context: DemoContext = Depends(get_demo_context)
) -> Any:
    # AssetCreate is validated manually (not used as the route's parameter
    # type) -- see the docstring in app/routers/_crud.py for why a model
    # with a PyObjectId field breaks FastAPI's per-field schema generation
    # when declared directly as a parameter annotation.
    try:
        payload = AssetCreate.model_validate({**body, "organisation_id": context.organisation_id})
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, exc.errors())

    if payload.type != AssetType.COLOUR:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Logo assets must be created via POST /api/assets/upload.",
        )
    if not payload.hex_value:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Colour assets require a hex_value.")
    data = payload.model_copy(update={"organisation_id": context.organisation_id, "file_path": None})
    created = await assets.create(data)
    return created.model_dump(mode="json")


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_logo(
    file: UploadFile = File(...),
    name: str = Form(...),
    status_: AssetStatus = Form(AssetStatus.APPROVED, alias="status"),
    context: DemoContext = Depends(get_demo_context),
) -> Any:
    content = await file.read()
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Uploaded file is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"File exceeds the {settings.max_asset_upload_mb}MB upload limit.",
        )
    sniffed = sniff_image_type(content)
    if sniffed is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Only PNG or JPEG logos are accepted (file content did not match either format).",
        )
    ext, _content_type = sniffed

    created = await assets.create(
        AssetCreate(
            organisation_id=context.organisation_id,
            type=AssetType.LOGO,
            name=name,
            status=status_,
            file_path=None,
        )
    )
    # Generated filename derived from the new record's id -- never the
    # client-supplied filename -- so there is no path-traversal surface.
    try:
        write_bytes(asset_file_path(created.id, ext), content)
    except OSError as exc:
        # Storing the file failed (disk full, permissions, ...): don't leave
        # a DB record with file_path=None pointing at nothing -- remove it
        # and report a clear error instead of a silently broken asset.
        await assets.delete(created.id, organisation_id=context.organisation_id)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, f"Failed to store uploaded file: {exc}"
        )

    stored_filename = f"{created.id}{ext}"
    updated = await assets.update(created.id, {"file_path": stored_filename}, organisation_id=context.organisation_id)
    return updated.model_dump(mode="json")


@router.get("")
async def list_assets(context: DemoContext = Depends(get_demo_context)) -> Any:
    items = await assets.list(organisation_id=context.organisation_id, limit=1000)
    return [item.model_dump(mode="json") for item in items]


@router.get("/{asset_id}")
async def get_asset(asset_id: str, context: DemoContext = Depends(get_demo_context)) -> Any:
    try:
        item = await assets.get(asset_id, organisation_id=context.organisation_id)
    except InvalidId:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid id format.")
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Asset not found.")
    return item.model_dump(mode="json")


@router.get("/{asset_id}/file")
async def get_asset_file(asset_id: str, context: DemoContext = Depends(get_demo_context_from_query)):
    # Query-param context (not headers) because the frontend renders this
    # via a plain <img src=...>, which cannot attach custom headers.
    try:
        item = await assets.get(asset_id, organisation_id=context.organisation_id)
    except InvalidId:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid id format.")
    if item is None or not item.file_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Asset file not found.")

    path = ASSETS_DIR / item.file_path
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Asset file not found.")

    # Content-Type is derived from the file's actual bytes, never from the
    # stored extension or any client-supplied value -- this also means any
    # pre-existing non-PNG/JPEG file (e.g. an old SVG record from before the
    # security fix) fails the sniff and is refused rather than served.
    with open(path, "rb") as f:
        header = f.read(16)
    sniffed = sniff_image_type(header)
    if sniffed is None:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "This asset's stored file is not a supported image type and cannot be served.",
        )
    _ext, content_type = sniffed

    return FileResponse(
        path,
        media_type=content_type,
        headers={
            "X-Content-Type-Options": "nosniff",
            # "inline" is safe here specifically because the content has
            # just been verified to be a raster image (PNG/JPEG) and nothing
            # else -- raster image bytes cannot carry executable script, so
            # inline rendering (required for the frontend's <img> tag) does
            # not reopen the SVG-script risk this replaces.
            "Content-Disposition": f'inline; filename="asset-{asset_id}{_ext}"',
        },
    )


@router.patch("/{asset_id}")
async def update_asset(
    asset_id: str, payload: AssetUpdate, context: DemoContext = Depends(get_demo_context)
) -> Any:
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No fields supplied to update.")
    try:
        updated = await assets.update(asset_id, changes, organisation_id=context.organisation_id)
    except InvalidId:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid id format.")
    if updated is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Asset not found.")
    return updated.model_dump(mode="json")


@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_asset(asset_id: str, context: DemoContext = Depends(get_demo_context)) -> None:
    try:
        item = await assets.get(asset_id, organisation_id=context.organisation_id)
    except InvalidId:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid id format.")
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Asset not found.")

    if item.file_path:
        delete_if_exists(ASSETS_DIR / item.file_path)
    await assets.delete(item.id, organisation_id=context.organisation_id)
