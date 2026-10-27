"""Campaign brief generation (local template-assisted + AI-assisted paths).

Local mode builds the brief deterministically from actual saved insights and is
labelled method='local_template' so it can never be mistaken for LLM output.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from modules.models import CampaignBriefSchema, PersonaSchema


def _pick(insights: List[Dict[str, Any]], category: str) -> List[Dict[str, Any]]:
    return [i for i in insights if i["category"] == category]


def build_local_brief(setup: Dict[str, Any], insights: List[Dict[str, Any]],
                      metrics: Dict[str, Any]) -> Dict[str, Any]:
    """Template-assisted brief fully grounded in the supplied insight records."""
    pain = _pick(insights, "pain_point")
    drivers = _pick(insights, "satisfaction_driver")
    churn = _pick(insights, "churn_risk")
    requests = _pick(insights, "feature_request")
    opportunity = _pick(insights, "marketing_opportunity")

    segment = setup.get("audience_segment") or "all measured segments"
    seg_stats = (metrics.get("sentiment_by_segment", {}) or {}).get(segment, {})
    seg_note = ""
    if seg_stats:
        tot = sum(seg_stats.values())
        seg_note = (f"Measured sentiment mix for '{segment}' in this dataset: "
                    f"{seg_stats.get('positive',0)}/{tot} positive, "
                    f"{seg_stats.get('negative',0)}/{tot} negative.")

    persona = PersonaSchema(
        name=f"{segment} Buyer (inferred)",
        segment=segment,
        demographics_note=("Demographics are NOT present in the feedback dataset; this persona is an "
                           "inferred marketing hypothesis built from stated needs, pains and language."),
        needs_goals=[i["title"] for i in drivers[:4]] or ["Efficient, reliable analytics workflows"],
        pain_points=[i["title"].replace("Recurring pain point: ", "") for i in pain[:5]],
        motivations=[i["description"][:160] for i in drivers[:2]],
        objections=[i["description"][:160] for i in churn[:2]] + [i["description"][:160] for i in requests[:1]],
        preferred_channels=setup.get("channels", [])[:4],
        messaging_preferences=(f"{setup.get('brand_voice') or 'Practical, evidence-led'} tone; lead with "
                               "verified outcomes, acknowledge known limitations."),
        evidence_refs=[i["title"] for i in (pain + drivers + churn)[:6]],
        inferred=True)

    pillars = []
    for d in drivers[:3]:
        pillars.append(f"Evidenced strength - {d['title']} ({d['supporting_count']} supporting records)")
    for o in opportunity[:1]:
        pillars.append(f"Differentiation angle - {o['title']}")
    if not pillars:
        pillars = [f"Address: {p['title']}" for p in pain[:3]] or ["Value communication based on collected feedback"]

    channels = setup.get("channels") or ["linkedin", "email"]
    channel_strategy = []
    rationale = {
        "linkedin": "B2B decision-makers discussing tools; supports long-form proof points.",
        "email": "Direct channel for re-engagement and objection handling with measurable opens/clicks.",
        "instagram": "Visual product storytelling for lighter-touch brand awareness.",
        "facebook": "Community building and retargeting pools.",
        "x": "Real-time conversation and quick feature announcements (280-char discipline).",
        "video": "Demonstrates workflow fixes addressing top complaint clusters.",
        "search_ad": "Captures active demand from prospects comparing solutions.",
        "social_ad": "Amplifies proven organic messages to lookalike audiences.",
        "landing_page": "Central conversion hub matching ad message to action.",
        "calendar": "Sustains cadence across the campaign window.",
        "faq": "Pre-empts measured objections.",
        "ab_test": "Validates message variants before scale.",
    }
    for ch in channels:
        channel_strategy.append(f"{ch}: {rationale.get(ch, 'Selected by campaign owner; align content formats accordingly.')} "
                                f"(Objective: {setup.get('business_objective','')})")

    timeline = []
    dur = (setup.get("duration") or "6 weeks").lower()
    weeks = 6
    import re as _re
    m = _re.search(r"(\d+)", dur)
    if m:
        weeks = max(2, int(m.group()))
    phase_w = max(1, weeks // 3)
    timeline = [f"Weeks 1-{phase_w}: Insight validation + creative production against top evidence themes",
                f"Weeks {phase_w+1}-{2*phase_w}: Launch priority channels, A/B test messaging pillars",
                f"Weeks {2*phase_w+1}-{weeks}: Scale winning variants, publish objection-handling FAQ content"]

    kpis = ["Sentiment-weighted engagement rate per channel (baseline set at launch)",
            "Click-through to landing page vs prior period",
            "Marketing-qualified sign-ups / demo requests attributed to campaign",
            "Email open + reply rates for re-engagement sequence"]
    if metrics.get("average_rating") is not None:
        kpis.append(f"Post-campaign product rating movement from current baseline {metrics['average_rating']}")

    assumptions = [
        "Insight sample reflects the target segment adequately (verify coverage before heavy spend).",
        f"Dataset covers {metrics.get('classified_records', 0)} classified records from "
        f"{metrics.get('analysis_period', {}).get('start', 'n/a')} to "
        f"{metrics.get('analysis_period', {}).get('end', 'n/a')}.",
        "No external market-size or competitor pricing figures were used - none were provided/verified.",
    ]
    risks = [f"Over-indexing on loudest complaint topic may skew message; pain themes: "
             f"{', '.join(p['title'] for p in pain[:2]) or 'n/a'}",
             "Churn signals indicate billing/onboarding friction that creative cannot fix alone.",
             "Small-sample insights (confidence=low) should not anchor paid claims."]
    testing = ["A/B test pillar-led vs objection-led subject lines",
               "Test quote-based social proof vs feature-list creative",
               "Hold-out segment to measure organic vs campaign lift"]

    overview = (f"Campaign '{setup.get('campaign_name','Unnamed')}' supports {setup.get('product_service','the product')} "
                f"for {setup.get('target_market','the target market')}. "
                f"Built from {len(insights)} evidence-backed insights. {seg_note}")

    value_prop = (drivers[0]["description"] if drivers else
                  "Reliable customer-intelligence workflows validated by user feedback.")
    usp = (opportunity[0]["description"][:280] if opportunity else
           "Differentiation drawn only from attributes customers explicitly praised in feedback data.")

    cta = setup.get("desired_action") or "Request a guided demo"
    brief = CampaignBriefSchema(
        overview=overview,
        business_objective=setup.get("business_objective", ""),
        persona=persona,
        audience_needs=[i["title"] for i in (pain + requests)[:6]],
        motivations_objections=[i["title"] for i in (drivers + churn)[:6]],
        value_proposition=value_prop,
        usp=usp,
        messaging_pillars=pillars,
        supporting_evidence=[f"{i['title']} (n={i['supporting_count']})" for i in insights[:8]],
        recommended_channels=channels,
        channel_strategy=channel_strategy,
        content_themes=[i["title"] for i in (drivers + pain + requests)[:7]],
        cta_strategy=f"Primary CTA: '{cta}'. Match CTA to funnel stage per channel; measure lift vs baseline.",
        timeline=timeline, kpis=kpis, assumptions=assumptions, risks=risks,
        testing_recommendations=testing)
    return {"brief": brief.model_dump(), "method": "local_template",
            "insight_ids": [i["id"] for i in insights]}


def regenerate_section(brief_content: Dict[str, Any], section: str,
                       new_value: Any) -> Dict[str, Any]:
    """Replace one section without touching the rest of the brief."""
    if section not in brief_content:
        raise ValueError(f"Unknown brief section '{section}'")
    updated = dict(brief_content)
    updated[section] = new_value
    # re-validate whole document so partial edits cannot corrupt the schema
    return CampaignBriefSchema.model_validate(updated).model_dump()
