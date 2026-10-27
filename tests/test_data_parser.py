import io
import pytest

from modules.data_parser import (IngestionError, detect_column_mapping,
                                 load_document_as_records, map_dataframe,
                                 parse_date, parse_rating, read_csv_bytes,
                                 split_text_into_feedback, validate_file_meta)


def make_csv(text):
    return text.encode("utf-8")


def test_valid_csv_loads():
    df = read_csv_bytes(make_csv('id,feedback,rating\n1,"Great product",5\n2,"Bad",1\n'))
    assert len(df) == 2
    assert list(df.columns) == ["id", "feedback", "rating"]


def test_malformed_csv_fails_gracefully():
    with pytest.raises(IngestionError):
        read_csv_bytes(b'')


def test_unsupported_extension():
    with pytest.raises(IngestionError):
        validate_file_meta("data.xlsx", 100)


def test_oversize_rejected():
    with pytest.raises(IngestionError):
        validate_file_meta("a.csv", 999_999_999)


def test_empty_file_rejected():
    with pytest.raises(IngestionError):
        validate_file_meta("a.csv", 0)


def test_auto_mapping_detects_roles():
    df = read_csv_bytes(make_csv('customer_id,review_text,score,created_date,product,segment\n'
                                 '7,"lovely tool",4,2026-01-02,X,SMB\n'))
    m = detect_column_mapping(df)
    assert m["text"] == "review_text"
    assert m["rating"] == "score"
    assert m["date"] == "created_date"
    assert m["id"] == "customer_id"
    assert m["product"] == "product"
    assert m["segment"] == "segment"


def test_manual_mapping_works():
    df = read_csv_bytes(make_csv('weird_col,other\n"some long feedback text here",zzz\n'))
    mapping = {"id": None, "text": "weird_col", "rating": None, "date": None,
               "product": None, "segment": None, "competitor": None, "channel": None}
    rows = map_dataframe(df, mapping, [])
    assert rows[0]["text"].startswith("some long feedback")


def test_rating_parsing_and_validation():
    assert parse_rating("4") == (4.0, None)
    assert parse_rating("8/10x") == (4.0, None)  # rescaled
    r, err = parse_rating("abc")
    assert r is None and err
    r, err = parse_rating("99")
    assert r is None and "out-of-range" in err
    assert parse_rating("") == (None, None)


def test_date_parsing():
    assert parse_date("2026-05-01")[0] == "2026-05-01"
    assert parse_date("not a date")[1] is not None


def test_document_splitting():
    recs = split_text_into_feedback("Trial period felt far too short for evaluation.\n\n"
                                    "Customers praised the new API speed improvements.")
    assert len(recs) >= 2
    assert all(r["external_ref"].startswith("DOC-") for r in recs)


def test_txt_ingestion():
    recs = load_document_as_records(b"We noticed competitor X undercuts on price significantly.",
                                    "notes.txt")
    assert recs and "competitor" in recs[0]["text"]
