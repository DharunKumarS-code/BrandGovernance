"""PyMuPDF-based guideline PDF extraction and page-based chunking.

Chunking targets ~800-1200 characters per chunk with a small overlap between
consecutive chunks of the same page, so a chunk near a page's end still
carries a little of the preceding context. Chunk indices reset per page;
page numbers are preserved as 1-indexed to match how a human would cite them.
"""

import fitz  # PyMuPDF

CHUNK_TARGET_MIN = 800
CHUNK_TARGET_MAX = 1200
CHUNK_OVERLAP = 150

# A demo guideline document has no business being thousands of pages long;
# this also keeps the fully-synchronous extract->chunk->insert pipeline
# below bounded and fast within a single request.
MAX_PAGE_COUNT = 50


class PdfProcessingError(ValueError):
    """Raised when a PDF cannot be opened or read."""


def extract_pages(pdf_bytes: bytes) -> list[tuple[int, str]]:
    """Returns [(page_number, text), ...], 1-indexed. Pages with no
    extractable text come back with an empty string rather than failing
    the whole document."""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        raise PdfProcessingError(f"Unable to open PDF: {exc}") from exc

    # PyMuPDF opens an encrypted/password-protected PDF's container
    # successfully even without a password -- it just returns empty text
    # for every page. Left unchecked, that silently produces a "ready"
    # document with zero chunks and no indication anything went wrong
    # (found in the Phase 3 security audit, reproduced directly). Reject it
    # explicitly instead.
    if doc.is_encrypted or doc.needs_pass:
        doc.close()
        raise PdfProcessingError(
            "PDF is encrypted or password-protected and cannot be processed. "
            "Please upload an unprotected PDF."
        )

    if doc.page_count == 0:
        doc.close()
        raise PdfProcessingError("PDF has no pages.")

    if doc.page_count > MAX_PAGE_COUNT:
        page_count = doc.page_count
        doc.close()
        raise PdfProcessingError(
            f"PDF has {page_count} pages, which exceeds the {MAX_PAGE_COUNT}-page limit "
            f"for guideline documents."
        )

    pages: list[tuple[int, str]] = []
    try:
        for index in range(doc.page_count):
            try:
                text = doc.load_page(index).get_text("text") or ""
            except Exception:
                text = ""
            pages.append((index + 1, text))
    finally:
        doc.close()
    return pages


def chunk_text(
    text: str,
    target_min: int = CHUNK_TARGET_MIN,
    target_max: int = CHUNK_TARGET_MAX,
    overlap: int = CHUNK_OVERLAP,
) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= target_max:
        return [text]

    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + target_max, n)
        if end < n:
            # Prefer breaking on whitespace so we don't split mid-word.
            break_point = text.rfind(" ", start + target_min, end)
            if break_point != -1:
                end = break_point
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= n:
            break
        start = max(end - overlap, start + 1)  # always make forward progress
    return chunks


def extract_and_chunk(pdf_bytes: bytes) -> tuple[list[dict], int]:
    """Returns (chunks, page_count). Each chunk dict has page, chunk_index, text."""
    pages = extract_pages(pdf_bytes)
    chunks: list[dict] = []
    for page_num, text in pages:
        for idx, piece in enumerate(chunk_text(text)):
            chunks.append({"page": page_num, "chunk_index": idx, "text": piece})
    return chunks, len(pages)
