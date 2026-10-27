"""Pydantic schemas and shared constants for MarketPulse AI & Campaign Studio."""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

SENTIMENT_LABELS = ("positive", "neutral", "negative", "mixed", "uncertain")
ReviewStatus = Literal["draft", "under_review", "changes_requested", "approved", "rejected", "archived"]
ASSET_STATUSES: List[str] = ["draft", "under_review", "changes_requested", "approved", "rejected", "archived"]

CHANNELS = ["linkedin", "instagram", "facebook", "x", "video", "calendar",
            "email", "search_ad", "social_ad", "landing_page", "faq", "ab_test"]


class SentimentRecordResult(BaseModel):
    """One AI-classified feedback record (validated before persistence)."""
    record_id: int
    sentiment: Literal["positive", "neutral", "negative", "mixed", "uncertain"]
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    main_topic: str = ""
    pain_points: List[str] = Field(default_factory=list)
    positive_attributes: List[str] = Field(default_factory=list)
    feature_requests: List[str] = Field(default_factory=list)
    customer_intent: str = ""
    evidence: str = ""

    @field_validator("main_topic", "customer_intent")
    @classmethod
    def _strip(cls, v: str) -> str:
        return (v or "").strip()[:200]


class SentimentAnalysisResponse(BaseModel):
    results: List[SentimentRecordResult]


class InsightItem(BaseModel):
    title: str
    description: str
    category: Literal["pain_point", "satisfaction_driver", "feature_request", "unmet_need",
                      "objection", "churn_risk", "improvement", "differentiator",
                      "emerging_theme", "marketing_opportunity"]
    evidence: List[str] = Field(default_factory=list)
    record_ids: List[int] = Field(default_factory=list)
    supporting_count: int = 0
    segments: List[str] = Field(default_factory=list)
    business_implication: str = ""
    recommended_action: str = ""
    confidence: Literal["high", "medium", "low"] = "medium"
    origin: Literal["data_derived", "ai_interpreted", "hypothesis"] = "data_derived"


class PersonaSchema(BaseModel):
    name: str
    segment: str = ""
    demographics_note: str = "Not measured in dataset - inferred marketing hypothesis."
    needs_goals: List[str] = Field(default_factory=list)
    pain_points: List[str] = Field(default_factory=list)
    motivations: List[str] = Field(default_factory=list)
    objections: List[str] = Field(default_factory=list)
    preferred_channels: List[str] = Field(default_factory=list)
    messaging_preferences: str = ""
    evidence_refs: List[str] = Field(default_factory=list)
    inferred: bool = True


class CampaignBriefSchema(BaseModel):
    overview: str
    business_objective: str
    persona: PersonaSchema
    audience_needs: List[str] = Field(default_factory=list)
    motivations_objections: List[str] = Field(default_factory=list)
    value_proposition: str
    usp: str
    messaging_pillars: List[str] = Field(default_factory=list)
    supporting_evidence: List[str] = Field(default_factory=list)
    recommended_channels: List[str] = Field(default_factory=list)
    channel_strategy: List[str] = Field(default_factory=list)
    content_themes: List[str] = Field(default_factory=list)
    cta_strategy: str
    timeline: List[str] = Field(default_factory=list)
    kpis: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    testing_recommendations: List[str] = Field(default_factory=list)


class ContentAssetSchema(BaseModel):
    asset_type: str
    title: str
    body: str
    cta: str = ""
    notes: str = ""


class ContentBatchSchema(BaseModel):
    assets: List[ContentAssetSchema]


class CampaignSetup(BaseModel):
    """Validated campaign configuration form input."""
    campaign_name: str = Field(min_length=2, max_length=120)
    product_service: str = Field(min_length=2, max_length=120)
    business_objective: str = Field(min_length=4, max_length=300)
    target_market: str = Field(min_length=2, max_length=200)
    audience_segment: str = ""
    geographic_market: str = ""
    brand_positioning: str = ""
    budget: str = ""
    duration: str = ""
    channels: List[str] = Field(default_factory=list)
    desired_action: str = ""
    brand_voice: str = ""
    restrictions: str = ""
    competitor_context: str = ""

    @field_validator("channels")
    @classmethod
    def _valid_channels(cls, v: List[str]) -> List[str]:
        allowed = set(CHANNELS) | {"email_outreach", "content_calendar"}
        bad = [c for c in v if c not in allowed]
        if bad:
            raise ValueError(f"Unknown channels: {bad}")
        return v
