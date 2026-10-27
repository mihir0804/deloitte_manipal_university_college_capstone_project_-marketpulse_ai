"""Deterministic local sentiment analysis, topic extraction and quantitative metrics.

Local Analysis Mode is rule-based and transparent: it never claims LLM inference.
Records it cannot confidently classify are labelled 'uncertain' or 'mixed'.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple

from modules.models import SENTIMENT_LABELS

POSITIVE_WORDS = {
    "love", "excellent", "great", "fantastic", "amazing", "smooth", "intuitive", "fast",
    "helpful", "reliable", "standout", "unique", "improved", "improvement", "value",
    "responsive", "easy", "happy", "satisfied", "satisfaction", "best", "outstanding",
    "perfect", "recommend", "saved", "save", "fixed", "awesome", "wonderful", "good",
    "positive", "solid", "efficient", "professional", "useful", "like",
}
NEGATIVE_WORDS = {
    "hate", "terrible", "awful", "crash", "crashing", "broken", "slow", "confusing",
    "frustrating", "expensive", "bug", "bugs", "fail", "fails", "failing", "poor",
    "bad", "worst", "disappointing", "unhelpful", "difficult", "issue", "issues",
    "problem", "problems", "complaint", "billed", "unclear", "useless", "wrong",
    "risky", "costly", "lag", "laggy", "error", "errors", "lost", "cut", "missing",
    "overpriced", "annoying", "unreliable", "postponing", "cancellation",
}
FEATURE_REQUEST_MARKERS = ["wish", "would love", "i want", "please add", "integration",
                          "add support", "feature request", "if only", "need an", "need a",
                          "consider adding"]
SWITCH_MARKERS = ["switch", "churn", "cancel", "leave", "competitor", "alternative",
                  "migration", "moving to", "downgrade", "not renewing", "postpone renewal"]

STOPWORDS = set("""a an the and or but if then than that this these those i you he she it we they
me him her us them my your his its our their of in on at to for with without from by as is are was
were be been being do does did doing have has had having not no so too very can will just about
into over after before between under out up down off again once here there all any both each few
more most other some such only own same s t don now d ll m o re ve y ain aren couldn didn doesn
hadn hasn haven isn ma mightn mustn shouldn wasn weren won wouldn""".split())

# Domain-ish bigrams worth surfacing as topics even when single tokens are stopwords
TOPIC_PHRASES = [
    "customer support", "data export", "mobile app", "free trial", "pricing plan",
    "real time", "team collaboration", "sentiment analysis", "onboarding flow",
    "slack integration", "single sign", "pdf export", "dashboard export", "api",
    "performance", "documentation", "notifications", "renewal", "billing", "integration",
    "reports", "dashboard", "pricing", "support", "onboarding", "export", "crash",
]


def _tokens(text: str) -> List[str]:
    return re.findall(r"[a-zA-Z']+", text.lower())


def classify_local(text: str, rating: Optional[float] = None) -> Dict[str, Any]:
    """Rule-based classification with explicit uncertainty handling."""
    toks = _tokens(text)
    pos = sum(1 for t in toks if t in POSITIVE_WORDS)
    neg = sum(1 for t in toks if t in NEGATIVE_WORDS)
    score = pos - neg

    label: str
    confidence: float
    method_parts = ["lexicon"]
    if rating is not None:
        method_parts.append("rating")
        # Combine lexicon with rating indicator (normalized -1..1 around midpoint 3)
        rating_signal = (rating - 3.0) / 2.0
        combined = 0.5 * (score / max(pos + neg, 1)) + 0.5 * rating_signal
        if abs(score) <= 1 and pos + neg == 0:
            label = "positive" if rating >= 4 else ("negative" if rating <= 2 else "neutral")
            confidence = 0.55
        elif score != 0 and max(pos, neg) >= 2 and (pos == 0 or neg == 0):
            # overwhelming one-sided lexical evidence outranks a weak/contradicting
            # numeric rating (e.g. 'excellent work' rated 3 stays positive)
            label = "positive" if score > 0 else "negative"
            confidence = min(0.9, 0.5 + 0.1 * max(pos, neg))
        elif combined > 0.25:
            label = "positive"; confidence = min(0.9, 0.5 + abs(combined))
        elif combined < -0.25:
            label = "negative"; confidence = min(0.9, 0.5 + abs(combined))
        else:
            label = "mixed" if pos and neg else "uncertain"
            confidence = 0.4
    else:
        if pos + neg == 0:
            label, confidence = "uncertain", 0.3
        elif score >= 1:
            # one clear positive marker (and no negative counter-evidence) is
            # sufficient evidence; 'uncertain' stays reserved for zero-signal text
            label, confidence = "positive", min(0.85, 0.45 + 0.1 * score)
        elif score <= -1:
            label, confidence = "negative", min(0.85, 0.45 + 0.1 * abs(score))
        else:
            label, confidence = "uncertain", 0.35

    topics = extract_topics(text)
    pain = [w for w in toks if w in NEGATIVE_WORDS]
    praise = [w for w in toks if w in POSITIVE_WORDS]
    lower = text.lower()
    requests = []
    if any(m in lower for m in FEATURE_REQUEST_MARKERS):
        requests.append("feature request mentioned")
    intent = ""
    if any(m in lower for m in SWITCH_MARKERS):
        intent = "possible churn / switching consideration"
    elif any(m in lower for m in ["buy", "upgrade", "renew", "trial", "purchase"]):
        intent = "purchase/renewal consideration"
    elif requests:
        intent = "feature seeking"

    return {
        "sentiment": label,
        "confidence": round(confidence, 2),
        "main_topic": topics[0] if topics else "",
        "pain_points": sorted(set(pain))[:6],
        "positive_attributes": sorted(set(praise))[:6],
        "feature_requests": requests,
        "customer_intent": intent,
        "evidence": text[:240],
        "method": "+".join(method_parts) + " rules (local)",
    }


def extract_topics(text: str, top_n: int = 3) -> List[str]:
    lower = text.lower()
    found = [p for p in TOPIC_PHRASES if p in lower]
    toks = [t for t in _tokens(text) if t not in STOPWORDS and len(t) > 3]
    freq = Counter(toks)
    words = [w for w, _ in freq.most_common(top_n)]
    ordered = []
    for item in found + words:
        if item not in ordered:
            ordered.append(item)
    return ordered[:top_n]


def compute_metrics(records: List[Dict[str, Any]], classifications: List[Dict[str, Any]]) -> Dict[str, Any]:
    """All quantitative metrics derived strictly from actual records."""
    rec_by_id = {r["id"]: r for r in records}
    n = len(classifications)
    counts = Counter(c["sentiment"] for c in classifications)
    percentages = {k: round(v * 100.0 / n, 1) if n else 0.0 for k, v in counts.items()}

    ratings = [rec_by_id[c["record_id"]]["rating"] for c in classifications
               if c.get("record_id") in rec_by_id and rec_by_id[c["record_id"]].get("rating") is not None]
    avg_rating = round(sum(ratings) / len(ratings), 2) if ratings else None
    rating_dist = Counter(int(r) for r in ratings) if ratings else {}

    by_product: Dict[str, Dict[str, int]] = defaultdict(lambda: Counter())
    by_segment: Dict[str, Dict[str, int]] = defaultdict(lambda: Counter())
    by_month: Dict[str, Dict[str, int]] = defaultdict(lambda: Counter())
    by_competitor: Dict[str, Dict[str, int]] = defaultdict(lambda: Counter())
    topic_counter: Counter = Counter()
    complaint_counter: Counter = Counter()
    praise_counter: Counter = Counter()

    for c in classifications:
        rec = rec_by_id.get(c["record_id"], {})
        lab = c["sentiment"]
        if rec.get("product"):
            by_product[rec["product"]][lab] += 1
        if rec.get("segment"):
            by_segment[rec["segment"]][lab] += 1
        if rec.get("review_date"):
            by_month[str(rec["review_date"])[:7]][lab] += 1
        comp = rec.get("competitor")
        if not comp:
            # competitor mention may appear inside text of market/competitor datasets
            m = re.search(r"\b(CompetitorX|DataPulse)\b", rec.get("text", ""))
            comp = m.group(1) if m else None
        if comp:
            by_competitor[comp][lab] += 1
        if c.get("main_topic"):
            topic_counter[c["main_topic"]] += 1
        for w in c.get("pain_points", []):
            complaint_counter[w] += 1
        for w in c.get("positive_attributes", []):
            praise_counter[w] += 1

    dates = sorted([r["review_date"] for r in records if r.get("review_date")])

    def _full(d: Dict[str, Any]) -> Dict[str, int]:
        """Normalise breakdown dicts so every sentiment label key always exists."""
        return {lab: int(d.get(lab, 0)) for lab in SENTIMENT_LABELS}

    return {
        "total_records": len(records),
        "classified_records": n,
        "sentiment_counts": dict(counts),
        "sentiment_percentages": percentages,
        "average_rating": avg_rating,
        "rating_distribution": {str(k): v for k, v in sorted(rating_dist.items())},
        "sentiment_by_product": {k: _full(v) for k, v in by_product.items()},
        "sentiment_by_segment": {k: _full(v) for k, v in by_segment.items()},
        "sentiment_over_time": {k: _full(v) for k, v in sorted(by_month.items())},
        "competitor_sentiment": {k: _full(v) for k, v in by_competitor.items()},
        "top_topics": topic_counter.most_common(12),
        "top_complaints": complaint_counter.most_common(10),
        "top_praise": praise_counter.most_common(10),
        "analysis_period": {"start": dates[0] if dates else None, "end": dates[-1] if dates else None},
    }


def run_local_analysis(records: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Classify valid records and compute metrics. Returns per-record results + metrics."""
    classifications = []
    for r in records:
        res = classify_local(r["text"], r.get("rating"))
        res["record_id"] = r["id"]
        classifications.append(res)
    metrics = compute_metrics(records, classifications)
    return classifications, metrics


LIMITATIONS_NOTE = (
    "Local Analysis Mode uses a configurable keyword lexicon plus rating indicators. "
    "It cannot reliably detect sarcasm, negation scope, or domain slang; low-evidence "
    "records are labelled 'uncertain' or 'mixed' rather than forced into a class."
)
