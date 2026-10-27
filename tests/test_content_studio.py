import pytest

from modules.content_studio import (flag_near_duplicates, generate_local_assets,
                                    validate_asset)
from modules.review_workflow import edit_asset  # noqa - ensure import works

BRIEF = {
    "overview": "o", "business_objective": "increase demos",
    "persona": {"name": "n", "pain_points": ["billing errors"], "needs_goals": []},
    "value_proposition": "Turn feedback into decisions with evidence.",
    "usp": "u", "messaging_pillars": ["Evidenced strength - support (4 records)"],
    "supporting_evidence": ["x"], "recommended_channels": ["linkedin"],
    "channel_strategy": [], "content_themes": [], "cta_strategy": "Primary CTA: 'Book a demo'.",
    "timeline": [], "kpis": [], "assumptions": [], "risks": [], "testing_recommendations": []}


def params(**kw):
    p = {"channel": "linkedin", "format": "post", "variations": 2, "cta": "Book a demo",
         "brand_voice": "practical", "primary_message": "pm", "required_phrases": "",
         "restricted_phrases": "", "product": "InsightHub Pro"}
    p.update(kw)
    return p


def test_linkedin_generation():
    assets = generate_local_assets(BRIEF, params())
    assert len(assets) == 2
    assert all("Book a demo" in a["body"] for a in assets)
    assert all(a["asset_type"] == "linkedin_post" for a in assets)


def test_email_generation_sections_present():
    assets = generate_local_assets(BRIEF, params(channel="email"))
    types = [a["asset_type"] for a in assets]
    assert "email_subject" in types and "email_preview" in types and "email_body" in types


def test_x_respects_280_limit():
    assets = generate_local_assets(BRIEF, params(channel="x", variations=3))
    assert all(len(a["body"]) <= 280 for a in assets)


def test_search_ad_limits():
    assets = generate_local_assets(BRIEF, params(channel="search_ad"))
    for a in assets:
        if a["asset_type"] == "search_ad_headline":
            assert len(a["body"]) <= 30
        if a["asset_type"] == "search_ad_description":
            assert len(a["body"]) <= 90


def test_restricted_phrase_removed():
    assets = generate_local_assets(BRIEF, params(channel="landing_page",
                                                 restricted_phrases="evidence"))
    joined = " ".join(a["body"].lower() for a in assets)
    assert "evidence" not in joined.replace("[removed-restricted-term]", "")


def test_required_phrase_injected():
    assets = generate_local_assets(BRIEF, params(channel="faq", required_phrases="fair pricing"))
    assert any("fair pricing" in a["body"] for a in assets)


def test_validate_flags_unsupported_claims():
    asset = {"asset_type": "linkedin_post", "title": "t",
             "body": "Our users see a 300% increase guaranteed. Book a demo."}
    v = validate_asset(asset, params(), BRIEF)
    assert v["unsupported_claims_flagged"]


def test_validate_number_from_brief_not_flagged():
    brief = dict(BRIEF)
    brief["supporting_evidence"] = ["12 records mention pricing"]
    asset = {"asset_type": "linkedin_post", "title": "t", "body": "Backed by 12 records."}
    v = validate_asset(asset, params(), brief)
    assert v["unsupported_claims_flagged"] == []


def test_validate_length_check():
    asset = {"asset_type": "x_post", "title": "t", "body": "x" * 300}
    v = validate_asset(asset, params(), BRIEF)
    assert v["platform_length"]["ok"] is False


def test_near_duplicate_detection():
    a = [{"body": "identical text here"}, {"body": "identical text here"},
         {"body": "completely different content about something else entirely"}]
    pairs = flag_near_duplicates(a)
    assert pairs == [[0, 1]]


def test_edit_one_asset_does_not_touch_others(db):
    ds_id = db.create_dataset("d", "csv", "own_customers", None, {}, 0)
    cid = db.create_campaign("c", {"campaign_name": "c"}, ds_id, None)
    bid, _ = db.save_brief(cid, BRIEF, [])
    id1 = db.create_asset(bid, cid, "uid-1", "linkedin_post", "T1", "body one", "cta", "", {})
    id2 = db.create_asset(bid, cid, "uid-2", "email_body", "T2", "body two", "cta", "", {})
    new_id = db.update_asset_as_new_version("uid-1", "T1 edited", "new body", "cta", "", {})
    a2 = db.get_asset(id2)
    assert a2["version"] == 1 and a2["body"] == "body two"
    a1new = db.get_asset(new_id)
    assert a1new["version"] == 2 and a1new["asset_uid"] == "uid-1"
