"""Data ingestion: file loading, schema detection, column mapping, normalization."""
from __future__ import annotations

import io
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from modules.config import ALLOWED_EXTENSIONS, MAX_UPLOAD_BYTES

FIELD_ROLES = ["id", "text", "rating", "date", "product", "segment", "competitor", "channel"]

# Heuristic patterns for automatic column-role detection (lowercased substring match)
ROLE_PATTERNS: Dict[str, List[str]] = {
    "id": ["review_id", "customer_id", "record_id", "ticket_id", "id", "ref"],
    "text": ["feedback", "review", "comment", "text", "response", "observation", "content", "message"],
    "rating": ["rating", "score", "stars", "satisfaction"],
    "date": ["date", "created", "timestamp", "submitted"],
    "product": ["product", "service", "plan", "sku"],
    "segment": ["segment", "tier", "cohort", "customer_type", "plan_level"],
    "competitor": ["competitor", "brand_vs", "rival"],
    "channel": ["channel", "source", "platform", "medium"],
}


class IngestionError(ValueError):
    """Raised when a source cannot be ingested."""


def validate_file_meta(filename: str, size_bytes: int) -> None:
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise IngestionError(
            f"Unsupported file type '{ext}'. Supported: {sorted(ALLOWED_EXTENSIONS)}")
    if size_bytes <= 0:
        raise IngestionError("File is empty.")
    if size_bytes > MAX_UPLOAD_BYTES:
        raise IngestionError(f"File exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.")


def read_csv_bytes(data: bytes) -> pd.DataFrame:
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return pd.read_csv(io.BytesIO(data), encoding=enc, dtype=str, keep_default_na=False)
        except UnicodeDecodeError:
            continue
        except pd.errors.EmptyDataError:
            raise IngestionError("CSV file contains no data rows.")
        except pd.errors.ParserError as e:
            raise IngestionError(f"Malformed CSV: {e}")
    raise IngestionError("Could not decode file as UTF-8 or Latin-1 text.")


def read_text_bytes(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise IngestionError("Could not decode text file.")


def extract_pdf_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise IngestionError("PDF support requires the 'pypdf' package.") from e
    reader = PdfReader(io.BytesIO(data))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def extract_docx_text(data: bytes) -> str:
    try:
        import docx
    except ImportError as e:
        raise IngestionError("DOCX support requires the 'python-docx' package.") from e
    d = docx.Document(io.BytesIO(data))
    return "\n".join(p.text for p in d.paragraphs)


def load_document_as_records(data: bytes, filename: str) -> List[Dict[str, Any]]:
    """TXT/MD/PDF/DOCX research notes -> paragraph-level records."""
    ext = Path(filename).suffix.lower()
    if ext in (".txt", ".md", ".markdown"):
        text = read_text_bytes(data)
    elif ext == ".pdf":
        text = extract_pdf_text(data)
    elif ext == ".docx":
        text = extract_docx_text(data)
    else:
        raise IngestionError(f"Unsupported document type: {ext}")
    return split_text_into_feedback(text)


def split_text_into_feedback(text: str) -> List[Dict[str, Any]]:
    """Split free text into sentence/paragraph level feedback units."""
    text = text.strip()
    if not text:
        return []
    chunks: List[str] = []
    for para in re.split(r"\n\s*\n|\n- |\n\* |^#\s+", text, flags=re.M):
        para = para.strip()
        if not para:
            continue
        sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z\"'])", para)
        merged = ""
        for s in sentences:
            merged = (merged + " " + s).strip()
            if len(merged) >= 60:
                chunks.append(merged)
                merged = ""
        if merged:
            chunks.append(merged)
    return [{"external_ref": f"DOC-{i+1:03d}", "text": c} for i, c in enumerate(chunks) if len(c) >= 15]


def detect_column_mapping(df: pd.DataFrame) -> Dict[str, Optional[str]]:
    """Return best-guess {role: column}. Never assigns one column to two roles."""
    mapping: Dict[str, Optional[str]] = {r: None for r in FIELD_ROLES}
    used: set = set()
    cols_lower = {c: str(c).lower().strip() for c in df.columns}
    # exact / prefix matches first, then substring; ordered by role priority
    for role in ["text", "rating", "date", "id", "product", "segment", "competitor", "channel"]:
        candidates = []
        for col, low in cols_lower.items():
            if col in used:
                continue
            for rank, pat in enumerate(ROLE_PATTERNS[role]):
                if low == pat:
                    candidates.append((0, col)); break
                if low.startswith(pat) or low.endswith(pat):
                    candidates.append((1, col)); break
                if pat in low:
                    candidates.append((2, col)); break
        if candidates:
            candidates.sort(key=lambda t: (t[0], list(df.columns).index(t[1])))
            chosen = candidates[0][1]
            mapping[role] = chosen
            used.add(chosen)
    # fallback: widest textual column as 'text'
    if mapping["text"] is None:
        best, best_len = None, 0
        for col in df.columns:
            if col in used:
                continue
            avg = df[col].astype(str).str.len().mean()
            if avg > best_len:
                best, best_len = col, avg
        if best is not None and best_len >= 10:
            mapping["text"] = best
    return mapping


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", str(value))
    value = re.sub(r"\s+", " ", value).strip()
    return value


def parse_rating(value: Any) -> Tuple[Optional[float], Optional[str]]:
    """Return (rating, error). Ratings expected on 1..5 scale; larger scales rescaled with note."""
    if value is None or str(value).strip() == "":
        return None, None
    s = str(value).strip().lower().replace("/5", "").replace("out of 5", "")
    m = re.search(r"-?\d+(\.\d+)?", s)
    if not m:
        return None, f"unparseable rating '{value}'"
    r = float(m.group())
    if r < 0 or r > 10:
        return None, f"out-of-range rating '{r}'"
    if r > 5:  # e.g. 0-10 satisfaction score -> normalize to 5-point scale
        r = round(r / 2.0, 1)
    return r, None


DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d", "%d-%b-%Y", "%B %d, %Y", "%b %d, %Y"]


def parse_date(value: Any) -> Tuple[Optional[str], Optional[str]]:
    if value is None or str(value).strip() == "":
        return None, None
    s = str(value).strip()
    for fmt in DATE_FORMATS:
        try:
            return pd.to_datetime(s, format=fmt).strftime("%Y-%m-%d"), None
        except (ValueError, TypeError):
            continue
    try:
        ts = pd.to_datetime(s, errors="raise", dayfirst=False)
        return ts.strftime("%Y-%m-%d"), None
    except Exception:
        return None, f"unparseable date '{value}'"


def map_dataframe(df: pd.DataFrame, mapping: Dict[str, Optional[str]],
                  dataset_seed: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert mapped DataFrame rows into normalized record dicts (pre-validation)."""
    unmapped = [c for c in df.columns if c not in mapping.values()]
    rows = []
    for idx, row in df.iterrows():
        rec: Dict[str, Any] = {
            "dataset_id": None,
            "external_ref": normalize_text(row[mapping["id"]])[:120] if mapping.get("id") else f"ROW-{idx+1}",
            "text": normalize_text(row[mapping["text"]]) if mapping.get("text") else "",
            "rating_raw": row.get(mapping["rating"]) if mapping.get("rating") else None,
            "date_raw": row.get(mapping["date"]) if mapping.get("date") else None,
            "product": normalize_text(row[mapping["product"]])[:120] if mapping.get("product") else None,
            "segment": normalize_text(row[mapping["segment"]])[:120] if mapping.get("segment") else None,
            "competitor": normalize_text(row[mapping["competitor"]])[:120] if mapping.get("competitor") else None,
            "channel": normalize_text(row[mapping["channel"]])[:120] if mapping.get("channel") else None,
            "payload": {c: str(row[c]) for c in unmapped if str(row[c]).strip() != ""},
        }
        rows.append(rec)
    return rows
