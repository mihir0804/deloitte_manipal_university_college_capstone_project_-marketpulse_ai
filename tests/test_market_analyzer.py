from modules.market_analyzer import competitor_comparison, market_intelligence_bundle
from modules.sentiment_engine import run_local_analysis


def mk(db, texts):
    ds_id = db.create_dataset("d", "csv", "own_customers", None, {}, len(texts))
    rows = [{"dataset_id": ds_id, "external_ref": f"M{i}", "text": t[0], "rating": t[1],
             "review_date": None, "product": None, "segment": None, "competitor": t[2],
             "channel": None, "valid": 1, "exclusion_reason": None, "payload": "{}"}
            for i, t in enumerate(texts, start=1)]
    db.insert_records(rows)
    records = db.get_records(ds_id, only_valid=True)
    classifications, metrics = run_local_analysis(records)
    return records, classifications, metrics


def test_no_competitor_data_disables_analysis(db):
    records, cls, m = mk(db, [("great tool love it", 5, None), ("awful crash", 1, None)])
    comp = competitor_comparison(records, cls)
    assert not comp["available"]
    assert "disabled" in comp["reason"].lower() or "no competitor" in comp["reason"].lower()


def test_competitor_column_and_text_mentions(db):
    records, cls, m = mk(db, [
        ("pricing better than CompetitorX", 4, None),
        ("CompetitorX undercuts us badly", 2, "CompetitorX"),
        ("love the product", 5, None)])
    comp = competitor_comparison(records, cls)
    assert comp["available"]
    names = {row["competitor"] for row in comp["table"]}
    assert "CompetitorX" in names
    assert any(comp["quotes"]["CompetitorX"])


def test_bundle_separates_tiers(db):
    from modules.insight_extractor import extract_insights
    records, cls, m = mk(db, [
        ("too expensive pricing complaint", 1, None),
        ("expensive versus competitors, switching considered at renewal", 2, None),
        ("wish we had offline mode", 3, None),
        ("love collaboration and support", 5, None)])
    insights = extract_insights(records, cls, m)
    bundle = market_intelligence_bundle(records, cls, insights, [], m)
    assert set(bundle.keys()) >= {"observed_evidence", "ai_interpretation", "strategic_hypothesis"}
    # observed tier must contain data-derived insight titles only
    derived_titles = {i["title"] for i in insights if i["origin"] == "data_derived"}
    for item in bundle["observed_evidence"]:
        assert item["title"] in derived_titles or item["title"].startswith(("User note", "Pricing friction"))
    hyp = bundle["strategic_hypothesis"]
    assert all("NOT measured" in i["detail"] or "Requires validation" in i["detail"]
               or "hypothesis" in i["evidence_count"] for i in hyp)


def test_notes_flow_into_observed(db):
    notes = [{"title": "Field interview", "body": "3 customers mentioned migration cost fear",
              "kind": "note"}]
    records, cls, m = mk(db, [("ok product", 3, None)])
    bundle = market_intelligence_bundle(records, cls, [], notes, m)
    assert any("Field interview" in o["title"] for o in bundle["observed_evidence"])
