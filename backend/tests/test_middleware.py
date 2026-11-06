"""MaxContentLengthMiddleware: rejects oversized uploads by Content-Length
before the route handler's own (larger) size check would ever see them."""

import app.core.middleware as middleware_mod


async def test_oversized_content_length_rejected_before_route_runs(api_client, demo_headers, monkeypatch):
    headers, _org, _user = demo_headers
    # A tiny limit (well under the body size below) proves the 413 comes
    # from the middleware's own Content-Length check, not the route
    # handler's post-read size check (which still uses the real 20MB
    # limit and would accept this body). Monkeypatching via item
    # assignment (not replacing the dict object) because the middleware
    # module looks up the same module-global dict by reference.
    monkeypatch.setitem(middleware_mod._UPLOAD_LIMITS, ("POST", "/api/guidelines"), 10)

    # Must clear the 64KB multipart-overhead allowance the middleware grants
    # on top of the limit, so the body needs to be bigger than that to prove
    # the check actually fires.
    oversized_body = b"%PDF-1.4\n" + b"0" * 200_000  # 200KB, still far under the real 20MB app limit
    resp = await api_client.post(
        "/api/guidelines",
        headers=headers,
        files={"file": ("small.pdf", oversized_body, "application/pdf")},
    )
    assert resp.status_code == 413
    assert "exceeds" in resp.json()["detail"].lower()


async def test_normal_sized_upload_passes_middleware(api_client, demo_headers):
    """The middleware must not interfere with a normal, well-under-limit upload."""
    import fitz

    doc = fitz.open()
    doc.new_page().insert_text((50, 72), "normal content")
    pdf_bytes = doc.tobytes()
    doc.close()

    headers, _org, _user = demo_headers
    resp = await api_client.post(
        "/api/guidelines",
        headers=headers,
        files={"file": ("normal.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == 201, resp.text
