"""Phase 7 Stage 3, Stage 1: submission image upload/serve -- focused tests."""

from app.core.config import settings
from app.core.security import create_access_token
from app.models import OrganisationCreate, UserCreate, UserRole
from app.repositories import organisations, users


def _png_bytes() -> bytes:
    # 1x1 transparent PNG.
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
        "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
        "0000004945454e44ae426082"
    )


async def test_upload_image_creates_draft_submission_with_image_revision(api_client, demo_headers):
    headers, _org, _user = demo_headers
    resp = await api_client.post(
        "/api/submissions/upload-image", headers=headers,
        files={"file": ("ad.png", _png_bytes(), "image/png")}, data={"title": "Image Ad"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "draft"

    content_resp = await api_client.get(f"/api/submissions/{body['id']}/content", headers=headers)
    assert content_resp.json()["content"] == ""


async def test_upload_image_rejects_non_image(api_client, demo_headers):
    headers, _org, _user = demo_headers
    resp = await api_client.post(
        "/api/submissions/upload-image", headers=headers,
        files={"file": ("ad.txt", b"not an image", "text/plain")},
    )
    assert resp.status_code == 400


async def test_image_served_back_correctly_and_cross_org_isolated(api_client, demo_headers):
    headers, org, _user = demo_headers
    created = await api_client.post(
        "/api/submissions/upload-image", headers=headers,
        files={"file": ("ad.png", _png_bytes(), "image/png")},
    )
    sub_id = created.json()["id"]

    # Query-param context, like get_asset_file -- this endpoint is meant
    # for a plain <img src=...>, which can't attach custom headers.
    img_resp = await api_client.get(
        f"/api/submissions/{sub_id}/revisions/1/image",
        params={"organisation_id": str(org.id), "user_id": headers["X-User-Id"]},
    )
    assert img_resp.status_code == 200
    assert img_resp.headers["content-type"] == "image/png"
    assert img_resp.content == _png_bytes()

    other_org = await organisations.create(OrganisationCreate(name="Image Isolation Org"))
    other_user = await users.create(
        UserCreate(organisation_id=other_org.id, name="Outsider", email="image-outsider@example.com", role=UserRole.ADMIN)
    )
    cross_org_resp = await api_client.get(
        f"/api/submissions/{sub_id}/revisions/1/image",
        params={"organisation_id": str(other_org.id), "user_id": str(other_user.id)},
    )
    assert cross_org_resp.status_code == 404


async def test_text_submission_has_no_image_to_serve(api_client, demo_headers):
    headers, org, _user = demo_headers
    created = await api_client.post("/api/submissions", headers=headers, json={"title": "Text Ad", "content": "x"})
    resp = await api_client.get(
        f"/api/submissions/{created.json()['id']}/revisions/1/image",
        params={"organisation_id": str(org.id), "user_id": headers["X-User-Id"]},
    )
    assert resp.status_code == 404

async def test_bearer_authenticated_asset_and_submission_images(api_client, monkeypatch):
    from app.models import OrganisationCreate, UserCreate, UserRole
    from app.repositories import organisations, users

    monkeypatch.setattr(settings, "require_jwt_auth", True)
    org = await organisations.create(OrganisationCreate(name="JWT Image Org"))
    user = await users.create(
        UserCreate(organisation_id=org.id, name="Image User", email="jwt-image@example.com", role=UserRole.ADMIN)
    )
    token, _ = create_access_token(user_id=str(user.id), organisation_id=str(org.id), role="admin")
    headers = {"Authorization": f"Bearer {token}"}

    asset = await api_client.post(
        "/api/assets/upload", headers=headers,
        files={"file": ("logo.png", _png_bytes(), "image/png")}, data={"name": "Logo"},
    )
    assert asset.status_code == 201, asset.text
    asset_id = asset.json()["id"]
    asset_image = await api_client.get(f"/api/assets/{asset_id}/file", headers=headers)
    assert asset_image.status_code == 200
    assert asset_image.content == _png_bytes()
    assert (await api_client.get(f"/api/assets/{asset_id}/file")).status_code == 401

    submission = await api_client.post(
        "/api/submissions/upload-image", headers=headers,
        files={"file": ("ad.png", _png_bytes(), "image/png")}, data={"title": "JWT Image Ad"},
    )
    assert submission.status_code == 201, submission.text
    image_url = f"/api/submissions/{submission.json()['id']}/revisions/1/image"
    submission_image = await api_client.get(image_url, headers=headers)
    assert submission_image.status_code == 200
    assert submission_image.content == _png_bytes()
    assert (await api_client.get(image_url)).status_code == 401

    other_org = await organisations.create(OrganisationCreate(name="Other JWT Image Org"))
    other_user = await users.create(
        UserCreate(organisation_id=other_org.id, name="Other", email="other-jwt-image@example.com", role=UserRole.ADMIN)
    )
    other_token, _ = create_access_token(user_id=str(other_user.id), organisation_id=str(other_org.id), role="admin")
    cross_org = await api_client.get(image_url, headers={"Authorization": f"Bearer {other_token}"})
    assert cross_org.status_code == 404


async def test_image_context_bearer_query_precedence_and_missing_tokens(api_client, demo_headers, monkeypatch):
    headers, org, user = demo_headers
    uploaded = await api_client.post(
        "/api/submissions/upload-image", headers=headers,
        files={"file": ("ad.png", _png_bytes(), "image/png")}, data={"title": "Context Auth"},
    )
    assert uploaded.status_code == 201
    image_url = f"/api/submissions/{uploaded.json()['id']}/revisions/1/image"
    bearer, _ = create_access_token(user_id=str(user.id), organisation_id=str(org.id), role="admin")

    monkeypatch.setattr(settings, "require_jwt_auth", True)
    bearer_response = await api_client.get(image_url, headers={"Authorization": f"Bearer {bearer}"})
    assert bearer_response.status_code == 200

    query_response = await api_client.get(image_url, params={"token": bearer})
    assert query_response.status_code == 200

    # Invalid query credentials cannot override a valid Authorization header.
    precedence_response = await api_client.get(
        image_url, headers={"Authorization": f"Bearer {bearer}"}, params={"token": "invalid-query-token"}
    )
    assert precedence_response.status_code == 200

    invalid_response = await api_client.get(
        image_url, headers={"Authorization": "Bearer invalid-header-token"}, params={"token": bearer}
    )
    assert invalid_response.status_code == 401
    missing_response = await api_client.get(image_url)
    assert missing_response.status_code == 401
