import json
import re
from pathlib import Path

import pytest

from modules.export_service import (build_campaign_pdf, campaign_pack_markdown,
                                    insights_report_markdown, safe_filename,
                                    sentiment_csv_bytes, write_markdown_export)

BRIEF = {"overview": "Overview text", "business_objective": "Get demos",
         "persona": {"name": "Ops Erin", "segment": "Mid-Market", "inferred": True,
                     "demographics_note": "NOT measured", "needs_goals": ["speed"],
                     "pain_points": ["slow reports"], "motivations": ["insight"],
                     "objections": ["price"], "preferred_channels": ["linkedin"],
                     "messaging_preferences": "plain"},
         "audience_needs": ["n1"], "motivations_objections": ["m1"],
         "value_proposition": "VP here", "usp": "USP here",
         "messaging_pillars": ["Pillar one (3 records)"], "supporting_evidence": ["e"],
         "recommended_channels": ["linkedin"], "channel_strategy": ["cs"],
         "content_themes": ["ct"], "cta_strategy": "Book a demo", "timeline": ["w1-2"],
         "kpis": ["kpi1"], "assumptions": ["a1"], "risks": ["r1"],
         "testing_recommendations": ["t1"]}


def setup_campaign(db, asset_status="approved", body="Approved social copy goes here."):
    ds = db.create_dataset("d", "csv", "own_customers", None, {}, 2)
    run = db.create_run(ds, "local", "none", {}, {"classified_records": 2,
                                                  "sentiment_counts": {"positive": 1, "negative": 1},
                                                  "sentiment_percentages": {"positive": 50.0, "negative": 50.0},
                                                  "average_rating": 3.0, "analysis_period": {"start": "2026-01-01", "end": "2026-02-01"},
                                                  "top_praise": [], "top_complaints": [],
                                                  "competitor_sentiment": {}})
    ins_ids = db.save_insights(run, ds, [{"title": "i1", "description": "d", "category": "pain_point",
                                          "evidence": ["R: quote"], "record_ids": [],
                                          "supporting_count": 2, "segments": [], "business_implication": "",
                                          "recommended_action": "", "confidence": "medium",
                                          "origin": "data_derived"}])
    db.save_quality_report(ds, {"original_row_count": 2, "valid_row_count": 2,
                                "excluded_row_count": 0, "exclusions": [], "notes": [],
                                "missing_field_summary": {"rating": 0}, "config": {}})
    cid = db.create_campaign("Export Test Campaign", {"campaign_name": "Export Test Campaign"}, ds, run)
    bid, _ = db.save_brief(cid, BRIEF, ins_ids)
    aid = db.create_asset(bid, cid, "uid-x", "linkedin_post", "Social Asset", body,
                          "CTA", "", {"fields_present": True})
    if asset_status != "draft":
        db.set_asset_status(aid, "under_review")
        db.set_asset_status(aid, asset_status)
    return ds, run, cid, bid, aid


def test_safe_filename():
    assert safe_filename("../../evil name!.pdf") == "evil_name_.pdf" or "/" not in safe_filename("../../evil name!.pdf")
    assert ".." not in safe_filename("../../etc/passwd")
    assert safe_filename("") == "export"


def test_markdown_pack_contains_actual_data(db, tmp_path, monkeypatch):
    import modules.export_service as es
    monkeypatch.setattr(es, "EXPORT_DIR", tmp_path)
    ds, run, cid, bid, aid = setup_campaign(db)
    md = campaign_pack_markdown(db, cid, include_drafts=False)
    assert "Export Test Campaign" in md
    assert "VP here" in md and "Pillar one" in md
    assert "APPROVED" in md and "Social Asset" in md
    assert "Inferred Hypothesis" in md


def test_drafts_not_labelled_approved(db, tmp_path, monkeypatch):
    import modules.export_service as es
    monkeypatch.setattr(es, "EXPORT_DIR", tmp_path)
    ds, run, cid, bid, aid = setup_campaign(db, asset_status="draft")
    md_only_approved = campaign_pack_markdown(db, cid, include_drafts=False)
    assert "No approved assets" in md_only_approved
    md_incl = campaign_pack_markdown(db, cid, include_drafts=True)
    assert "NOT APPROVED" in md_incl


def test_pdf_generated_with_sections(db, tmp_path, monkeypatch):
    import modules.export_service as es
    monkeypatch.setattr(es, "EXPORT_DIR", tmp_path)
    ds, run, cid, bid, aid = setup_campaign(db)
    p = build_campaign_pdf(db, cid)
    assert p.exists() and p.stat().st_size > 1500
    data = p.read_bytes()
    assert data[:4] == b"%PDF"
    # verify key section text is embedded (compressed streams -> decompress check)
    from pypdf import PdfReader
    import io
    reader = PdfReader(io.BytesIO(data))
    text = "".join(pg.extract_text() or "" for pg in reader.pages)
    for token in ["Campaign Pack", "Audience Persona", "Key Messaging Pillars",
                  "Success Metrics", "Content Assets", "Review"]:
        assert token.lower() in text.lower(), token
    assert "APPROVED" in text.upper()


def test_pdf_fails_safely_without_brief(db, tmp_path, monkeypatch):
    import modules.export_service as es
    monkeypatch.setattr(es, "EXPORT_DIR", tmp_path)
    ds = db.create_dataset("d", "csv", "own_customers", None, {}, 0)
    cid = db.create_campaign("empty", {}, ds, None)
    with pytest.raises(ValueError):
        build_campaign_pdf(db, cid)


def test_insights_report_md(db, tmp_path, monkeypatch):
    import modules.export_service as es
    monkeypatch.setattr(es, "EXPORT_DIR", tmp_path)
    ds, run, cid, bid, aid = setup_campaign(db)
    p = insights_report_markdown(db, run)
    content = p.read_text(encoding="utf-8")
    assert "Market Insights Report" in content
    assert "Methodology" in content
    assert "Run #" in content


def test_csv_export_respects_filters(db):
    ds, run, cid, bid, aid = setup_campaign(db)
    db.insert_records([
        {"dataset_id": ds, "external_ref": "P1", "text": "love it", "rating": 5,
         "review_date": None, "product": None, "segment": "Enterprise", "competitor": None,
         "channel": None, "valid": 1, "exclusion_reason": None, "payload": "{}"},
        {"dataset_id": ds, "external_ref": "N1", "text": "hate it", "rating": 1,
         "review_date": None, "product": None, "segment": "SMB", "competitor": None,
         "channel": None, "valid": 1, "exclusion_reason": None, "payload": "{}"}])
    recs = db.get_records(ds, only_valid=True)
    rows = [{"record_id": recs[0]["id"], "sentiment": "positive", "confidence": 0.7,
             "main_topic": "x", "pain_points": "[]", "positive_attributes": "[]",
             "feature_requests": "[]", "customer_intent": "", "evidence": "", "method": "local"},
            {"record_id": recs[1]["id"], "sentiment": "negative", "confidence": 0.7,
             "main_topic": "y", "pain_points": "[]", "positive_attributes": "[]",
             "feature_requests": "[]", "customer_intent": "", "evidence": "", "method": "local"}]
    db.save_sentiment_results(run, rows)
    full = sentiment_csv_bytes(db, run).decode()
    pos = sentiment_csv_bytes(db, run, "positive").decode()
    smb = sentiment_csv_bytes(db, run, None, "SMB").decode()
    assert full.count("\n") == 3
    assert "love it" in pos and "hate it" not in pos
    assert "hate it" in smb and "love it" not in smb
