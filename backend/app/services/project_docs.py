"""Project document handling: upload validation, text extraction (with page/section info), safe on-disk storage.

Nothing here trusts the client: the extension must be on the allow-list AND the bytes must really be that format,
the on-disk name is a server-generated key (the client filename is only ever stored as display metadata), and every
parser failure becomes a ParseError with a user-facing message rather than a 500.
"""
import csv
import io
import re
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from app.config import get_settings
from app.services import parser
from app.services.parser import Block, ParseError, ParsedDoc, ParsedPage

ALLOWED = {"pdf": "application/pdf", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
           "txt": "text/plain", "md": "text/markdown", "csv": "text/csv"}
MAX_UNCOMPRESSED = 60 * 1024 * 1024    # zip-bomb guard for DOCX
MAX_CSV_ROWS = 5000
CSV_ROWS_PER_BLOCK = 15
MAX_EXTRACTED_CHARS = 2_000_000
_HEAD = re.compile(r"^(#{1,6}\s+.+|\d{1,2}(\.\d{1,2}){0,3}\.?\s+[A-Z][^\n]{2,90}|[A-Z][A-Z0-9 \-:]{3,60})$")
_FNAME_BAD = re.compile(r"[^\w.\- ()]+")


@dataclass
class Extracted:
    file_type: str
    doc: ParsedDoc
    warnings: list[str] = field(default_factory=list)


def clean_filename(name: str) -> str:
    """Display-only: strip any path and odd characters. Never used to build a path."""
    base = (name or "document").replace("\\", "/").rsplit("/", 1)[-1]
    base = _FNAME_BAD.sub("_", base).strip(" .") or "document"
    return base[:200]


def file_type_of(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED:
        raise ParseError(f"Unsupported file type '.{ext}'. Allowed: PDF, DOCX, TXT, MD, CSV.")
    return ext


def _decode(data: bytes, warnings: list[str]) -> str:
    if b"\x00" in data[:8192]:
        raise ParseError("This file looks binary, not text.")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        warnings.append("File is not UTF-8; decoded as Windows-1252, some characters may be wrong.")
        return data.decode("cp1252", errors="replace")


def _text_blocks(text: str) -> list[Block]:
    blocks: list[Block] = []
    for para in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        lines = [ln.strip() for ln in para.split("\n") if ln.strip()]
        if not lines:
            continue
        if len(lines) == 1 and len(lines[0]) <= 100 and _HEAD.match(lines[0]):
            blocks.append(Block(lines[0].lstrip("# ").strip(), True))
        else:
            blocks.append(Block(" ".join(lines)))
    return blocks


def _parse_csv(text: str, warnings: list[str]) -> ParsedDoc:
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(text), dialect))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if len(rows) < 2:
        raise ParseError("This CSV has no data rows.")
    header, body = [h.strip() or f"col{i + 1}" for i, h in enumerate(rows[0])], rows[1:]
    if len(body) > MAX_CSV_ROWS:
        warnings.append(f"CSV has {len(body)} rows; only the first {MAX_CSV_ROWS} were indexed.")
        body = body[:MAX_CSV_ROWS]
    blocks: list[Block] = []
    for i in range(0, len(body), CSV_ROWS_PER_BLOCK):
        part = body[i:i + CSV_ROWS_PER_BLOCK]
        blocks.append(Block(f"Rows {i + 1}-{i + len(part)} (columns: {', '.join(header)})", True))
        for r in part:
            blocks.append(Block("; ".join(f"{h}: {c.strip()}" for h, c in zip(header, r) if c.strip()) + "."))
    return ParsedDoc("csv", [ParsedPage(None, blocks)], None, [])


def extract(filename: str, data: bytes) -> Extracted:
    """Validate and parse. Raises ParseError (user-safe message) for anything unusable."""
    ftype = file_type_of(filename)
    limit = get_settings().project_max_upload_mb * 1024 * 1024
    if not data:
        raise ParseError("The file is empty.")
    if len(data) > limit:
        raise ParseError(f"File is larger than {get_settings().project_max_upload_mb} MB.")
    warnings: list[str] = []
    if ftype == "pdf":
        if data[:5] != b"%PDF-":
            raise ParseError("This file is not a real PDF (content does not match its extension).")
        doc = parser.parse_pdf(data)
        if doc.scanned_pages:
            warnings.append("No extractable text on page(s) " + ", ".join(map(str, doc.scanned_pages[:20]))
                            + " (scanned images?). Those pages are not searchable.")
    elif ftype == "docx":
        if data[:4] != b"PK\x03\x04":
            raise ParseError("This file is not a real DOCX (content does not match its extension).")
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                if "word/document.xml" not in z.namelist():
                    raise ParseError("This file is not a Word document.")
                if sum(i.file_size for i in z.infolist()) > MAX_UNCOMPRESSED:
                    raise ParseError("This DOCX expands to an unsafe size.")
        except zipfile.BadZipFile as e:
            raise ParseError("This DOCX is corrupt or unreadable.") from e
        doc = parser.parse_docx(data)
    else:
        text = _decode(data, warnings)
        if not text.strip():
            raise ParseError("The file contains no text.")
        if ftype == "csv":
            doc = _parse_csv(text, warnings)
        else:
            blocks = _text_blocks(text)
            if not blocks:
                raise ParseError("The file contains no readable text.")
            doc = ParsedDoc(ftype, [ParsedPage(None, blocks)], None, [])
    if not doc.full_text.strip():
        raise ParseError("No readable text was found in this file.")
    return Extracted(ftype, doc, warnings)


def pages_payload(doc: ParsedDoc) -> list[dict]:
    """Stored form of the extracted text, kept so users can read it back and so the index can be rebuilt."""
    out, total = [], 0
    for p in doc.pages:
        t = p.text
        if not t.strip():
            continue
        total += len(t)
        if total > MAX_EXTRACTED_CHARS:
            break
        out.append({"page": p.page, "text": t})
    return out


# ------------------------------------------------------------------ storage
def _root() -> Path:
    root = Path(get_settings().storage_dir)
    if not root.is_absolute():
        root = Path(__file__).resolve().parents[2] / root
    return root


def _path(project_id: uuid.UUID, key: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", key):
        raise ValueError("bad storage key")
    return _root() / "projects" / str(project_id) / key


def new_key() -> str:
    return uuid.uuid4().hex


def save(project_id: uuid.UUID, key: str, data: bytes) -> None:
    p = _path(project_id, key)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


def read(project_id: uuid.UUID, key: str) -> bytes:
    return _path(project_id, key).read_bytes()


def remove(project_id: uuid.UUID, key: str) -> None:
    _path(project_id, key).unlink(missing_ok=True)


def remove_project_files(project_id: uuid.UUID) -> None:
    import shutil
    shutil.rmtree(_root() / "projects" / str(project_id), ignore_errors=True)
