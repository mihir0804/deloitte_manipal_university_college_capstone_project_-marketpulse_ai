import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.db_handler import Database


@pytest.fixture()
def db(tmp_path):
    return Database(str(tmp_path / "test.db"))


@pytest.fixture()
def sample_records(db):
    """Insert a small dataset with known content; returns (ds_id, records)."""
    ds_id = db.create_dataset("t", "csv", "own_customers", None, {}, 4)
    rows = [
        {"dataset_id": ds_id, "external_ref": "A1", "text": "Love the dashboard, excellent support and fast export", "rating": 5.0, "review_date": "2026-01-05", "product": "P", "segment": "Enterprise", "competitor": None, "channel": "web", "valid": 1, "exclusion_reason": None, "payload": "{}"},
        {"dataset_id": ds_id, "external_ref": "A2", "text": "Terrible pricing, too expensive, considering switching to CompetitorX", "rating": 2.0, "review_date": "2026-02-01", "product": "P", "segment": "Small Business", "competitor": "CompetitorX", "channel": "web", "valid": 1, "exclusion_reason": None, "payload": "{}"},
        {"dataset_id": ds_id, "external_ref": "A3", "text": "The app crashes constantly and reports are slow, very frustrating", "rating": 1.0, "review_date": "2026-02-10", "product": "M", "segment": "Enterprise", "competitor": None, "channel": "app", "valid": 1, "exclusion_reason": None, "payload": "{}"},
        {"dataset_id": ds_id, "external_ref": "A4", "text": "It is okay I guess", "rating": 3.0, "review_date": None, "product": None, "segment": None, "competitor": None, "channel": None, "valid": 1, "exclusion_reason": None, "payload": "{}"},
    ]
    db.insert_records(rows)
    return ds_id, db.get_records(ds_id, only_valid=True)
