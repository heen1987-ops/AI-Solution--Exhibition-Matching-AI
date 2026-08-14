"""document_parsing job.

Parses an uploaded exhibitor document (PDF, DOCX, XLSX, CSV, plain text) into
page/sheet/section-segmented text with character offsets, and masks likely
PII (phone numbers, emails, personal addresses, resident-registration-number
-shaped strings, account-number-shaped strings) *before* the text is allowed
to reach any AI step, per AGENTS.md invariant 6 (privacy is not a later
add-on) and the top-level harness rule "never write personal data into logs,
fixtures, or snapshots".

XLSX and PDF now use real libraries (unified-repo port note)
----------------------------------------------------------------
The standalone-worktree original of this module hand-rolled its XLSX and PDF parsers on
stdlib `zipfile`/`xml.etree.ElementTree`/`re`/`zlib` alone, on the documented premise that
the shared venv had no `openpyxl`/`pypdf` installed. That premise no longer holds in the
unified repo (`openpyxl` is already an `apps/api` runtime dependency with a 511-line
production reader at `apps/api/app/services/excel_import.py`, and `pypdf` has been added
alongside it here - see `apps/worker/pyproject.toml`). The hand-rolled `XlsxParser` and
`PdfTextParser` were also empirically unfit, not just unnecessary: the merge audit that
authorized this replacement executed them and found the XLSX parser reports `SUCCEEDED`
while silently dropping every `inlineStr` cell (it only special-cased shared-string cells)
and mislabels sheets from the 10th onward because it lexicographically sorts
`xl/worksheets/sheetN.xml` filenames as strings (`"sheet10.xml" < "sheet2.xml"`); the PDF
parser returned `OCR_REQUIRED` with zero segments against a Flate-compressed hex-string
`Tj` content stream it could not decode. Both are replaced below with `openpyxl`/`pypdf`
- see `worker/tests/test_document_parsing.py` for the regression tests the audit's findings
became. `DocxParser` (unaffected by either finding) is kept exactly as it was: a real
python-docx dependency was judged unnecessary just to keep reading `<w:t>` run text out of
`word/document.xml`.

Idempotency
-----------
`parse_document()` keys results by `(content_hash, parser_version)`. A `SegmentStore`
Protocol abstracts persistence; `InMemorySegmentStore` is the reference implementation used
by this track's own tests. Both are `async` here (unlike the standalone-worktree original)
because this repo has no synchronous SQLAlchemy engine to implement a sync Protocol
against - see `worker/jobs/analytics_aggregation.py`'s module docstring for the same
reasoning applied to `MetricSink`. A future migration + repository class can implement
`SegmentStore` against a real table without changing this module's public contract.
"""

from __future__ import annotations

import hashlib
import io
import logging
import re
import zipfile
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable
from xml.etree import ElementTree as ET

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException
from pypdf import PdfReader
from pypdf.errors import PdfReadError

PARSER_VERSION = "document-parsing/2.0.0"

logger = logging.getLogger("worker.jobs.document_parsing")


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class DocumentFormat(str, Enum):
    PDF = "PDF"
    DOCX = "DOCX"
    XLSX = "XLSX"
    CSV = "CSV"
    PLAIN_TEXT = "PLAIN_TEXT"


class ParseStatus(str, Enum):
    #: Text was extracted (possibly zero segments if the source truly has no
    #: body content, e.g. a header-only CSV - see EMPTY for the "nothing at
    #: all" case).
    SUCCEEDED = "SUCCEEDED"
    #: The file parsed structurally (valid PDF object stream) but no
    #: extractable text was found anywhere in it - almost always a scanned/
    #: image-only PDF. Per this track's spec: classify once, do not retry.
    OCR_REQUIRED = "OCR_REQUIRED"
    #: The input had no content at all (zero bytes, or a CSV/plain-text file
    #: containing only whitespace).
    EMPTY = "EMPTY"
    #: The file could not be parsed as its declared/detected format (bad
    #: zip, bad PDF header, unreadable encoding, ...). This must never raise
    #: out of parse_document() - it is a terminal, reportable state.
    PROCESSING_FAILED = "PROCESSING_FAILED"
    #: A best-effort parser recognized the format but could not confidently
    #: extract structured text (reserved for future stub parsers; none of
    #: the five implementations below currently return this, they either
    #: succeed or fail explicitly - kept for forward compatibility per the
    #: track spec's "MANUAL_TEXT_REQUIRED fallback" requirement).
    MANUAL_TEXT_REQUIRED = "MANUAL_TEXT_REQUIRED"
    #: The file exceeded a size/entry-count/expansion guard (see
    #: `_validate_xlsx_archive`) - a distinct, non-retryable terminal state from a
    #: structurally-corrupt file, so an operator can tell "too big" from "broken" at a
    #: glance.
    UNSUPPORTED_DOCUMENT = "UNSUPPORTED_DOCUMENT"


class PiiType(str, Enum):
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    RESIDENT_REGISTRATION_NUMBER = "RESIDENT_REGISTRATION_NUMBER"
    ACCOUNT_NUMBER = "ACCOUNT_NUMBER"


# ---------------------------------------------------------------------------
# PII masking
# ---------------------------------------------------------------------------
#
# Regex-based, MVP-level detection only. Documented false-negative risk (per
# this track's spec, "good enough for MVP, document the false-negative
# risk"):
#   - EMAIL: misses obfuscated forms ("name at domain dot com"), unicode/IDN
#     domains, and addresses without a `.`-delimited TLD.
#   - PHONE: only matches Korean landline/mobile shapes (0XX-XXXX-XXXX and
#     010-XXXX-XXXX with optional dashes/spaces); misses +82 international
#     prefix, spelled-out numbers, and non-Korean numbers.
#   - RESIDENT_REGISTRATION_NUMBER: matches the YYMMDD-GSSSSNC *shape*
#     (6 digits, dash, 7 digits starting 1-8) only - does NOT validate the
#     official checksum digit, so it will both miss checksum-invalid real
#     numbers typed with a typo and mask some checksum-invalid numbers that
#     merely look like one (safe direction: over-masking, not under-masking).
#   - ACCOUNT_NUMBER: bank account numbers have no single canonical shape in
#     Korea; this uses a generic "8-16 digits, optionally dash-grouped, not
#     already claimed by a phone/RRN match" heuristic, which will both miss
#     account numbers that happen to look like phone numbers (rare) and
#     occasionally mask unrelated long digit runs (order numbers, invoice
#     numbers). Given the "unknown stays unknown" / privacy-first invariant
#     in AGENTS.md, over-masking is the accepted tradeoff for MVP.
#
# Matches are resolved in priority order (EMAIL, RRN, PHONE, ACCOUNT_NUMBER)
# and later patterns skip any span already claimed by an earlier match, so a
# single digit run is only ever masked once.

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_RRN_RE = re.compile(r"(?<!\d)\d{6}[-\s]?[1-8]\d{6}(?!\d)")
_PHONE_RE = re.compile(r"(?<!\d)0\d{1,2}[-\s]?\d{3,4}[-\s]?\d{4}(?!\d)")
_ACCOUNT_RE = re.compile(r"(?<!\d)(?:\d[-\s]?){8,16}(?!\d)")

_PII_PATTERNS: tuple[tuple[PiiType, re.Pattern[str]], ...] = (
    (PiiType.EMAIL, _EMAIL_RE),
    (PiiType.RESIDENT_REGISTRATION_NUMBER, _RRN_RE),
    (PiiType.PHONE, _PHONE_RE),
    (PiiType.ACCOUNT_NUMBER, _ACCOUNT_RE),
)


@dataclass(frozen=True)
class PiiMatch:
    pii_type: PiiType
    start: int
    end: int
    masked_value: str


@dataclass(frozen=True)
class MaskingResult:
    masked_text: str
    matches: tuple[PiiMatch, ...]


def _mask_placeholder(pii_type: PiiType) -> str:
    return f"[MASKED_{pii_type.value}]"


def mask_pii(text: str) -> MaskingResult:
    """Detect and mask PII-shaped substrings in ``text``.

    Returns the masked text plus the list of matches (offsets are relative
    to the *original* ``text``, not the masked output - useful for audit
    without ever storing the raw match itself).
    """

    if not text:
        return MaskingResult(masked_text=text, matches=())

    claimed: list[tuple[int, int]] = []
    matches: list[PiiMatch] = []

    def _overlaps(start: int, end: int) -> bool:
        return any(start < c_end and end > c_start for c_start, c_end in claimed)

    for pii_type, pattern in _PII_PATTERNS:
        for m in pattern.finditer(text):
            start, end = m.start(), m.end()
            if _overlaps(start, end):
                continue
            claimed.append((start, end))
            matches.append(
                PiiMatch(
                    pii_type=pii_type,
                    start=start,
                    end=end,
                    masked_value=_mask_placeholder(pii_type),
                )
            )

    if not matches:
        return MaskingResult(masked_text=text, matches=())

    matches.sort(key=lambda m: m.start)
    pieces: list[str] = []
    cursor = 0
    for m in matches:
        pieces.append(text[cursor : m.start])
        pieces.append(m.masked_value)
        cursor = m.end
    pieces.append(text[cursor:])
    return MaskingResult(masked_text="".join(pieces), matches=tuple(matches))


# ---------------------------------------------------------------------------
# Segments / parse result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TextSegment:
    """One page / sheet+row / paragraph / row-level chunk of extracted text.

    ``start_offset``/``end_offset`` are character offsets of this segment's
    *masked* text within the document-level concatenated text (segments
    joined with ``"\\n"``, in emission order) - i.e. offsets a downstream
    consumer can use to re-locate a segment inside the full extracted
    document without re-parsing the original file.
    """

    segment_index: int
    section_label: str
    text: str
    start_offset: int
    end_offset: int
    pii_matches: tuple[PiiMatch, ...] = ()


@dataclass(frozen=True)
class ParseResult:
    status: ParseStatus
    document_format: DocumentFormat
    content_hash: str
    parser_version: str
    segments: tuple[TextSegment, ...] = ()
    warnings: tuple[str, ...] = ()
    from_cache: bool = False


def _segments_from_texts(
    labeled_texts: list[tuple[str, str]],
) -> tuple[TextSegment, ...]:
    """Turn ``[(section_label, raw_text), ...]`` into masked, offset TextSegments."""

    segments: list[TextSegment] = []
    cursor = 0
    for index, (label, raw_text) in enumerate(labeled_texts):
        masking = mask_pii(raw_text)
        start = cursor
        end = start + len(masking.masked_text)
        segments.append(
            TextSegment(
                segment_index=index,
                section_label=label,
                text=masking.masked_text,
                start_offset=start,
                end_offset=end,
                pii_matches=masking.matches,
            )
        )
        cursor = end + 1  # +1 for the joining "\n" a consumer would insert
    return tuple(segments)


# ---------------------------------------------------------------------------
# DocumentParser protocol
# ---------------------------------------------------------------------------


class DocumentParseError(Exception):
    """Raised by a parser's internal extraction step; always caught by
    parse_document() and converted into ParseStatus.PROCESSING_FAILED - a
    corrupted document must fail gracefully, never crash the worker."""


class UnsupportedDocumentError(Exception):
    """Raised when a document fails an input guard (size/entry-count/expansion) before any
    real parsing is attempted - caught by parse_document() and converted into
    ParseStatus.UNSUPPORTED_DOCUMENT (distinct from PROCESSING_FAILED: this document was
    never structurally examined at all, so "too big" is reported as its own terminal state
    rather than looking like corruption)."""


@runtime_checkable
class DocumentParser(Protocol):
    """A parser for one document format.

    ``extract`` does the real work and may raise ``DocumentParseError`` (or
    let a stdlib exception propagate) on malformed input - ``parse_document``
    is the only public entry point and is responsible for catching those and
    mapping them to ``ParseStatus.PROCESSING_FAILED``.
    """

    format: DocumentFormat

    def extract(self, content: bytes) -> list[tuple[str, str]]:
        """Return ``[(section_label, raw_text), ...]`` in document order.

        An empty list means "structurally valid, no body text" (caller
        decides EMPTY vs SUCCEEDED-with-zero-segments); raise
        DocumentParseError for anything that looks corrupted.
        """
        ...


class PlainTextParser:
    format = DocumentFormat.PLAIN_TEXT

    def extract(self, content: bytes) -> list[tuple[str, str]]:
        text = _decode_best_effort(content)
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text)]
        paragraphs = [p for p in paragraphs if p]
        return [(f"section:{i + 1}", p) for i, p in enumerate(paragraphs)]


class CsvParser:
    format = DocumentFormat.CSV

    def extract(self, content: bytes) -> list[tuple[str, str]]:
        import csv

        text = _decode_best_effort(content)
        if not text.strip():
            return []

        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel

        reader = csv.reader(io.StringIO(text), dialect=dialect)
        rows: list[tuple[str, str]] = []
        for row_number, row in enumerate(reader, start=1):
            if not any(cell.strip() for cell in row):
                continue
            rows.append((f"row:{row_number}", ", ".join(cell.strip() for cell in row)))
        return rows


_DOCX_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


class DocxParser:
    """Reads the OOXML `word/document.xml` part directly (DOCX is a ZIP of
    XML parts) instead of depending on python-docx - kept exactly as in the standalone-
    worktree original (see module docstring "XLSX and PDF now use real libraries"): the
    merge audit found no correctness defect in this parser, only in XlsxParser/
    PdfTextParser, so a real python-docx dependency was judged unnecessary here.
    Limitation: only `<w:t>` run text is extracted - text boxes, headers/footers,
    footnotes, and tables-as-drawings are not walked (documented best-effort scope, not a
    crash risk)."""

    format = DocumentFormat.DOCX

    def extract(self, content: bytes) -> list[tuple[str, str]]:
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                xml_bytes = archive.read("word/document.xml")
        except (zipfile.BadZipFile, KeyError) as exc:
            raise DocumentParseError(f"invalid DOCX package: {exc}") from exc

        try:
            root = ET.fromstring(xml_bytes)
        except ET.ParseError as exc:
            raise DocumentParseError(f"invalid DOCX document.xml: {exc}") from exc

        paragraphs: list[tuple[str, str]] = []
        for index, p in enumerate(root.iter(f"{{{_DOCX_NS['w']}}}p")):
            runs = p.findall(f".//{{{_DOCX_NS['w']}}}t")
            text = "".join(run.text or "" for run in runs).strip()
            if text:
                paragraphs.append((f"paragraph:{index + 1}", text))
        return paragraphs


# --- XLSX (openpyxl) --------------------------------------------------------
#
# Reuses the same guard values apps/api/app/services/excel_import.py:123-159
# established for the exhibitor XLSX import endpoint (5MiB compressed / 25MiB
# uncompressed / <=1000 archive entries / no ../ traversal / no VBA macro project) -
# this worker has no operator-facing upload-size UI of its own to base a different limit
# on, and reusing a value the security review already accepted is safer than inventing a
# new one.

MAX_XLSX_BYTES = 5 * 1024 * 1024
MAX_XLSX_UNCOMPRESSED_BYTES = 25 * 1024 * 1024
MAX_XLSX_ARCHIVE_ENTRIES = 1_000


def _validate_xlsx_archive(data: bytes) -> None:
    if not data or len(data) > MAX_XLSX_BYTES:
        raise UnsupportedDocumentError("XLSX content must be 1 byte to 5MiB")
    if not data.startswith(b"PK"):
        raise DocumentParseError("not a valid .xlsx package")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_XLSX_ARCHIVE_ENTRIES:
                raise UnsupportedDocumentError("XLSX archive entry count exceeds the limit")
            if any(".." in info.filename.replace("\\", "/").split("/") for info in infos):
                raise DocumentParseError("XLSX archive contains an invalid path")
            if any(info.filename.lower().endswith("vbaproject.bin") for info in infos):
                raise DocumentParseError("macro-enabled XLSX packages are not allowed")
            if sum(info.file_size for info in infos) > MAX_XLSX_UNCOMPRESSED_BYTES:
                raise UnsupportedDocumentError("XLSX uncompressed size exceeds the limit")
    except zipfile.BadZipFile as exc:
        raise DocumentParseError(f"invalid XLSX package: {exc}") from exc


def _cell_to_text(value: object) -> str | None:
    if value is None:
        return None
    return str(value).strip()


class XlsxParser:
    """Reads the workbook with `openpyxl` (already an `apps/api` runtime dependency).

    See module docstring for why this replaces the standalone-worktree original's
    hand-rolled XML reader: that parser silently dropped every `inlineStr`-typed cell (it
    only special-cased shared-string cells) and mislabeled sheets from the 10th onward by
    lexicographically sorting `sheetN.xml` filenames as strings. `openpyxl` resolves sheet
    identity through the workbook's own relationships (`workbook.sheetnames`, in true
    document order) and reads every cell type uniformly, so neither defect exists here.
    """

    format = DocumentFormat.XLSX

    def extract(self, content: bytes) -> list[tuple[str, str]]:
        _validate_xlsx_archive(content)
        try:
            workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        except (InvalidFileException, zipfile.BadZipFile, KeyError, ValueError, OSError) as exc:
            raise DocumentParseError(f"invalid XLSX package: {exc}") from exc

        try:
            rows: list[tuple[str, str]] = []
            for sheet_name in workbook.sheetnames:
                sheet = workbook[sheet_name]
                for row_number, row in enumerate(
                    sheet.iter_rows(values_only=True), start=1
                ):
                    cell_values = [
                        text for value in row if (text := _cell_to_text(value)) is not None
                    ]
                    if any(cell_values):
                        rows.append(
                            (f"sheet:{sheet_name}:row:{row_number}", ", ".join(cell_values))
                        )
            return rows
        finally:
            workbook.close()


# --- PDF (pypdf) -------------------------------------------------------------


class PdfTextParser:
    """Reads the PDF with `pypdf` (added as a dependency for this job - see module
    docstring for why the standalone-worktree original's hand-rolled object/stream scanner
    was replaced: it never decoded hex-string (`<...> Tj`) content, only literal-string
    (`(...) Tj`), so any Flate-compressed hex-encoded content stream - a normal producer
    output, not an edge case - was invisible to it and misclassified the page as
    OCR_REQUIRED. `pypdf` walks the real `/Pages` tree and font encodings instead of
    regex-scanning raw object bytes."""

    format = DocumentFormat.PDF

    def extract(self, content: bytes) -> list[tuple[str, str]]:
        if not content.startswith(b"%PDF-"):
            raise DocumentParseError("missing %PDF- header")

        try:
            reader = PdfReader(io.BytesIO(content), strict=False)
            page_count = len(reader.pages)
        except (PdfReadError, ValueError, OSError, KeyError) as exc:
            raise DocumentParseError(f"invalid PDF: {exc}") from exc

        pages: list[tuple[str, str]] = []
        for index in range(page_count):
            try:
                text = reader.pages[index].extract_text() or ""
            except Exception as exc:  # noqa: BLE001 - pypdf can raise assorted internal
                # errors on malformed page content streams; a single bad page must not
                # abort the whole document (parse_document's outer guard would anyway
                # convert an unhandled exception here to PROCESSING_FAILED, but skipping
                # just the offending page yields a strictly more useful partial result).
                logger.warning(
                    "document_parsing: page %d text extraction failed (%s), skipping page",
                    index + 1,
                    type(exc).__name__,
                )
                continue
            if text.strip():
                pages.append((f"page:{index + 1}", text.strip()))
        return pages


_PARSERS: dict[DocumentFormat, DocumentParser] = {
    DocumentFormat.PDF: PdfTextParser(),
    DocumentFormat.DOCX: DocxParser(),
    DocumentFormat.XLSX: XlsxParser(),
    DocumentFormat.CSV: CsvParser(),
    DocumentFormat.PLAIN_TEXT: PlainTextParser(),
}


def _decode_best_effort(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


_EXTENSION_FORMAT_MAP = {
    ".pdf": DocumentFormat.PDF,
    ".docx": DocumentFormat.DOCX,
    ".xlsx": DocumentFormat.XLSX,
    ".csv": DocumentFormat.CSV,
    ".txt": DocumentFormat.PLAIN_TEXT,
}


def detect_format(content: bytes, filename: str) -> DocumentFormat:
    """Detect format primarily from magic bytes (authoritative), falling
    back to the filename extension only when the content is ambiguous
    (e.g. an empty file)."""

    if content.startswith(b"%PDF-"):
        return DocumentFormat.PDF
    if content[:4] == b"PK\x03\x04":
        # DOCX/XLSX are both ZIP; disambiguate by peeking at zip entry names.
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                names = archive.namelist()
            if any(n.startswith("word/") for n in names):
                return DocumentFormat.DOCX
            if any(n.startswith("xl/") for n in names):
                return DocumentFormat.XLSX
        except zipfile.BadZipFile:
            pass

    ext = ""
    if "." in filename:
        ext = "." + filename.rsplit(".", 1)[-1].lower()
    if ext in _EXTENSION_FORMAT_MAP:
        return _EXTENSION_FORMAT_MAP[ext]

    return DocumentFormat.PLAIN_TEXT


# ---------------------------------------------------------------------------
# Idempotent segment store
# ---------------------------------------------------------------------------


@runtime_checkable
class SegmentStore(Protocol):
    """Persistence boundary for idempotent parse results, keyed by
    ``(content_hash, parser_version)``. See module docstring for why no
    Postgres-backed implementation lives in this file, and why this Protocol is async."""

    async def get(self, content_hash: str, parser_version: str) -> ParseResult | None: ...

    async def put(self, content_hash: str, parser_version: str, result: ParseResult) -> None: ...


@dataclass
class InMemorySegmentStore:
    """Reference SegmentStore for tests and local/dev use. Not safe to share
    across processes - a real deployment must back this with the durable
    store the integrator wires in (see README.md Integration TODO)."""

    _results: dict[tuple[str, str], ParseResult] = field(default_factory=dict)

    async def get(self, content_hash: str, parser_version: str) -> ParseResult | None:
        return self._results.get((content_hash, parser_version))

    async def put(self, content_hash: str, parser_version: str, result: ParseResult) -> None:
        self._results[(content_hash, parser_version)] = result


def compute_content_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


async def parse_document(
    content: bytes,
    *,
    filename: str = "",
    store: SegmentStore | None = None,
    parser_version: str = PARSER_VERSION,
) -> ParseResult:
    """Parse ``content`` into masked, offset-addressed text segments.

    Never raises for malformed/corrupted input - always returns a
    ``ParseResult`` (with ``status=PROCESSING_FAILED`` and a warning on
    unrecoverable errors) so a bad upload cannot crash the worker process.

    Idempotent: if ``store`` already has a result for this exact
    ``(sha256(content), parser_version)`` pair, that cached result is
    returned as-is (with ``from_cache=True``) instead of re-parsing/
    re-masking, and no duplicate segments are produced.
    """

    content_hash = compute_content_hash(content)

    if store is not None:
        cached = await store.get(content_hash, parser_version)
        if cached is not None:
            return ParseResult(
                status=cached.status,
                document_format=cached.document_format,
                content_hash=cached.content_hash,
                parser_version=cached.parser_version,
                segments=cached.segments,
                warnings=cached.warnings,
                from_cache=True,
            )

    document_format = detect_format(content, filename)

    if not content or not content.strip():
        result = ParseResult(
            status=ParseStatus.EMPTY,
            document_format=document_format,
            content_hash=content_hash,
            parser_version=parser_version,
        )
        if store is not None:
            await store.put(content_hash, parser_version, result)
        return result

    parser = _PARSERS[document_format]

    try:
        labeled_texts = parser.extract(content)
    except UnsupportedDocumentError as exc:
        result = ParseResult(
            status=ParseStatus.UNSUPPORTED_DOCUMENT,
            document_format=document_format,
            content_hash=content_hash,
            parser_version=parser_version,
            warnings=(f"unsupported document: {exc}",),
        )
        if store is not None:
            await store.put(content_hash, parser_version, result)
        return result
    except DocumentParseError as exc:
        result = ParseResult(
            status=ParseStatus.PROCESSING_FAILED,
            document_format=document_format,
            content_hash=content_hash,
            parser_version=parser_version,
            warnings=(f"parse failed: {exc}",),
        )
        if store is not None:
            await store.put(content_hash, parser_version, result)
        return result
    except Exception as exc:  # noqa: BLE001 - last-resort guard, must not crash the worker
        result = ParseResult(
            status=ParseStatus.PROCESSING_FAILED,
            document_format=document_format,
            content_hash=content_hash,
            parser_version=parser_version,
            warnings=(f"unexpected parse error: {type(exc).__name__}: {exc}",),
        )
        if store is not None:
            await store.put(content_hash, parser_version, result)
        return result

    if not labeled_texts:
        status = (
            ParseStatus.OCR_REQUIRED
            if document_format == DocumentFormat.PDF
            else ParseStatus.EMPTY
        )
        result = ParseResult(
            status=status,
            document_format=document_format,
            content_hash=content_hash,
            parser_version=parser_version,
        )
        if store is not None:
            await store.put(content_hash, parser_version, result)
        return result

    segments = _segments_from_texts(labeled_texts)
    result = ParseResult(
        status=ParseStatus.SUCCEEDED,
        document_format=document_format,
        content_hash=content_hash,
        parser_version=parser_version,
        segments=segments,
    )
    if store is not None:
        await store.put(content_hash, parser_version, result)
    return result


# ---------------------------------------------------------------------------
# Job registration hook (for the integrator)
# ---------------------------------------------------------------------------


@runtime_checkable
class JobRegistry(Protocol):
    """Structural placeholder for whatever RQ/Celery-backed registry the
    BACKEND track sets up for apps/worker (PROJECT_SCOPE.md: "RQ or Celery,
    no Kafka in MVP") - not implemented yet anywhere in this repo, so this
    module only requires the minimal shape it needs (a `register` method)
    rather than importing a real queue library that isn't a dependency
    here."""

    def register(self, name: str, handler: object) -> None: ...


async def handle_parse_document_job(
    payload: dict[str, object], *, store: SegmentStore
) -> ParseResult:
    """Job-shaped entry point: ``payload`` carries ``content`` (bytes) and
    optional ``filename`` (str). Kept separate from ``parse_document`` so a
    future queue adapter can call this with a deserialized payload without
    this module needing to know the queue's envelope format."""

    content = payload["content"]
    if not isinstance(content, (bytes, bytearray)):
        raise TypeError("payload['content'] must be bytes")
    filename = payload.get("filename", "")
    if not isinstance(filename, str):
        filename = ""
    return await parse_document(bytes(content), filename=filename, store=store)


def register_document_parsing_job(registry: JobRegistry) -> None:
    """Registration hook for the integrator - do not call this from within
    this track's own tests other than to check it does not raise; wiring a
    real registry/queue and a real SegmentStore is out of this track's
    OWNED PATHS."""

    registry.register("document_parsing", handle_parse_document_job)
