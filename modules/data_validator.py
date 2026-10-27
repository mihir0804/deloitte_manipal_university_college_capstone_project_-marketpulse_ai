"""Dataset validation: quality checks, dedup policy, record-level exclusion reporting."""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List

from modules.data_parser import parse_date, parse_rating


def validate_records(raw_rows: List[Dict[str, Any]],
                     drop_duplicates: bool = True,
                     min_text_len: int = 10) -> Dict[str, Any]:
    """Validate and normalize raw mapped rows.

    Returns a report dict with original/valid/excluded counts, exclusion reasons,
    and the final normalized records ready for persistence (invalid rows are kept
    with valid=0 and an exclusion_reason - nothing is silently discarded).
    """
    valid: List[Dict[str, Any]] = []
    excluded: List[Dict[str, str]] = []
    seen_hashes: Dict[str, int] = {}
    notes: List[str] = []

    for i, row in enumerate(raw_rows):
        problems: List[str] = []
        text = (row.get("text") or "").strip()
        if not text:
            problems.append("empty feedback text")
        elif len(text) < min_text_len:
            problems.append(f"text shorter than {min_text_len} characters")

        rating, rating_err = parse_rating(row.get("rating_raw"))
        if rating_err:
            problems.append(rating_err)
        date_val, date_err = parse_date(row.get("date_raw"))
        if date_err:
            # A bad date alone does not invalidate the record; it is nulled + noted.
            notes.append(f"row {i+1}: {date_err} (date ignored)")

        fp = hashlib.sha1(text.lower().encode("utf-8")).hexdigest()
        dup_of = seen_hashes.get(fp)
        if dup_of is not None and drop_duplicates:
            problems.append(f"duplicate of row {dup_of}")
        elif dup_of is not None:
            notes.append(f"row {i+1}: duplicate text kept (dedup disabled), first seen at row {dup_of}")

        is_valid = len(problems) == 0
        if is_valid:
            seen_hashes[fp] = i + 1

        rec = {
            "dataset_id": row.get("dataset_id"),
            "external_ref": row.get("external_ref") or f"ROW-{i+1}",
            "text": text[:5000],
            "rating": rating,
            "review_date": date_val,
            "product": row.get("product") or None,
            "segment": row.get("segment") or None,
            "competitor": row.get("competitor") or None,
            "channel": row.get("channel") or None,
            "valid": 1 if is_valid else 0,
            "exclusion_reason": "; ".join(problems) if problems else None,
            "payload": row.get("payload") or {},
        }
        import json as _json
        rec["payload"] = _json.dumps(rec["payload"], ensure_ascii=False)
        valid.append(rec)
        if not is_valid:
            excluded.append({"row": i + 1, "ref": rec["external_ref"], "reasons": problems})

    total = len(raw_rows)
    n_valid = sum(1 for r in valid if r["valid"] == 1)
    report = {
        "original_row_count": total,
        "valid_row_count": n_valid,
        "excluded_row_count": total - n_valid,
        "exclusions": excluded,
        "notes": notes,
        "missing_field_summary": {
            "rating": sum(1 for r in valid if r["rating"] is None),
            "date": sum(1 for r in valid if r["review_date"] is None),
            "product": sum(1 for r in valid if not r["product"]),
            "segment": sum(1 for r in valid if not r["segment"]),
            "competitor": sum(1 for r in valid if not r["competitor"]),
            "channel": sum(1 for r in valid if not r["channel"]),
        },
        "config": {"drop_duplicates": drop_duplicates, "min_text_len": min_text_len},
    }
    return {"report": report, "records": valid}
