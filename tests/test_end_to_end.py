"""End-to-end acceptance scenario at the service layer (no browser available in this
environment - UI verification is documented as a limitation).

Steps mirror the assignment: load sample -> upload extra dataset -> validate/map ->
analyze -> inspect insight evidence -> brief -> edit persona -> generate content ->
edit asset -> review -> approve -> export PDF/MD -> reconnect DB -> verify persistence.
"""
import json
from pathlib import Path

import pytest

from modules.campaign_builder import build_local_brief, regenerate_section
from modules.config import SAMPLE_CSV
from modules.content_studio import generate_local_assets, validate_asset
from modules.data_parser import detect_column_mapping, map_dataframe, read_csv_bytes
from modules.data_validator import validate_records
from modules.db_handler import Database
from modules.export_service import build_campaign_pdf, campaign_pack_markdown
from modules import review_workflow as rw
from modules.insight_extractor import extract_insights
from modules.sentiment_engine import run_local_analysis


def test_full_workflow(tmp_path):
    dbp = str(tmp_path / "e2e.db")
    db = Database(dbp)

    # 1-2. load fictional sample dataset
    df = read_csv_bytes(SAMPLE_CSV.read_bytes())
    mapping = detect_column_mapping(df)
    assert mapping["text"] and mapping["rating"] and mapping["date"]
    res = validate_records(map_dataframe(df, mapping, []), drop_duplicates=True)
    ds1 = db.create_dataset("Sample Feedback (fictional)", "sample", "own_customers",
                            str(SAMPLE_CSV), mapping, res["report"]["original_row_count"])
    rows = res["records"]
    for r in rows:
        r["dataset_id"] = ds1
    db.insert_records(rows)
    db.save_quality_report(ds1, res["report"])
    total, valid = db.count_records(ds1)
    assert total == 25 and valid == 25

    # 3-4. upload an additional dataset with DIFFERENT schema, map columns
    csv2 = ('cust_ref,opinion,satisfaction,team_type\n'
            'B1,"Onboarding was smooth and helpful",5,SMB\n'
            'B2,"Too expensive, might cancel next quarter",1,Enterprise\n'
            'B3,"slow performance and confusing docs",2,SMB\n'
            'B4,"",,\n'
            'B5,"great value compared to CompetitorX which is pricier",4,Mid-Market\n')
    df2 = read_csv_bytes(csv2.encode())
    m2 = {"id": "cust_ref", "text": "opinion", "rating": "satisfaction", "date": None,
          "product": None, "segment": "team_type", "competitor": None, "channel": None}
    res2 = validate_records(map_dataframe(df2, m2, []))
    ds2 = db.create_dataset("Extra feedback", "csv", "own_customers", None, m2,
                            res2["report"]["original_row_count"])
    for r in res2["records"]:
        r["dataset_id"] = ds2
    db.insert_records(res2["records"])
    db.save_quality_report(ds2, res2["report"])
    assert res2["report"]["excluded_row_count"] == 1  # empty text row excluded visibly
    assert res2["report"]["valid_row_count"] == 4

    # 5. run sentiment + market analysis on ds2
    records = db.get_records(ds2, only_valid=True)
    classifications, metrics = run_local_analysis(records)
    run_id = db.create_run(ds2, "local", "none", {"mode": "local"}, metrics)
    save_rows = [dict(c, pain_points=json.dumps(c["pain_points"]),
                      positive_attributes=json.dumps(c["positive_attributes"]),
                      feature_requests=json.dumps(c["feature_requests"]))
                 for c in classifications]
    db.save_sentiment_results(run_id, save_rows)
    insights = extract_insights(records, classifications, metrics)
    ins_ids = db.save_insights(run_id, ds2, insights)
    assert len(ins_ids) >= 1
    assert metrics["sentiment_percentages"]

    # 6. inspect an insight's supporting records
    stored = db.list_insights(run_id=run_id)
    target = next(i for i in stored if i["category"] == "pain_point")
    rec_ids = set(r["id"] for r in records)
    assert set(target["record_ids"]) <= rec_ids
    quotes = [db.query_one("SELECT text FROM records WHERE id=?", (rid,))["text"]
              for rid in target["record_ids"]]
    assert any("expensive" in q.lower() or "slow" in q.lower() or "confusing" in q.lower()
               for q in quotes)

    # 7. generate campaign brief from saved insights
    setup = {"campaign_name": "E2E Retention Push", "product_service": "InsightHub Pro",
             "business_objective": "reduce churn risk in enterprise renewals",
             "target_market": "B2B SaaS", "audience_segment": "Enterprise",
             "geographic_market": "NA", "brand_positioning": "evidence-led",
             "budget": "$10k", "duration": "4 weeks", "channels": ["linkedin", "email"],
             "desired_action": "Book renewal call", "brand_voice": "credible",
             "restrictions": "", "competitor_context": ""}
    cid = db.create_campaign(setup["campaign_name"], setup, ds2, run_id)
    built = build_local_brief(setup, stored, metrics)
    bid, v = db.save_brief(cid, built["brief"], [i["id"] for i in stored])
    assert v == 1

    # 8. edit persona + messaging strategy (new version)
    updated = regenerate_section(built["brief"], "persona",
                                 dict(built["brief"]["persona"], name="Renewal-Risk Rachel"))
    updated = regenerate_section(updated, "messaging_pillars", ["Custom pillar one"])
    bid2, v2 = db.save_brief(cid, updated, [i["id"] for i in stored])
    assert v2 == 2
    assert db.get_brief(bid)["content"]["persona"]["name"] != "Renewal-Risk Rachel"  # v1 preserved

    # 9. generate LinkedIn + email + ad content
    params_li = {"channel": "linkedin", "variations": 2, "cta": "Book renewal call",
                 "product": "InsightHub Pro", "primary_message": "pm", "brand_voice": "credible",
                 "required_phrases": "", "restricted_phrases": ""}
    created_uids = []
    for ch in ["linkedin", "email", "search_ad"]:
        p = dict(params_li, channel=ch)
        assets = generate_local_assets(updated, p)
        assert assets
        for a in assets:
            val = validate_asset(a, p, updated)
            uid = f"{ch}-{len(created_uids)+1}"
            aid = db.create_asset(bid2, cid, uid, a["asset_type"], a["title"], a["body"],
                                  a.get("cta", ""), "", val)
            created_uids.append((uid, aid))

    # 10. edit one generated asset
    uid, aid = created_uids[0]
    new_aid = rw.edit_asset(db, uid, "Hand-improved headline",
                            "Human-edited body referencing pricing objections.", "Book now",
                            "", {"cta": "Book now"}, updated)
    assert db.get_asset(new_aid)["version"] == 2

    # 11-12. submit + approve final versions
    pack = rw.approve_campaign_pack(db, cid, "E2E approval session")
    assert not pack["blocked_assets"], pack["blocked_assets"]
    latest = db.list_assets(campaign_id=cid)
    assert all(a["status"] == "approved" for a in latest)
    edited = db.get_asset_by_uid_latest(uid)
    assert edited["body"].startswith("Human-edited body")
    assert edited["status"] == "approved"

    # 13. export approved pack as PDF + Markdown
    pdf = build_campaign_pdf(db, cid)
    assert pdf.exists() and pdf.read_bytes()[:4] == b"%PDF"
    md = campaign_pack_markdown(db, cid, include_drafts=False)
    assert "Human-edited body referencing pricing objections." in md
    assert "APPROVED" in md

    # 14. reconnect to database (simulated restart)
    db2 = Database(dbp)

    # 15. verify persistence of everything
    assert db2.get_dataset(ds2)["name"] == "Extra feedback"
    assert db2.get_dataset(ds1)["row_count"] == 25
    assert db2.get_run(run_id)["mode"] == "local"
    assert len(db2.list_insights(run_id=run_id)) == len(stored)
    b = db2.latest_brief(cid)
    assert b["content"]["persona"]["name"] == "Renewal-Risk Rachel"
    assert b["content"]["messaging_pillars"] == ["Custom pillar one"]
    assert db2.get_asset_by_uid_latest(uid)["body"].startswith("Human-edited body")
    reviews = db2.list_reviews("campaign_pack", cid)
    assert reviews and reviews[-1]["action"] == "approve"
    exports = db2.list_exports()
    assert any(e["export_type"] == "pdf" for e in exports)
    assert any(e["export_type"] == "markdown" for e in exports)
    audit = db2.list_audit()
    assert any(e["event"] == "dataset.created" for e in audit)
    assert any(e["event"] == "asset.status" for e in audit)
