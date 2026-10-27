import pytest

from modules.campaign_builder import build_local_brief, regenerate_section
from modules.models import CampaignSetup


SETUP = {"campaign_name": "Growth Q4", "product_service": "InsightHub Pro",
         "business_objective": "more demos", "target_market": "B2B ops teams",
         "audience_segment": "Enterprise", "geographic_market": "NA",
         "brand_positioning": "evidence-led", "budget": "$40k", "duration": "6 weeks",
         "channels": ["linkedin", "email"], "desired_action": "Book a demo",
         "brand_voice": "practical", "restrictions": "no fake numbers",
         "competitor_context": ""}

INSIGHTS = [
    {"id": 1, "title": "Recurring pain point: billing", "description": "billing errors seen",
     "category": "pain_point", "supporting_count": 3, "segments": ["Enterprise"],
     "origin": "data_derived", "confidence": "high"},
    {"id": 2, "title": "Satisfaction driver: support", "description": "customers love support responsiveness",
     "category": "satisfaction_driver", "supporting_count": 4, "segments": ["Enterprise"],
     "origin": "data_derived", "confidence": "high"},
    {"id": 3, "title": "Churn / competitor-switching signals", "description": "switching talk",
     "category": "churn_risk", "supporting_count": 2, "segments": [], "origin": "data_derived",
     "confidence": "medium"},
]
METRICS = {"classified_records": 9, "average_rating": 3.4,
           "analysis_period": {"start": "2026-01-01", "end": "2026-06-01"},
           "sentiment_by_segment": {"Enterprise": {"positive": 3, "negative": 1}}}


def test_setup_validation():
    with pytest.raises(Exception):
        CampaignSetup(campaign_name="x", product_service="", business_objective="", target_market="")
    s = CampaignSetup(**{k: v for k, v in SETUP.items()})
    assert s.campaign_name == "Growth Q4"


def test_brief_uses_selected_insights():
    out = build_local_brief(SETUP, INSIGHTS, METRICS)
    brief = out["brief"]
    assert out["method"] == "local_template"
    assert out["insight_ids"] == [1, 2, 3]
    joined = str(brief)
    assert "support" in joined.lower()
    assert any("billing" in p.lower() or "support" in p.lower() for p in brief["messaging_pillars"])
    assert any("n=3" in e or "n=4" in e for e in brief["supporting_evidence"])


def test_persona_labelled_inferred():
    brief = build_local_brief(SETUP, INSIGHTS, METRICS)["brief"]
    assert brief["persona"]["inferred"] is True
    assert "NOT present" in brief["persona"]["demographics_note"]


def test_no_promised_conversion_numbers():
    brief = build_local_brief(SETUP, INSIGHTS, METRICS)["brief"]
    text = str(brief).lower()
    assert "guarantee" not in text
    assert "conversion rate of" not in text


def test_all_18_sections_present():
    brief = build_local_brief(SETUP, INSIGHTS, METRICS)["brief"]
    required = ["overview", "business_objective", "persona", "audience_needs",
                "motivations_objections", "value_proposition", "usp", "messaging_pillars",
                "supporting_evidence", "recommended_channels", "channel_strategy",
                "content_themes", "cta_strategy", "timeline", "kpis", "assumptions", "risks",
                "testing_recommendations"]
    for r in required:
        assert r in brief, r


def test_regenerate_single_section_preserves_rest():
    brief = build_local_brief(SETUP, INSIGHTS, METRICS)["brief"]
    updated = regenerate_section(brief, "usp", "New USP text")
    assert updated["usp"] == "New USP text"
    assert updated["overview"] == brief["overview"]
    assert updated["messaging_pillars"] == brief["messaging_pillars"]
    with pytest.raises(ValueError):
        regenerate_section(brief, "nonexistent", "x")
