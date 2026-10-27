"""Evidence-backed insight extraction from classified records."""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Dict, List

from modules.models import InsightItem
from modules.sentiment_engine import SWITCH_MARKERS


def _rec_lookup(records: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    return {r["id"]: r for r in records}


def extract_insights(records: List[Dict[str, Any]], classifications: List[Dict[str, Any]],
                    metrics: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build insights strictly from actual record evidence.

    Each insight carries record ids, quoted evidence, counts, segments,
    confidence (evidence strength) and origin=data_derived.
    """
    by_id = _rec_lookup(records)
    n = max(len(classifications), 1)
    insights: List[InsightItem] = []

    def group_by_key(key_fn, label_fn, category, min_count=2, implication="", action=""):
        groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for c in classifications:
            k = key_fn(c)
            if not k:
                continue
            groups[k].append(c)
        out = []
        for k, items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            if len(items) < min_count:
                continue
            rec_ids = [i["record_id"] for i in items]
            segs = sorted({by_id[r]["segment"] for r in rec_ids
                           if r in by_id and by_id[r].get("segment")})
            ev = [f'{by_id[r]["external_ref"]}: "{by_id[r]["text"][:140]}"'
                  for r in rec_ids[:5] if r in by_id]
            pct = round(100 * len(items) / n)
            conf = "high" if len(items) >= max(3, n * 0.1) else ("medium" if len(items) >= 3 else "low")
            out.append(label_fn(k, items, rec_ids, segs, ev, pct, conf))
        return out

    # 1. Pain points: negative records grouped by main topic
    neg_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for c in classifications:
        if c["sentiment"] == "negative":
            neg_groups[c.get("main_topic") or "general dissatisfaction"].append(c)
    for topic, items in sorted(neg_groups.items(), key=lambda kv: -len(kv[1])):
        rec_ids = [i["record_id"] for i in items]
        segs = sorted({by_id[r]["segment"] for r in rec_ids if r in by_id and by_id[r].get("segment")})
        ev = [f'{by_id[r]["external_ref"]}: "{by_id[r]["text"][:160]}"' for r in rec_ids[:5] if r in by_id]
        pct = round(100 * len(items) / n)
        insights.append(InsightItem(
            title=f"Recurring pain point: {topic}",
            description=(f"{len(items)} negative feedback records ({pct}% of classified records) "
                         f"cluster around '{topic}'."),
            category="pain_point", evidence=ev, record_ids=rec_ids, supporting_count=len(items),
            segments=segs,
            business_implication=("High-frequency friction area likely affecting retention and "
                                  "purchase confidence." if pct >= 15 else
                                  "Localized friction; monitor whether it recurs across segments."),
            recommended_action=f"Investigate root cause behind '{topic}' complaints and prepare a "
                               "remediation/comms plan before campaign claims touch this area.",
            confidence="high" if len(items) >= max(3, n * 0.1) else ("medium" if len(items) >= 2 else "low"),
            origin="data_derived"))

    # 2. Satisfaction drivers: positive records grouped by topic
    pos_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for c in classifications:
        if c["sentiment"] == "positive":
            pos_groups[c.get("main_topic") or "general satisfaction"].append(c)
    for topic, items in sorted(pos_groups.items(), key=lambda kv: -len(kv[1])):
        rec_ids = [i["record_id"] for i in items]
        segs = sorted({by_id[r]["segment"] for r in rec_ids if r in by_id and by_id[r].get("segment")})
        ev = [f'{by_id[r]["external_ref"]}: "{by_id[r]["text"][:160]}"' for r in rec_ids[:5] if r in by_id]
        attrs = sorted({w for i in items for w in i.get("positive_attributes", [])})[:6]
        insights.append(InsightItem(
            title=f"Satisfaction driver: {topic}",
            description=(f"{len(items)} positive records mention '{topic}'. Recurring praised "
                         f"attributes: {', '.join(attrs) if attrs else 'n/a'}."),
            category="satisfaction_driver", evidence=ev, record_ids=rec_ids,
            supporting_count=len(items), segments=segs,
            business_implication="Validated strength that marketing copy can truthfully emphasise.",
            recommended_action=f"Feature '{topic}' proof points in campaign messaging with real quotes.",
            confidence="high" if len(items) >= max(3, n * 0.1) else "medium",
            origin="data_derived"))

    # 3. Feature requests
    fr_items = [c for c in classifications if c.get("feature_requests")]
    if fr_items:
        rec_ids = [i["record_id"] for i in fr_items]
        ev = [f'{by_id[r]["external_ref"]}: "{by_id[r]["text"][:160]}"' for r in rec_ids[:5] if r in by_id]
        segs = sorted({by_id[r]["segment"] for r in rec_ids if r in by_id and by_id[r].get("segment")})
        insights.append(InsightItem(
            title="Explicit feature requests detected",
            description=f"{len(fr_items)} records contain wish-list language (integration/offline/etc.).",
            category="feature_request", evidence=ev, record_ids=rec_ids,
            supporting_count=len(fr_items), segments=segs,
            business_implication="Unmet needs define whitespace for positioning vs competitors.",
            recommended_action="Prioritise the requested capabilities; avoid promising them in copy "
                               "until shipped.",
            confidence="medium" if len(fr_items) >= 3 else "low", origin="data_derived"))

    # 4. Churn / switching risk
    churn_items = [c for c in classifications
                   if "churn" in (c.get("customer_intent") or "")
                   or any(m in (c.get("evidence") or "").lower() for m in SWITCH_MARKERS)]
    if churn_items:
        rec_ids = [i["record_id"] for i in churn_items]
        ev = [f'{by_id[r]["external_ref"]}: "{by_id[r]["text"][:160]}"' for r in rec_ids[:5] if r in by_id]
        segs = sorted({by_id[r]["segment"] for r in rec_ids if r in by_id and by_id[r].get("segment")})
        insights.append(InsightItem(
            title="Churn / competitor-switching signals",
            description=(f"{len(churn_items)} records reference switching, cancellation, renewal "
                         "hesitation or competitor comparison."),
            category="churn_risk", evidence=ev, record_ids=rec_ids, supporting_count=len(churn_items),
            segments=segs,
            business_implication=("Retention exposure concentrated in these accounts/segments; "
                                  "objection-handling content is warranted."),
            recommended_action="Build re-engagement and objection-handling sequences targeting the "
                               "stated switching triggers (pricing, migration effort, billing).",
            confidence="high" if len(churn_items) >= 3 else "medium", origin="data_derived"))

    # 5. Segment-level skew (if any segment is disproportionately negative)
    seg_stats = metrics.get("sentiment_by_segment", {})
    for seg, d in seg_stats.items():
        tot = sum(d.values())
        if tot >= 3 and d.get("negative", 0) / tot >= 0.5:
            rec_ids = [c["record_id"] for c in classifications
                       if by_id.get(c["record_id"], {}).get("segment") == seg
                       and c["sentiment"] == "negative"]
            ev = [f'{by_id[r]["external_ref"]}: "{by_id[r]["text"][:140]}"' for r in rec_ids[:4] if r in by_id]
            insights.append(InsightItem(
                title=f"Segment risk: {seg}",
                description=(f"{d['negative']}/{tot} classified records from the '{seg}' segment are "
                             f"negative ({round(100*d['negative']/tot)}%)."),
                category="objection", evidence=ev, record_ids=rec_ids, supporting_count=d["negative"],
                segments=[seg],
                business_implication="This segment's objections should shape campaign targeting and FAQ copy.",
                recommended_action=f"Tailor pricing/value messaging for {seg}; validate with follow-up interviews.",
                confidence="medium", origin="data_derived"))

    # 6. Marketing opportunity hypothesis derived from praise + gaps
    top_pos = metrics.get("top_praise", [])
    top_neg = metrics.get("top_complaints", [])
    if top_pos:
        strengths = ", ".join(w for w, _ in top_pos[:3])
        weaknesses = ", ".join(w for w, _ in top_neg[:3]) or "no dominant complaint cluster"
        all_ids = [c["record_id"] for c in classifications if c["sentiment"] == "positive"][:8]
        insights.append(InsightItem(
            title="Positioning opportunity (hypothesis)",
            description=(f"Customers praise {strengths} while complaining about {weaknesses}. "
                         "A campaign that leads with the praised differentiators while honestly "
                         "acknowledging/mitigating the complaint areas has credible ground to own."),
            category="marketing_opportunity",
            evidence=[f'{by_id[r]["external_ref"]}: "{by_id[r]["text"][:120]}"'
                      for r in all_ids if r in by_id][:5],
            record_ids=all_ids, supporting_count=len(all_ids),
            segments=[], business_implication="Differentiation must rest on evidenced strengths only.",
            recommended_action="Validate the positioning angle with a small message-testing panel "
                               "before scaling spend.",
            confidence="medium", origin="hypothesis"))

    return [i.model_dump() for i in insights]
