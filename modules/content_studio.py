"""Multichannel content generation + quality controls (local template mode and AI mode)."""
from __future__ import annotations

import difflib
import re
from typing import Any, Dict, List

PLATFORM_LIMITS = {"x": 280, "linkedin": 3000, "instagram": 2200, "facebook": 5000,
                   "search_ad_headline": 30, "search_ad_description": 90}

# Phrases that assert facts the pipeline cannot verify from supplied data
UNSUPPORTED_CLAIM_PATTERNS = [
    r"\b\d+(?:\.\d+)?\s?%(\s+(increase|lift|boost|of users|more))?",
    r"\bguarantee[d]?\b", r"\b#\s?1\b", r"\bbest[- ]in[- ]class\b",
    r"\bworld[- ]class\b", r"\bguaranteed results\b", r"\bproven to double\b",
    r"\btrust(ed)? by (over\s)?\d+", r"\bno\.1\b",
]


def _pillar_text(brief: Dict[str, Any]) -> str:
    pillars = brief.get("messaging_pillars") or []
    return pillars[0] if pillars else "customer-validated value"


def _pain_text(brief: Dict[str, Any]) -> str:
    pains = (brief.get("persona", {}) or {}).get("pain_points") or []
    return pains[0] if pains else "workflow friction"


def generate_local_assets(brief: Dict[str, Any], params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Template-assisted generation grounded in the brief's evidence fields."""
    product = params.get("product") or "our platform"
    cta = params.get("cta") or (brief.get("cta_strategy", "").split("'")[1]
                                if "'" in brief.get("cta_strategy", "") else "Book a demo")
    voice = params.get("brand_voice") or "practical, evidence-led"
    pillar = _pillar_text(brief)
    pain = _pain_text(brief)
    vp = brief.get("value_proposition", "")
    n = int(params.get("variations", 2))
    channel = params.get("channel", "linkedin")
    fmt = params.get("format", "post")
    primary_msg = params.get("primary_message") or vp or pillar
    required = [p.strip() for p in (params.get("required_phrases") or "").split(",") if p.strip()]
    restricted = [p.strip().lower() for p in (params.get("restricted_phrases") or "").split(",") if p.strip()]

    assets: List[Dict[str, Any]] = []

    def add(atype: str, title: str, body: str, call: str = "", notes: str = ""):
        for phrase in restricted:
            # replace ALL occurrences (repeated calls until exhausted) so a
            # restricted term can never leak into generated content
            lowered = body.lower()
            guard = 0
            while phrase and phrase in lowered and guard < 50:
                idx = lowered.find(phrase)
                body = (body[:idx] + "[removed-restricted-term]" + body[idx + len(phrase):])
                lowered = body.lower()
                guard += 1
        for phrase in required:
            if phrase not in body:
                body = f"{body}\n\n[{phrase}]"
        assets.append({"asset_type": atype, "title": title, "body": body.strip(),
                       "cta": call, "notes": notes})

    if channel == "email" or fmt in ("email",):
        for v in range(1, n + 1):
            add("email_subject", f"Subject option {v}",
                f"{primary_msg[:70]} - see what customers report about {product}")
        add("email_preview", "Preview text",
            f"Real feedback themes on {_pain_text(brief)} - and how {product} responds.")
        add("email_body", "Initial outreach email",
            f"Hi {{first_name}},\n\nCustomers like you told us their biggest frustration was "
            f"\"{pain}\". {vp}\n\nOur latest insight programme shows: {pillar}.\n\n"
            f"Would a 20-minute walkthrough help? {cta}.\n\nBest,\n{{sender_name}}",
            call=cta, notes="Local template; merge fields {{...}} must be mapped before any send.")
        add("email_body", "Re-engagement email",
            f"Hi {{first_name}},\n\nWe heard feedback about {pain} and acted on it. "
            f"{vp}\n\nIf pricing or migration worry you, we can walk through both honestly. {cta}.",
            call=cta, notes="Targets measured objection themes; review before sending.")
    elif channel == "x":
        for v in range(1, n + 1):
            body = (f"Teams told us {pain} hurts. Here's what the feedback data says: "
                    f"{pillar[:160]} {cta}")[:280]
            add("x_post", f"X post variant {v}", body, call=cta)
    elif channel in ("instagram", "facebook"):
        for v in range(1, n + 1):
            add(f"{channel}_post", f"{channel.title()} caption {v}",
                f"What customers actually say about {product}:\n\n\u2022 {pillar}\n"
                f"\u2022 Real pain, real fix: {pain}\n\n{primary_msg}\n\n{cta}\n\n"
                f"#CustomerFeedback #MarketInsights #{product.replace(' ','')}"[:PLATFORM_LIMITS[channel]])
    elif channel in ("search_ad",):
        for v in range(1, n + 1):
            add("search_ad_headline", f"Search headline {v}",
                f"{product}: Built On Real Feedback"[:30])
            add("search_ad_description", f"Search description {v}",
                f"{pillar[:88]} {cta}"[:90], call=cta)
    elif channel == "social_ad":
        for v in range(1, n + 1):
            add("social_ad_primary", f"Social ad primary text {v}",
                f"Frustrated by {pain}? Customers rate {product} for {pillar}. {cta}", call=cta)
    elif channel == "landing_page":
        add("landing_headline", "Landing headline", f"{primary_msg[:80]}")
        add("landing_description", "Landing description",
            f"{vp}\n\nEvidence base: {len(brief.get('supporting_evidence', []))} tracked insight themes "
            f"from customer feedback.")
        add("benefit_statement", "Benefit statement",
            f"Turn raw customer feedback into decisions: {pillar}.")
    elif channel == "faq":
        add("faq", "FAQ - Why should I trust the claims?",
            f"Q: Why should I trust your claims?\nA: Every statement traces to labelled customer "
            f"feedback records ({len(brief.get('supporting_evidence', []))} insight themes). We do "
            f"not publish unverified numbers.")
        add("faq", "FAQ - What about pricing concerns?",
            f"Q: Is it expensive compared to alternatives?\nA: Pricing complaints appear in our "
            f"feedback data; contact us for a transparent quote tailored to team size.")
    elif channel == "video":
        add("video_script", "Short-form video script (30s)",
            f"[HOOK 0-5s] '{pain}' sound familiar?\n[PROBLEM 5-15s] Customers describe exactly this "
            f"friction in their own words.\n[SOLUTION 15-25s] {vp}\n[CTA 25-30s] {cta}.")
    elif channel == "calendar":
        for week in range(1, 4):
            add("calendar_entry", f"Week {week} content slot",
                f"Publish: {pillar} | Format: proof-point carousel | Channel: {channel} | "
                f"KPI: engagement vs baseline")
    elif channel == "ab_test":
        add("ab_variant", "Variant A - benefit led", f"{primary_msg}. {cta}", call=cta)
        add("ab_variant", "Variant B - pain led", f"Stop losing time to {pain}. {vp} {cta}", call=cta)
    else:  # linkedin default
        for v in range(1, n + 1):
            add("linkedin_post", f"LinkedIn post variant {v}",
                f"What does customer feedback really say about {product}?\n\n"
                f"We analysed incoming reviews and one theme dominates: {pillar}.\n\n"
                f"At the same time, buyers consistently flag: {pain}.\n\n"
                f"Our answer: {vp}\n\n{primary_msg}\n\n{cta}", call=cta)
    return assets


def validate_asset(asset: Dict[str, Any], params: Dict[str, Any],
                   brief: Dict[str, Any]) -> Dict[str, Any]:
    """Configurable quality checks. Returns dict of check -> pass/violation detail."""
    results: Dict[str, Any] = {}
    body = asset.get("body", "")
    title = asset.get("title", "")
    full = f"{title}\n{body}"

    results["fields_present"] = bool(body.strip()) and bool(title.strip())

    atype = asset.get("asset_type", "")
    limit = None
    if atype == "x_post":
        limit = PLATFORM_LIMITS["x"]
    elif atype.startswith("search_ad_headline"):
        limit = PLATFORM_LIMITS["search_ad_headline"]
    elif atype.startswith("search_ad_description"):
        limit = PLATFORM_LIMITS["search_ad_description"]
    if params.get("max_length"):
        try:
            custom = int(params["max_length"])
            limit = min(limit, custom) if limit else custom
        except (TypeError, ValueError):
            results["max_length_valid"] = False
    if limit is not None:
        results["platform_length"] = {"limit": limit, "actual": len(body),
                                      "ok": len(body) <= limit}

    claims = [m.group(0) for pat in UNSUPPORTED_CLAIM_PATTERNS
              for m in re.finditer(pat, full, flags=re.I)]
    allowed_numbers = set(re.findall(r"\d+", str(brief)))
    numeric_claims = [c for c in claims
                      if not any(num in allowed_numbers for num in re.findall(r"\d+", c))]
    results["unsupported_claims_flagged"] = numeric_claims

    cta_expected = (params.get("cta") or "").strip().lower()
    if cta_expected:
        results["cta_present"] = cta_expected.split()[0] in body.lower() if cta_expected else True

    req = [p.strip() for p in (params.get("required_phrases") or "").split(",") if p.strip()]
    missing = [p for p in req if p.lower() not in full.lower()]
    results["required_phrases_missing"] = missing
    res = [p.strip().lower() for p in (params.get("restricted_phrases") or "").split(",") if p.strip()]
    found_bad = [p for p in res if p in full.lower()]
    results["restricted_phrases_found"] = found_bad

    pains = (brief.get("persona", {}) or {}).get("pain_points", [])
    reflected = any(p.lower()[:15] in full.lower() for p in pains) if pains else None
    results["pain_point_reflected"] = reflected
    return results


def flag_near_duplicates(assets: List[Dict[str, Any]], threshold: float = 0.85) -> List[List[int]]:
    """Identify near-duplicate pairs among generated variants (practical similarity check)."""
    dupes = []
    for i in range(len(assets)):
        for j in range(i + 1, len(assets)):
            ratio = difflib.SequenceMatcher(None, assets[i]["body"].lower(),
                                            assets[j]["body"].lower()).ratio()
            if ratio >= threshold:
                dupes.append([i, j])
    return dupes
