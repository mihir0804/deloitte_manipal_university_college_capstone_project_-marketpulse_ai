import json

import pytest

from modules.db_handler import Database


def test_schema_init_idempotent(tmp_path):
    p = str(tmp_path / "x.db")
    Database(p)
    Database(p)  # second init must not fail


def test_foreign_key_cascade(tmp_path, db):
    ds = db.create_dataset("d", "csv", "own_customers", None, {}, 1)
    db.insert_records([{"dataset_id": ds, "external_ref": "a", "text": "great product love it",
                        "rating": 5.0, "review_date": None, "product": None, "segment": None,
                        "competitor": None, "channel": None, "valid": 1,
                        "exclusion_reason": None, "payload": "{}"}])
    run = db.create_run(ds, "local", "none", {}, {})
    rec = db.get_records(ds)[0]
    db.save_sentiment_results(run, [{"record_id": rec["id"], "sentiment": "positive",
                                     "confidence": 0.8, "main_topic": "product",
                                     "pain_points": "[]", "positive_attributes": "[\"love\"]",
                                     "feature_requests": "[]", "customer_intent": "",
                                     "evidence": "t", "method": "local"}])
    db.delete_dataset(ds)
    assert db.get_records(ds) == []
    assert db.list_runs(ds) == []
    assert db.get_sentiment_results(run) == []


def test_invalid_record_fk_rejected(db):
    with pytest.raises(Exception):
        db.insert_records([{"dataset_id": 9999, "external_ref": "x", "text": "t",
                            "rating": None, "review_date": None, "product": None,
                            "segment": None, "competitor": None, "channel": None,
                            "valid": 1, "exclusion_reason": None, "payload": "{}"}])


def test_brief_versioning(db):
    ds = db.create_dataset("d", "csv", "own_customers", None, {}, 0)
    cid = db.create_campaign("c", {"campaign_name": "c"}, ds, None)
    b1, v1 = db.save_brief(cid, {"overview": "one"}, [])
    b2, v2 = db.save_brief(cid, {"overview": "two"}, [])
    assert (v1, v2) == (1, 2)
    assert db.get_brief(b1)["content"]["overview"] == "one"  # old version preserved


def test_asset_unique_versions(db):
    ds = db.create_dataset("d", "csv", "own_customers", None, {}, 0)
    cid = db.create_campaign("c", {}, ds, None)
    bid, _ = db.save_brief(cid, {}, [])
    db.create_asset(bid, cid, "uid-a", "linkedin_post", "T", "b1", "", "", {})
    db.create_asset(bid, cid, "uid-a", "linkedin_post", "T", "b2", "", "", {})
    latest = db.get_asset_by_uid_latest("uid-a")
    assert latest["version"] == 2 and latest["body"] == "b2"
    rows = db.query("SELECT version FROM content_assets WHERE asset_uid='uid-a' ORDER BY version")
    assert [r["version"] for r in rows] == [1, 2]


def test_update_brief_content_blocks_approved(db):
    ds = db.create_dataset("d", "csv", "own_customers", None, {}, 0)
    cid = db.create_campaign("c", {}, ds, None)
    bid, _ = db.save_brief(cid, {"x": 1}, [])
    db.update_brief_content(bid, {"x": 2})          # draft ok
    db.set_brief_status(bid, "under_review")
    db.set_brief_status(bid, "approved")
    with pytest.raises(ValueError):
        db.update_brief_content(bid, {"x": 3})      # approved locked


def test_audit_events_written(db):
    db.create_dataset("d", "csv", "own_customers", None, {}, 0)
    events = db.list_audit()
    assert any(e["event"] == "dataset.created" for e in events)


def test_persistence_across_connections(tmp_path):
    p = str(tmp_path / "persist.db")
    d1 = Database(p)
    ds = d1.create_dataset("keepme", "csv", "own_customers", None, {}, 0)
    d2 = Database(p)
    assert d2.get_dataset(ds)["name"] == "keepme"
