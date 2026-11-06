"""Early rejection of oversized uploads via the Content-Length header.

This is a cheap, low-risk pre-check -- it only reads a request header, never
the body -- that runs before Starlette's multipart parser would otherwise
fully receive and spool an oversized upload to memory/disk. The per-route
handlers (app/routers/guidelines.py, app/routers/assets.py) still enforce
the exact limit after reading, so this is a second, earlier line of defense,
not a replacement for them.

Known limitation: a request sent with chunked transfer-encoding and no
Content-Length header bypasses this pre-check entirely and is only caught
by the existing post-read size check in the route handler. True streaming
byte-counting (aborting mid-upload before the body is fully received) would
require bypassing FastAPI's File()/Form() parsing and manually driving
request.stream(), which is a meaningfully larger change -- left out here to
stay within scope, consistent with the Phase 3 audit follow-up instructions.
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import settings

# Multipart form-data adds a small amount of overhead (boundaries, per-part
# headers) on top of the raw file bytes; this allowance is generous enough
# to never falsely reject a file at exactly the configured limit.
_MULTIPART_OVERHEAD_BYTES = 64 * 1024

_UPLOAD_LIMITS: dict[tuple[str, str], int] = {
    ("POST", "/api/guidelines"): settings.max_guideline_upload_mb * 1024 * 1024,
    ("POST", "/api/assets/upload"): settings.max_asset_upload_mb * 1024 * 1024,
    ("POST", "/api/submissions/upload"): settings.max_guideline_upload_mb * 1024 * 1024,
}


class MaxContentLengthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        limit = _UPLOAD_LIMITS.get((request.method, request.url.path))
        if limit is not None:
            content_length = request.headers.get("content-length")
            if content_length is not None:
                try:
                    declared_size = int(content_length)
                except ValueError:
                    declared_size = None
                if declared_size is not None and declared_size > limit + _MULTIPART_OVERHEAD_BYTES:
                    return JSONResponse(
                        {"detail": "Request body exceeds the allowed upload size."},
                        status_code=413,
                    )
        return await call_next(request)
