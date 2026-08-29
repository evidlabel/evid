"""resolve_source must keep binary PDFs even when Content-Type is not application/pdf."""

from unittest.mock import patch

import requests

from evid.services.doc_ingester import resolve_source

_URL = (
    "https://billeder.aeldresagen.dk/cdndownload/2yJov2nhe0mA/"
    "udspil-beredskab-aeldre-sagen-2026.pdf"
)
_PDF_BODY = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n"


def _response(
    content: bytes,
    content_type: str,
    *,
    disposition: str | None = None,
) -> requests.Response:
    r = requests.models.Response()
    r.status_code = 200
    r._content = content
    r.headers["Content-Type"] = content_type
    if disposition:
        r.headers["Content-Disposition"] = disposition
    r.url = _URL
    return r


def test_octet_stream_pdf_is_saved_as_pdf():
    """CDNs often send application/octet-stream for a downloadable PDF."""
    resp = _response(
        _PDF_BODY,
        "application/octet-stream",
        disposition="attachment; filename=udspil-beredskab-aeldre-sagen-2026.pdf",
    )
    with patch("requests.get", return_value=resp):
        resolved = resolve_source(_URL)
    try:
        assert resolved.pdf_path.read_bytes() == _PDF_BODY
        assert resolved.pdf_path.suffix.lower() == ".pdf"
        assert resolved.source_url == _URL
    finally:
        if resolved.temp_dir is not None:
            resolved.temp_dir.cleanup()
