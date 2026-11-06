"""Brand asset management -- colour CRUD, logo upload validation, and
cross-org isolation -- exercised through the real HTTP API."""

from app.models import OrganisationCreate, UserCreate, UserRole
from app.repositories import assets, organisations, users

PNG_MAGIC = b"\x89PNG\r\n\x1a\n" + b"0" * 32
JPEG_MAGIC = b"\xff\xd8\xff" + b"0" * 32
SAFE_SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><circle r="5"/></svg>'
UNSAFE_SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
# Confirmed-bypassable against the old substring blocklist in the Phase 3
# audit: no "<script", "javascript:", "onload=", "onerror=" or
# "<foreignobject" substring, yet still executes script when rendered.
ONCLICK_SVG = b'<svg xmlns="http://www.w3.org/2000/svg" onclick="alert(1)"><rect/></svg>'


async def _other_org_headers():
    org = await organisations.create(OrganisationCreate(name="Other Org Assets"))
    user = await users.create(
        UserCreate(organisation_id=org.id, name="Other", email="other-assets@example.com", role=UserRole.ADMIN)
    )
    return {"X-Organisation-Id": str(org.id), "X-User-Id": str(user.id)}


async def test_colour_asset_crud(api_client, demo_headers):
    headers, org, _user = demo_headers
    create_resp = await api_client.post(
        "/api/assets",
        headers=headers,
        json={"organisation_id": str(org.id), "type": "colour", "name": "Test Blue", "status": "approved", "hex_value": "#123456"},
    )
    assert create_resp.status_code == 201, create_resp.text
    asset_id = create_resp.json()["id"]

    update_resp = await api_client.patch(f"/api/assets/{asset_id}", headers=headers, json={"status": "deprecated"})
    assert update_resp.json()["status"] == "deprecated"

    assert (await api_client.delete(f"/api/assets/{asset_id}", headers=headers)).status_code == 204


async def test_colour_asset_requires_hex_value(api_client, demo_headers):
    headers, org, _user = demo_headers
    resp = await api_client.post(
        "/api/assets",
        headers=headers,
        json={"organisation_id": str(org.id), "type": "colour", "name": "No Hex", "status": "approved"},
    )
    assert resp.status_code == 400


async def test_logo_cannot_be_created_via_json(api_client, demo_headers):
    headers, org, _user = demo_headers
    resp = await api_client.post(
        "/api/assets",
        headers=headers,
        json={"organisation_id": str(org.id), "type": "logo", "name": "Logo", "status": "approved"},
    )
    assert resp.status_code == 400


async def test_logo_upload_png_and_file_serving(api_client, demo_headers):
    headers, _org, _user = demo_headers
    resp = await api_client.post(
        "/api/assets/upload",
        headers=headers,
        files={"file": ("logo.png", PNG_MAGIC, "image/png")},
        data={"name": "Primary Logo", "status": "approved"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["type"] == "logo"
    asset_id = body["id"]
    # file_path is a generated filename only, not an absolute filesystem path
    assert "/" not in body["file_path"].replace("\\", "/").lstrip("/") or body["file_path"].count("/") == 0

    org_id, user_id = headers["X-Organisation-Id"], headers["X-User-Id"]
    file_resp = await api_client.get(f"/api/assets/{asset_id}/file?organisation_id={org_id}&user_id={user_id}")
    assert file_resp.status_code == 200
    assert file_resp.content == PNG_MAGIC
    assert file_resp.headers["content-type"] == "image/png"
    assert file_resp.headers["x-content-type-options"] == "nosniff"
    assert file_resp.headers["content-disposition"].startswith("inline")


async def test_logo_upload_jpeg_and_file_serving(api_client, demo_headers):
    headers, _org, _user = demo_headers
    resp = await api_client.post(
        "/api/assets/upload",
        headers=headers,
        files={"file": ("logo.jpg", JPEG_MAGIC, "image/jpeg")},
        data={"name": "JPEG Logo", "status": "approved"},
    )
    assert resp.status_code == 201, resp.text
    asset_id = resp.json()["id"]

    org_id, user_id = headers["X-Organisation-Id"], headers["X-User-Id"]
    file_resp = await api_client.get(f"/api/assets/{asset_id}/file?organisation_id={org_id}&user_id={user_id}")
    assert file_resp.status_code == 200
    assert file_resp.content == JPEG_MAGIC
    assert file_resp.headers["content-type"] == "image/jpeg"
    assert file_resp.headers["x-content-type-options"] == "nosniff"


async def test_logo_upload_rejects_mismatched_content(api_client, demo_headers):
    headers, _org, _user = demo_headers
    resp = await api_client.post(
        "/api/assets/upload",
        headers=headers,
        files={"file": ("fake.png", b"not actually a png", "image/png")},
        data={"name": "Fake"},
    )
    assert resp.status_code == 400


async def test_logo_upload_rejects_svg_entirely(api_client, demo_headers):
    """SVG support was removed after the Phase 3 security audit: both an
    innocuous-looking SVG and a SMIL/onclick XSS payload that bypassed the
    old substring blocklist must now be rejected, regardless of content."""
    headers, _org, _user = demo_headers
    for name, payload in [("harmless.svg", SAFE_SVG), ("unsafe.svg", UNSAFE_SVG), ("onclick.svg", ONCLICK_SVG)]:
        resp = await api_client.post(
            "/api/assets/upload",
            headers=headers,
            files={"file": (name, payload, "image/svg+xml")},
            data={"name": "SVG attempt"},
        )
        assert resp.status_code == 400, f"{name} should be rejected, got {resp.status_code}: {resp.text}"


async def test_logo_upload_rejects_disallowed_extension(api_client, demo_headers):
    headers, _org, _user = demo_headers
    resp = await api_client.post(
        "/api/assets/upload",
        headers=headers,
        files={"file": ("logo.gif", b"GIF89a", "image/gif")},
        data={"name": "Gif"},
    )
    assert resp.status_code == 400


async def test_asset_cross_org_isolation(api_client, demo_headers):
    headers_a, org, _user = demo_headers
    headers_b = await _other_org_headers()
    created = await api_client.post(
        "/api/assets",
        headers=headers_a,
        json={"organisation_id": str(org.id), "type": "colour", "name": "Private", "status": "approved", "hex_value": "#000000"},
    )
    asset_id = created.json()["id"]

    assert (await api_client.get(f"/api/assets/{asset_id}", headers=headers_b)).status_code == 404
    assert (await api_client.patch(f"/api/assets/{asset_id}", headers=headers_b, json={"status": "deprecated"})).status_code == 404
    assert (await api_client.delete(f"/api/assets/{asset_id}", headers=headers_b)).status_code == 404

    still_there = await api_client.get(f"/api/assets/{asset_id}", headers=headers_a)
    assert still_there.status_code == 200
    assert still_there.json()["status"] == "approved"


async def test_legacy_svg_record_cannot_be_served(api_client, demo_headers):
    """Simulates a pre-existing asset record (e.g. from before this fix)
    whose file_path points at an actual SVG file on disk. Serving re-sniffs
    the file's real bytes rather than trusting the stored extension, so it
    must refuse to serve it as executable/renderable content."""
    from app.core.storage import ASSETS_DIR, write_bytes
    from app.models import AssetCreate, AssetStatus, AssetType

    headers, org, _user = demo_headers
    legacy = await assets.create(
        AssetCreate(organisation_id=org.id, type=AssetType.LOGO, name="Legacy SVG", status=AssetStatus.APPROVED, file_path=None)
    )
    write_bytes(ASSETS_DIR / f"{legacy.id}.svg", SAFE_SVG)
    await assets.update(legacy.id, {"file_path": f"{legacy.id}.svg"}, organisation_id=org.id)

    org_id, user_id = headers["X-Organisation-Id"], headers["X-User-Id"]
    resp = await api_client.get(f"/api/assets/{legacy.id}/file?organisation_id={org_id}&user_id={user_id}")
    assert resp.status_code == 415
    assert resp.content != SAFE_SVG


async def test_logo_upload_write_failure_leaves_no_orphaned_record(api_client, demo_headers, monkeypatch):
    """Simulates a disk failure while storing the uploaded file (found in
    the Phase 3 audit to previously leave a DB record with file_path=None
    pointing at nothing). The upload must fail cleanly with no orphan."""
    import app.routers.assets as assets_router

    headers, org, _user = demo_headers

    def _boom(path, content):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(assets_router, "write_bytes", _boom)

    resp = await api_client.post(
        "/api/assets/upload",
        headers=headers,
        files={"file": ("logo.png", PNG_MAGIC, "image/png")},
        data={"name": "Will Fail"},
    )
    assert resp.status_code == 500

    remaining = await assets.list(organisation_id=org.id, filter={"name": "Will Fail"})
    assert remaining == []


async def test_asset_file_cross_org_isolation(api_client, demo_headers):
    headers_a, _org, _user = demo_headers
    headers_b = await _other_org_headers()

    upload = await api_client.post(
        "/api/assets/upload",
        headers=headers_a,
        files={"file": ("logo.png", PNG_MAGIC, "image/png")},
        data={"name": "Org A Logo", "status": "approved"},
    )
    asset_id = upload.json()["id"]

    # Org B's own (valid) context querying org A's asset id must not serve the file.
    cross_resp = await api_client.get(
        f"/api/assets/{asset_id}/file?organisation_id={headers_b['X-Organisation-Id']}&user_id={headers_b['X-User-Id']}"
    )
    assert cross_resp.status_code == 404
