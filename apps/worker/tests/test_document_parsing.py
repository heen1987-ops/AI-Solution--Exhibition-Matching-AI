"""Tests for apps/worker/worker/jobs/document_parsing.py.

All sample documents are constructed in-memory in this file - no external
fixtures - per this track's own test spec. DOCX is hand-assembled at the XML
level (the parser reads `word/document.xml` directly, no python-docx
dependency - see the module docstring). XLSX and PDF are built as real,
structurally valid packages (a proper xref/trailer for PDF; a proper
[Content_Types].xml/_rels package for XLSX) because this module now parses
them with real libraries (`openpyxl`/`pypdf`) rather than the hand-rolled
stdlib readers the standalone-worktree original used - see the "regression"
section below for the two bugs the merge audit found in those hand-rolled
readers and the tests that would have caught them.
"""

from __future__ import annotations

import io
import zipfile
import zlib

import openpyxl
import pytest

from worker.jobs.document_parsing import (
    DocumentFormat,
    InMemorySegmentStore,
    ParseStatus,
    PiiType,
    handle_parse_document_job,
    mask_pii,
    parse_document,
    register_document_parsing_job,
)

# ---------------------------------------------------------------------------
# Sample document builders
# ---------------------------------------------------------------------------


def _build_pdf(objects: list[bytes]) -> bytes:
    """Assemble a minimal but *structurally valid* PDF: a real xref table and
    trailer, computed from real byte offsets - `pypdf` (unlike the old hand-rolled
    stdlib scanner) requires a `startxref` to be present at all, even in
    non-strict mode."""

    header = b"%PDF-1.4\n"
    buf = bytearray(header)
    offsets = [0]
    for i, body in enumerate(objects, start=1):
        offsets.append(len(buf))
        buf += f"{i} 0 obj\n".encode("ascii") + body + b"\nendobj\n"
    xref_offset = len(buf)
    n = len(objects) + 1
    buf += f"xref\n0 {n}\n".encode("ascii")
    buf += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        buf += f"{off:010d} 00000 n \n".encode("ascii")
    buf += (
        f"trailer\n<< /Size {n} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF"
    ).encode("ascii")
    return bytes(buf)


def _pdf_page_objects(content_stream_obj: bytes, *, with_font: bool = True) -> list[bytes]:
    resources = b"/Resources << /Font << /F1 5 0 R >> >>" if with_font else b"/Resources << >>"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 4 0 R " + resources + b" >>"
        ),
        content_stream_obj,
    ]
    if with_font:
        objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    return objects


def _build_pdf_with_text(text: str) -> bytes:
    content_stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
    content_obj = (
        b"<< /Length " + str(len(content_stream)).encode("ascii") + b" >>\nstream\n"
        + content_stream
        + b"\nendstream"
    )
    return _build_pdf(_pdf_page_objects(content_obj))


def _build_pdf_with_flate_hex_tj(text: str) -> bytes:
    """A content stream compressed with /FlateDecode, using a hex string (`<...> Tj`)
    rather than a literal string (`(...) Tj`) - the shape the old hand-rolled parser could
    not decode at all (it only matched literal-string Tj/TJ operators), which is exactly
    why it misclassified real producer output as OCR_REQUIRED. See
    TestPdfRegressions below."""

    raw = f"BT /F1 12 Tf 72 720 Td <{text.encode('latin-1').hex()}> Tj ET".encode("latin-1")
    compressed = zlib.compress(raw)
    content_obj = (
        b"<< /Length " + str(len(compressed)).encode("ascii") + b" /Filter /FlateDecode >>"
        b"\nstream\n" + compressed + b"\nendstream"
    )
    return _build_pdf(_pdf_page_objects(content_obj))


def _build_scanned_pdf() -> bytes:
    """A structurally valid PDF whose only content stream draws an image
    XObject - no Tj/TJ text operators anywhere, i.e. what a scanned page
    looks like."""

    image_bytes = b"\x00\x00\x00\x00"
    content_stream = b"q 612 0 0 792 0 0 cm /Im1 Do Q"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 4 0 R /Resources << /XObject << /Im1 5 0 R >> >> >>"
        ),
        (
            b"<< /Length " + str(len(content_stream)).encode("ascii") + b" >>\nstream\n"
            + content_stream
            + b"\nendstream"
        ),
        (
            b"<< /Type /XObject /Subtype /Image /Width 1 /Height 1 "
            b"/ColorSpace /DeviceGray /BitsPerComponent 8 /Length 4 >>\nstream\n"
            + image_bytes
            + b"\nendstream"
        ),
    ]
    return _build_pdf(objects)


_DOCX_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _build_docx(paragraphs: list[str]) -> bytes:
    body = "".join(
        f'<w:p><w:r><w:t xml:space="preserve">{p}</w:t></w:r></w:p>' for p in paragraphs
    )
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{_DOCX_NS}"><w:body>{body}</w:body></w:document>'
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", document_xml)
    return buffer.getvalue()


def _build_xlsx_via_openpyxl(sheets: dict[str, list[list[object]]]) -> bytes:
    """Build a real .xlsx package with openpyxl - the tool under test's own dependency -
    so these fixtures exercise a genuine OOXML package rather than a hand-approximated
    one. openpyxl writes sheets sequentially as sheet1.xml, sheet2.xml, ... in creation
    order, which is exactly what reproduces the historical lexicographic-sort bug once a
    workbook has 10+ sheets (see TestXlsxRegressions)."""

    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)
    for name, rows in sheets.items():
        sheet = workbook.create_sheet(title=name)
        for row in rows:
            sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _build_xlsx_with_inline_strings() -> bytes:
    """A minimal, hand-built OOXML package using `t="inlineStr"` cells (`<is><t>...</t>
    </is>`) instead of the shared-strings table `openpyxl.Workbook.save()` always uses -
    the old hand-rolled parser only ever special-cased `t="s"` (shared-string) cells and
    had no branch for inline strings at all, so it silently dropped them while still
    reporting ParseStatus.SUCCEEDED. See TestXlsxRegressions."""

    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<worksheet xmlns="{ns}"><sheetData>'
        '<row r="1">'
        '<c r="A1" t="inlineStr"><is><t>Name</t></is></c>'
        '<c r="B1" t="inlineStr"><is><t>Phone</t></is></c>'
        "</row>"
        '<row r="2">'
        '<c r="A2" t="inlineStr"><is><t>Alice</t></is></c>'
        '<c r="B2" t="inlineStr"><is><t>010-1234-5678</t></is></c>'
        "</row>"
        "</sheetData></worksheet>"
    )
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<workbook xmlns="{ns}" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="People" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        "</Types>"
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        "</Relationships>"
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        "</Relationships>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_rels)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pdf_extraction_returns_page_segment_with_text() -> None:
    result = await parse_document(_build_pdf_with_text("Hello World"), filename="brochure.pdf")

    assert result.status == ParseStatus.SUCCEEDED
    assert result.document_format == DocumentFormat.PDF
    assert len(result.segments) == 1
    assert result.segments[0].section_label == "page:1"
    assert result.segments[0].text == "Hello World"
    assert result.segments[0].start_offset == 0
    assert result.segments[0].end_offset == len("Hello World")


@pytest.mark.asyncio
async def test_scanned_pdf_is_classified_ocr_required_not_retried() -> None:
    result = await parse_document(_build_scanned_pdf(), filename="scan.pdf")

    assert result.status == ParseStatus.OCR_REQUIRED
    assert result.segments == ()


@pytest.mark.asyncio
async def test_corrupted_pdf_fails_gracefully() -> None:
    result = await parse_document(b"this is not a real pdf file at all", filename="broken.pdf")

    assert result.status == ParseStatus.PROCESSING_FAILED
    assert result.warnings
    assert result.segments == ()


@pytest.mark.asyncio
async def test_pdf_with_missing_xref_fails_gracefully_not_ocr_required() -> None:
    """A PDF with the right magic bytes but no real xref/startxref (structurally
    incomplete, not merely image-only) must be reported as PROCESSING_FAILED, distinct
    from a genuinely scanned page."""

    broken = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF"
    result = await parse_document(broken, filename="incomplete.pdf")

    assert result.status == ParseStatus.PROCESSING_FAILED


class TestPdfRegressions:
    """Regression coverage for the empirically-demonstrated hand-rolled PdfTextParser
    defect the merge audit found: it never decoded hex-string (`<...> Tj`) text-showing
    operators, only literal strings, so any Flate-compressed hex-encoded content stream -
    normal output from many real PDF producers, not a contrived edge case - was invisible
    to it and misclassified as OCR_REQUIRED with zero segments."""

    @pytest.mark.asyncio
    async def test_flate_compressed_hex_string_tj_stream_is_extracted(self) -> None:
        result = await parse_document(
            _build_pdf_with_flate_hex_tj("Compressed Hello"), filename="compressed.pdf"
        )

        assert result.status == ParseStatus.SUCCEEDED
        assert len(result.segments) == 1
        assert result.segments[0].text == "Compressed Hello"


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_docx_extraction_returns_paragraph_segments() -> None:
    docx_bytes = _build_docx(["Booth introduction", "Contact hong@example.com for details"])

    result = await parse_document(docx_bytes, filename="intro.docx")

    assert result.status == ParseStatus.SUCCEEDED
    assert result.document_format == DocumentFormat.DOCX
    assert [seg.section_label for seg in result.segments] == ["paragraph:1", "paragraph:2"]
    assert result.segments[0].text == "Booth introduction"
    assert "[MASKED_EMAIL]" in result.segments[1].text
    assert "hong@example.com" not in result.segments[1].text


@pytest.mark.asyncio
async def test_corrupted_docx_fails_gracefully() -> None:
    result = await parse_document(b"not actually a zip", filename="broken.docx")

    assert result.status == ParseStatus.PROCESSING_FAILED
    assert result.segments == ()


# ---------------------------------------------------------------------------
# XLSX
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_xlsx_extraction_returns_row_segments_and_masks_pii() -> None:
    content = _build_xlsx_via_openpyxl(
        {"People": [["Name"], ["Alice", "010-1234-5678"]]}
    )

    result = await parse_document(content, filename="contacts.xlsx")

    assert result.status == ParseStatus.SUCCEEDED
    assert result.document_format == DocumentFormat.XLSX
    labels = [seg.section_label for seg in result.segments]
    assert labels == ["sheet:People:row:1", "sheet:People:row:2"]
    assert result.segments[0].text == "Name"
    assert "[MASKED_PHONE]" in result.segments[1].text
    assert "010-1234-5678" not in result.segments[1].text


@pytest.mark.asyncio
async def test_corrupted_xlsx_fails_gracefully() -> None:
    result = await parse_document(b"\x00\x01broken", filename="broken.xlsx")

    assert result.status == ParseStatus.PROCESSING_FAILED
    assert result.segments == ()


@pytest.mark.asyncio
async def test_oversized_xlsx_is_unsupported_not_processing_failed() -> None:
    from worker.jobs.document_parsing import MAX_XLSX_BYTES

    oversized = b"PK" + b"\x00" * (MAX_XLSX_BYTES + 1)
    result = await parse_document(oversized, filename="huge.xlsx")

    assert result.status == ParseStatus.UNSUPPORTED_DOCUMENT


class TestXlsxRegressions:
    """Regression coverage for the two empirically-demonstrated defects the merge audit
    found in the hand-rolled stdlib XlsxParser it replaced."""

    @pytest.mark.asyncio
    async def test_inline_string_cells_are_not_silently_dropped(self) -> None:
        result = await parse_document(
            _build_xlsx_with_inline_strings(), filename="inline.xlsx"
        )

        assert result.status == ParseStatus.SUCCEEDED
        assert len(result.segments) == 2
        assert result.segments[0].text == "Name, Phone"
        assert "Alice" in result.segments[1].text
        assert "[MASKED_PHONE]" in result.segments[1].text

    @pytest.mark.asyncio
    async def test_eleven_sheet_workbook_labels_every_sheet_by_its_real_name(self) -> None:
        """openpyxl physically writes sheets as sheet1.xml..sheet11.xml in creation
        order - lexicographically sorting those filenames as strings (the old parser's
        approach) would place "sheet10.xml"/"sheet11.xml" ahead of "sheet2.xml", which is
        exactly the bug that mislabeled the 10th sheet's content as belonging to the 2nd."""

        sheets = {f"S{i:02d}": [[f"marker-{i:02d}"]] for i in range(1, 12)}
        content = _build_xlsx_via_openpyxl(sheets)

        result = await parse_document(content, filename="eleven-sheets.xlsx")

        assert result.status == ParseStatus.SUCCEEDED
        by_label = {seg.section_label: seg.text for seg in result.segments}
        for i in range(1, 12):
            label = f"sheet:S{i:02d}:row:1"
            assert by_label[label] == f"marker-{i:02d}", (
                f"sheet S{i:02d} must report its own marker, not another sheet's "
                f"(got {by_label.get(label)!r})"
            )


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_csv_extraction_returns_row_segments() -> None:
    csv_bytes = b"name,phone\nHong Gildong,010-9876-5432\n"

    result = await parse_document(csv_bytes, filename="visitors.csv")

    assert result.status == ParseStatus.SUCCEEDED
    assert result.document_format == DocumentFormat.CSV
    assert result.segments[0].text == "name, phone"
    assert "[MASKED_PHONE]" in result.segments[1].text


# ---------------------------------------------------------------------------
# Plain text
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plain_text_extraction_splits_paragraphs() -> None:
    text_bytes = b"First paragraph.\n\nSecond paragraph."

    result = await parse_document(text_bytes, filename="notes.txt")

    assert result.status == ParseStatus.SUCCEEDED
    assert result.document_format == DocumentFormat.PLAIN_TEXT
    assert [seg.text for seg in result.segments] == ["First paragraph.", "Second paragraph."]


# ---------------------------------------------------------------------------
# Empty document
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content,filename",
    [
        (b"", "empty.txt"),
        (b"   \n  \n", "whitespace.csv"),
    ],
)
async def test_empty_document_returns_empty_status(content: bytes, filename: str) -> None:
    result = await parse_document(content, filename=filename)

    assert result.status == ParseStatus.EMPTY
    assert result.segments == ()


# ---------------------------------------------------------------------------
# PII masking
# ---------------------------------------------------------------------------


def test_mask_pii_detects_email_phone_rrn_and_account_number() -> None:
    sample = (
        "Reach Hong Gildong at hong@example.com or 010-1234-5678. "
        "RRN 901231-1234567 and account 110-234-567890 on file."
    )

    masking = mask_pii(sample)

    assert "hong@example.com" not in masking.masked_text
    assert "010-1234-5678" not in masking.masked_text
    assert "901231-1234567" not in masking.masked_text
    assert "110-234-567890" not in masking.masked_text

    types_found = {m.pii_type for m in masking.matches}
    assert types_found == {
        PiiType.EMAIL,
        PiiType.PHONE,
        PiiType.RESIDENT_REGISTRATION_NUMBER,
        PiiType.ACCOUNT_NUMBER,
    }

    # Offsets refer to the *original* text and round-trip back to the match.
    for match in masking.matches:
        assert sample[match.start : match.end]


def test_mask_pii_is_a_no_op_on_clean_text() -> None:
    masking = mask_pii("일반 텍스트, 개인정보 없음.")

    assert masking.masked_text == "일반 텍스트, 개인정보 없음."
    assert masking.matches == ()


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reparsing_same_content_and_version_does_not_duplicate_segments() -> None:
    store = InMemorySegmentStore()
    content = _build_pdf_with_text("Idempotent Hello")

    first = await parse_document(content, filename="brochure.pdf", store=store)
    second = await parse_document(content, filename="brochure.pdf", store=store)

    assert first.from_cache is False
    assert second.from_cache is True
    assert first.segments == second.segments
    assert len(store._results) == 1  # white-box check on the in-memory reference store


@pytest.mark.asyncio
async def test_different_parser_version_reparses_independently() -> None:
    store = InMemorySegmentStore()
    content = _build_pdf_with_text("Version Check")

    first = await parse_document(content, filename="brochure.pdf", store=store, parser_version="v1")
    second = await parse_document(content, filename="brochure.pdf", store=store, parser_version="v2")

    assert first.from_cache is False
    assert second.from_cache is False
    assert len(store._results) == 2


# ---------------------------------------------------------------------------
# Job registration hook
# ---------------------------------------------------------------------------


class _FakeRegistry:
    def __init__(self) -> None:
        self.registered: dict[str, object] = {}

    def register(self, name: str, handler: object) -> None:
        self.registered[name] = handler


def test_register_document_parsing_job_registers_handler() -> None:
    registry = _FakeRegistry()

    register_document_parsing_job(registry)

    assert registry.registered["document_parsing"] is handle_parse_document_job


@pytest.mark.asyncio
async def test_handle_parse_document_job_delegates_to_parse_document() -> None:
    store = InMemorySegmentStore()
    payload = {"content": _build_pdf_with_text("Job Payload"), "filename": "job.pdf"}

    result = await handle_parse_document_job(payload, store=store)

    assert result.status == ParseStatus.SUCCEEDED
    assert result.segments[0].text == "Job Payload"


@pytest.mark.asyncio
async def test_handle_parse_document_job_rejects_non_bytes_content() -> None:
    store = InMemorySegmentStore()

    with pytest.raises(TypeError):
        await handle_parse_document_job({"content": "not bytes"}, store=store)
