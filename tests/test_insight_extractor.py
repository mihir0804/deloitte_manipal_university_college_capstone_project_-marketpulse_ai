from modules.insight_extractor import extract_insights
from modules.sentiment_engine import run_local_analysis


def make_records(db, ds_id):
    rows = [
        {"dataset_id": ds_id, "external_ref": f"X{i}", "text": t, "rating": rt,
         "review_date": "2026-01-01", "product": "P", "segment": seg, "competitor": None,
         "channel": None, "valid": 1, "exclusion_reason": None, "payload": "{}"}
        for i, (t, rt, seg) in enumerate([
            ("pricing is too expensive versus competitors", 2, "Small Business"),
            ("overpriced and billing errors hurt us", 1, "Small Business"),
            ("love the collaboration features, excellent teamwork", 5, "Enterprise"),
            ("fantastic support team, very responsive", 5, "Enterprise"),
            ("wish there was a slack integration", 3, "Mid-Market"),
            ("considering switching to another vendor next renewal", 2, "Small Business"),
        ], start=1)]
    db.insert_records(rows)
    return db.get_records(ds_id, only_valid=True)


def test_insights_have_traceable_evidence(db):
    ds_id = db.create_dataset("d", "csv", "own_customers", None, {}, 6)["id"] if isinstance(db.create_dataset("d", "csv", "own_customers", None, {}, 6), dict) else db.create_dataset("x", "csv", "own_customers", None, {}, 6)
    records = make_records(db, ds_id)
    classifications, metrics = run_local_analysis(records)
    insights = extract_insights(records, classifications, metrics)
    assert insights
    ids = {r["id"] for r in records}
    for ins in insights:
        assert ins["record_ids"], f"insight without record linkage: {ins['title']}"
        assert set(ins["record_ids"]) <= ids
        assert ins["supporting_count"] >= 2 or ins["origin"] == "hypothesis"
        assert ins["evidence"]
        assert ins["business_implication"] and ins["recommended_action"]
        assert ins["origin"] in ("data_derived", "ai_interpreted", "hypothesis")


def test_pain_point_and_churn_insights_present(db):
    ds_id = db.create_dataset("d", "csv", "own_customers", None, {}, 6)
    records = make_records(db, ds_id)
    classifications, metrics = run_local_analysis(records)
    insights = extract_insights(records, classifications, metrics)
    cats = {i["category"] for i in insights}
    assert "pain_point" in cats
    assert "churn_risk" in cats
    pricing = [i for i in insights if "pricing" in i["title"].lower()]
    assert pricing and pricing[0]["supporting_count"] == 2


def test_segments_linked(db):
    ds_id = db.create_dataset("d", "csv", "own_customers", None, {}, 6)
    records = make_records(db, ds_id)
    classifications, metrics = run_local_analysis(records)
    insights = extract_insights(records, classifications, metrics)
    sb = [i for i in insights if "Small Business" in i.get("segments", [])]
    assert sb
