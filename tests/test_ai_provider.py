"""AI layer tests run fully offline: provider SDKs are mocked."""
import json
from types import SimpleNamespace

import pytest

from modules.ai_provider import AIError, classify_sentiment_ai, generate_brief_ai
from modules.config import AIConfig


def cfg_openai(monkeypatch):
    monkeypatch.setenv("MARPULSE_AI_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    return AIConfig(provider="openai", openai_api_key="test-key-not-real",
                    gemini_api_key=None, google_api_key=None)


RECORDS = [{"id": 1, "text": "great support team", "rating": 5.0},
           {"id": 2, "text": "awful crashes constantly", "rating": 1.0}]


def fake_openai_response(payload):
    class C:
        def __init__(self, d):
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=lambda **kw: SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(d)))])))
    return C(payload)


def test_no_provider_raises(monkeypatch):
    monkeypatch.delenv("MARPULSE_AI_PROVIDER", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    from modules.config import get_ai_config
    with pytest.raises(AIError):
        classify_sentiment_ai(RECORDS, get_ai_config())


def test_valid_structured_response_accepted(monkeypatch):
    payload = {"results": [
        {"record_id": 1, "sentiment": "positive", "confidence": 0.9, "main_topic": "support",
         "pain_points": [], "positive_attributes": ["support"], "feature_requests": [],
         "customer_intent": "", "evidence": "great support"},
        {"record_id": 2, "sentiment": "negative", "confidence": 0.85, "main_topic": "stability",
         "pain_points": ["crashes"], "positive_attributes": [], "feature_requests": [],
         "customer_intent": "", "evidence": "awful"}]}
    monkeypatch.setattr("modules.ai_provider._openai_client", lambda cfg: fake_openai_response(payload))
    out = classify_sentiment_ai(RECORDS, cfg_openai(monkeypatch))
    assert len(out) == 2
    assert out[0]["sentiment"] == "positive"
    assert out[0]["method"].startswith("ai:openai")


def test_invalid_label_rejected(monkeypatch):
    payload = {"results": [{"record_id": 1, "sentiment": "delighted", "confidence": 0.5,
                            "main_topic": "", "pain_points": [], "positive_attributes": [],
                            "feature_requests": [], "customer_intent": "", "evidence": ""}]}
    monkeypatch.setattr("modules.ai_provider._openai_client", lambda cfg: fake_openai_response(payload))
    with pytest.raises(AIError):
        classify_sentiment_ai(RECORDS, cfg_openai(monkeypatch))


def test_missing_required_field_handled(monkeypatch):
    payload = {"results": [{"record_id": 1}]}
    monkeypatch.setattr("modules.ai_provider._openai_client", lambda cfg: fake_openai_response(payload))
    with pytest.raises(AIError):
        classify_sentiment_ai(RECORDS, cfg_openai(monkeypatch))


def test_hallucinated_record_ids_dropped(monkeypatch):
    payload = {"results": [
        {"record_id": 999, "sentiment": "positive", "confidence": 0.5, "main_topic": "",
         "pain_points": [], "positive_attributes": [], "feature_requests": [],
         "customer_intent": "", "evidence": ""},
        {"record_id": 1, "sentiment": "neutral", "confidence": 0.4, "main_topic": "",
         "pain_points": [], "positive_attributes": [], "feature_requests": [],
         "customer_intent": "", "evidence": ""}]}
    monkeypatch.setattr("modules.ai_provider._openai_client", lambda cfg: fake_openai_response(payload))
    out = classify_sentiment_ai(RECORDS, cfg_openai(monkeypatch))
    assert [o["record_id"] for o in out] == [1]


def test_api_failure_raises_not_silent_fallback(monkeypatch):
    def boom(cfg):
        raise RuntimeError("connection reset")
    monkeypatch.setattr("modules.ai_provider._openai_client", boom)
    monkeypatch.setattr("modules.ai_provider.time.sleep", lambda s: None)
    with pytest.raises(AIError):
        classify_sentiment_ai(RECORDS, cfg_openai(monkeypatch))


def test_local_mode_never_claims_llm():
    from modules.sentiment_engine import run_local_analysis
    recs = [{"id": i, "text": f"the {w} product works", "rating": None} for i, w in enumerate(["great", "awful", "plain"])]
    classifications, _ = run_local_analysis(recs)
    assert all("local" in c["method"] and not c["method"].startswith("ai") for c in classifications)
