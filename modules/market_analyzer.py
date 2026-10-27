"""Market intelligence: competitor comparison and evidence-tiered synthesis."""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Dict, List


def competitor_comparison(records: List[Dict[str, Any]],
                          classifications: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compare sentiment when competitor data exists (explicit column or in-text mention).

    Returns {'available': bool, 'reason': str, 'table': [...], 'quotes': {...}}.
    Never fabricates external market facts - only what the supplied records say.
    """
    by_id = {r["id"]: r for r in records}
    comp_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for c in classifications:
        rec = by_id.get(c["record_id"], {})
        comp = rec.get("competitor")
        if not comp:
            m = re.search(r"\b(CompetitorX|DataPulse|[A-Z][A-Za-z]+\s?(Inc\.|Corp\.|Ltd\.))\b",
                          rec.get("text", ""))
            comp = m.group(1) if m else None
        if comp:
            comp_groups[comp].append({"sentiment": c["sentiment"], "rec": rec})

    if not comp_groups:
        return {"available": False,
                "reason": ("No competitor column and no recognisable competitor mentions were found "
                           "in the selected dataset. Competitor analysis is intentionally disabled "
                           "rather than fabricated."),
                "table": [], "quotes": {}}

    table = []
    quotes: Dict[str, List[str]] = {}
    for comp, items in comp_groups.items():
        counts = defaultdict(int)
        for it in items:
            counts[it["sentiment"]] += 1
        ratings = [it["rec"]["rating"] for it in items if it["rec"].get("rating") is not None]
        table.append({
            "competitor": comp,
            "mentions": len(items),
            "positive": counts.get("positive", 0),
            "negative": counts.get("negative", 0),
            "other": len(items) - counts.get("positive", 0) - counts.get("negative", 0),
            "avg_rating_when_rated": round(sum(ratings) / len(ratings), 2) if ratings else None,
        })
        quotes[comp] = [f'{it["rec"]["external_ref"]}: "{it["rec"]["text"][:150]}"'
                        for it in items[:6] if it["rec"].get("external_ref")]
    return {"available": True, "reason": "Derived from supplied records only.",
            "table": table, "quotes": quotes}


def market_intelligence_bundle(records: List[Dict[str, Any]], classifications: List[Dict[str, Any]],
                               insights: List[Dict[str, Any]], notes: List[Dict[str, Any]],
                               metrics: Dict[str, Any]) -> Dict[str, List[Dict[str, str]]]:
    """Separate findings into three explicit evidence tiers."""
    observed: List[Dict[str, str]] = []
    interpreted: List[Dict[str, str]] = []
    hypotheses: List[Dict[str, str]] = []

    for ins in insights:
        entry = {"title": ins["title"], "detail": ins["description"],
                 "evidence_count": str(ins["supporting_count"])}
        if ins["origin"] == "data_derived":
            observed.append(entry)
        elif ins["origin"] == "ai_interpreted":
            interpreted.append(entry)
        else:
            hypotheses.append(entry)

    for n in notes:
        observed.append({"title": f"User note: {n['title']}", "detail": n["body"][:300],
                         "evidence_count": "user-supplied"})

    def _has_pricing(text: str) -> bool:
        return bool(re.search(r"pric|expensive|overpriced|cost|budget", (text or "").lower()))

    pricing_neg = [c for c in classifications
                   if c["sentiment"] == "negative"
                   and (_has_pricing(c.get("evidence", "")) or _has_pricing(" ".join(c.get("pain_points", []))))]
    if pricing_neg:
        observed.append({"title": f"Pricing friction observed ({len(pricing_neg)} records)",
                         "detail": ("Negative records explicitly reference price/cost concerns. "
                                    "Derived only from the supplied feedback records."),
                         "evidence_count": str(len(pricing_neg))})
        interpreted.append({"title": "Price sensitivity interpretation",
                            "detail": ("Clusters of pricing complaints suggest a value-communication "
                                       "gap rather than proven market-wide price unfairness. "
                                       "Interpretation of observed data - not an external fact."),
                            "evidence_count": str(len(pricing_neg))})
        hypotheses.append({"title": "Flexible-entry-tier opportunity",
                           "detail": ("A small-business entry tier could neutralise the most common "
                                      "switching trigger. Requires validation - NOT measured."),
                           "evidence_count": "hypothesis"})

    gaps = [c for c in classifications if c.get("feature_requests")]
    if gaps:
        interpreted.append({"title": f"Feature/service gaps flagged ({len(gaps)} records)",
                            "detail": ("Wish-list language indicates unmet needs in the current "
                                       "offering. Interpretation of supplied records only."),
                            "evidence_count": str(len(gaps))})

    return {"observed_evidence": observed, "ai_interpretation": interpreted,
            "strategic_hypothesis": hypotheses,
            "note": ("Nothing here asserts independently verified external market size, share or "
                     "pricing. Competitor statements reflect what supplied customers said.")}
