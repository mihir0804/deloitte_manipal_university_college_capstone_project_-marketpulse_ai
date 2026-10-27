from modules.data_validator import validate_records


def base_row(**kw):
    r = {"dataset_id": 1, "external_ref": "R", "text": "This is meaningful feedback text",
         "rating_raw": "4", "date_raw": "2026-01-01", "product": None, "segment": None,
         "competitor": None, "channel": None, "payload": {}}
    r.update(kw)
    return r


def test_counts_accurate():
    rows = [base_row(), base_row(external_ref="R2", text=""),
            base_row(external_ref="R3", rating_raw="bad")]
    out = validate_records(rows)
    rep = out["report"]
    assert rep["original_row_count"] == 3
    assert rep["valid_row_count"] == 1
    assert rep["excluded_row_count"] == 2
    reasons = str(rep["exclusions"])
    assert "empty feedback" in reasons and "unparseable rating" in reasons


def test_duplicates_dropped_or_kept():
    rows = [base_row(), base_row(external_ref="D2")]
    dropped = validate_records(rows, drop_duplicates=True)
    kept = validate_records(rows, drop_duplicates=False)
    assert dropped["report"]["valid_row_count"] == 1
    assert kept["report"]["valid_row_count"] == 2
    assert kept["report"]["notes"]


def test_invalid_rows_persisted_not_silently_discarded():
    rows = [base_row(text="tiny"), base_row()]
    out = validate_records(rows)
    assert len(out["records"]) == 2
    invalid = [r for r in out["records"] if r["valid"] == 0]
    assert invalid and invalid[0]["exclusion_reason"]


def test_bad_date_does_not_invalidate():
    out = validate_records([base_row(date_raw="31st of Febtime")])
    assert out["report"]["valid_row_count"] == 1
    assert out["records"][0]["review_date"] is None


def test_missing_optional_fields_safe():
    out = validate_records([base_row(rating_raw=None, date_raw=None)])
    assert out["report"]["valid_row_count"] == 1
    mf = out["report"]["missing_field_summary"]
    assert mf["rating"] == 1 and mf["date"] == 1
