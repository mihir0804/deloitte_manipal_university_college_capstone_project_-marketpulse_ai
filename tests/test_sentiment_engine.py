import json

from modules.sentiment_engine import classify_local, compute_metrics, run_local_analysis


def rec(i, text, rating=None, **kw):
    r = {"id": i, "text": text, "rating": rating, "review_date": None, "product": None,
         "segment": None, "competitor": None, "external_ref": f"R{i}"}
    r.update(kw)
    return r


def test_positive_negative_classification():
    assert classify_local("I love it, excellent support!")["sentiment"] == "positive"
    assert classify_local("Terrible crashes, very frustrating")["sentiment"] == "negative"


def test_uncertain_when_no_evidence():
    out = classify_local("The system has a green button on page two")
    assert out["sentiment"] in ("uncertain", "mixed")
    assert out["confidence"] <= 0.5


def test_rating_indicator_used():
    out = classify_local("It arrived on tuesday", rating=5)
    assert out["sentiment"] == "positive"
    assert "rating" in out["method"]


def test_metrics_counts_and_percentages():
    records = [rec(1, "love great excellent", 5), rec(2, "terrible awful crash", 1),
               rec(3, "neutral statement here", 3)]
    classifications, metrics = run_local_analysis(records)
    total = sum(metrics["sentiment_counts"].values())
    assert total == 3 == metrics["classified_records"]
    pct_sum = sum(metrics["sentiment_percentages"].values())
    assert abs(pct_sum - 100.0) < 0.5  # denominator correctness
    assert metrics["average_rating"] == 3.0
    assert metrics["rating_distribution"] == {"1": 1, "3": 1, "5": 1}


def test_missing_optional_fields_safe():
    records = [rec(1, "great product")]  # no rating/date/product/segment
    _, metrics = run_local_analysis(records)
    assert metrics["average_rating"] is None
    assert metrics["rating_distribution"] == {}
    assert metrics["analysis_period"]["start"] is None
    assert metrics["sentiment_by_product"] == {}


def test_topics_from_actual_records():
    records = [rec(1, "the mobile app crash rate is high and mobile notifications wrong"),
               rec(2, "mobile performance issues again")]
    _, metrics = run_local_analysis(records)
    topic_names = [t for t, _ in metrics["top_topics"]]
    assert any("mobile" in t or "crash" in t for t in topic_names)


def test_competitor_detected_in_text():
    records = [rec(1, "Cheaper than CompetitorX honestly", 4)]
    _, metrics = run_local_analysis(records)
    assert "CompetitorX" in metrics["competitor_sentiment"]


def test_sentiment_by_segment():
    records = [rec(1, "excellent work", segment="Ent"), rec(2, "awful experience", segment="SMB")]
    _, metrics = run_local_analysis(records)
    assert metrics["sentiment_by_segment"]["Ent"]["positive"] == 1
    assert metrics["sentiment_by_segment"]["SMB"]["negative"] == 1
