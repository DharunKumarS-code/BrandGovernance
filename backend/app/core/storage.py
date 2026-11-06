"""Local filesystem storage for uploaded guideline PDFs and brand assets.

Filenames are always generated from a trusted MongoDB ObjectId plus a
server-validated extension -- never from user-supplied input -- so there is
no path-traversal surface here: callers cannot influence the path beyond
picking which validated extension applies.
"""

from pathlib import Path

from bson import ObjectId

from app.core.config import settings

STORAGE_ROOT = Path(settings.storage_root)
GUIDELINES_DIR = STORAGE_ROOT / "guidelines"
ASSETS_DIR = STORAGE_ROOT / "assets"
SUBMISSIONS_DIR = STORAGE_ROOT / "submissions"


def ensure_storage_dirs() -> None:
    GUIDELINES_DIR.mkdir(parents=True, exist_ok=True)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    SUBMISSIONS_DIR.mkdir(parents=True, exist_ok=True)


def guideline_pdf_path(doc_id: ObjectId) -> Path:
    return GUIDELINES_DIR / f"{doc_id}.pdf"


def submission_pdf_path(revision_id: ObjectId) -> Path:
    # Keyed by revision id (not submission id): each revision is immutable
    # once created, so a PDF-sourced revision's original file stays matched
    # to the exact snapshot it produced.
    return SUBMISSIONS_DIR / f"{revision_id}.pdf"


def asset_file_path(asset_id: ObjectId, extension: str) -> Path:
    return ASSETS_DIR / f"{asset_id}{extension}"


def submission_image_path(revision_id: ObjectId, extension: str) -> Path:
    # Same SUBMISSIONS_DIR as submission_pdf_path -- no collision since a
    # revision is either PDF- or image-sourced, never both, and extensions
    # differ.
    return SUBMISSIONS_DIR / f"{revision_id}{extension}"


# Shared PNG/JPEG signature sniffing -- used for every image upload/serve
# in the app (brand assets, now submission images too). Never trusts
# filename or client-supplied Content-Type, in either direction.
IMAGE_SIGNATURES: tuple[tuple[bytes, str, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", ".png", "image/png"),
    (b"\xff\xd8\xff", ".jpg", "image/jpeg"),
)


def sniff_image_type(content: bytes) -> tuple[str, str] | None:
    """Returns (extension, content_type) if `content` starts with a known
    PNG/JPEG signature, else None."""
    for magic, ext, content_type in IMAGE_SIGNATURES:
        if content.startswith(magic):
            return ext, content_type
    return None


def write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def delete_if_exists(path: Path) -> None:
    path.unlink(missing_ok=True)
