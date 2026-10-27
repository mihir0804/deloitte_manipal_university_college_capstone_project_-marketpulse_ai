"""Export services: campaign-pack PDF, insights report, Markdown/text, CSV.

All exports are built from actual saved database records. Approved-only mode
never labels drafts as approved; draft-inclusive mode marks each item clearly.
"""
from __future__ import annotations

import csv
import io
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from modules.config import EXPORT_DIR, ensure_dirs
from modules.db_handler import Database, utcnow


def safe_filename(name: str) -> str:
    # collapse '.' runs first so path-traversal fragments ('..') can never survive
    name = re.sub(r"\.{2,}", "_", (name or "").strip())
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:100]
    return name or "export"


def _out_path(fname: str) -> Path:
    ensure_dirs()
    return EXPORT_DIR / fname


# ------------------------------------------------------------------ markdown
def brief_to_markdown(setup: Dict[str, Any], brief: Dict[str, Any], method: str,
                     insights: List[Dict[str, Any]]) -> str:
    p = brief.get("persona", {})
    lines = [f"# Campaign Brief: {setup.get('campaign_name','')}",
             f"_Generated {utcnow()} via **{method}**_", "",
             "## 1. Campaign Overview", brief.get("overview", ""), "",
             "## 2. Business Objective", brief.get("business_objective", ""), "",
             "## 3. Target Audience Persona",
             f"- Name: {p.get('name','')} ({'INFERRED HYPOTHESIS' if p.get('inferred') else 'measured'})",
             f"- Segment: {p.get('segment','')}",
             f"- Demographics note: {p.get('demographics_note','')}",
             f"- Needs/goals: {'; '.join(p.get('needs_goals', []))}",
             f"- Pain points: {'; '.join(p.get('pain_points', []))}",
             f"- Motivations: {'; '.join(p.get('motivations', []))}",
             f"- Objections: {'; '.join(p.get('objections', []))}",
             f"- Preferred channels: {', '.join(p.get('preferred_channels', []))}",
             ("- Status: Inferred Hypothesis (not measured demographics)" if p.get("inferred")
              else "- Status: Measured audience data"), "",
             "## 4. Audience Needs & Pain Points",
             *[f"- {x}" for x in brief.get("audience_needs", [])], "",
             "## 5. Motivations & Objections",
             *[f"- {x}" for x in brief.get("motivations_objections", [])], "",
             "## 6. Value Proposition", brief.get("value_proposition", ""), "",
             "## 7. Unique Selling Proposition", brief.get("usp", ""), "",
             "## 8. Key Messaging Pillars",
             *[f"{i+1}. {x}" for i, x in enumerate(brief.get("messaging_pillars", []))], "",
             "## 9. Supporting Evidence (insight traceability)",
             *[f"- {x}" for x in brief.get("supporting_evidence", [])],
             *[f"- Insight #{ins['id']}: {ins['title']} [{ins['origin']}, confidence={ins['confidence']}, "
               f"n={ins['supporting_count']}]" for ins in insights], "",
             "## 10. Recommended Channels", ", ".join(brief.get("recommended_channels", [])), "",
             "## 11. Channel-Specific Strategy",
             *[f"- {x}" for x in brief.get("channel_strategy", [])], "",
             "## 12. Content Themes",
             *[f"- {x}" for x in brief.get("content_themes", [])], "",
             "## 13. Call-to-Action Strategy", brief.get("cta_strategy", ""), "",
             "## 14. Proposed Timeline",
             *[f"- {x}" for x in brief.get("timeline", [])], "",
             "## 15. Success Metrics / KPIs",
             *[f"- {x}" for x in brief.get("kpis", [])], "",
             "## 16. Assumptions & Dependencies",
             *[f"- {x}" for x in brief.get("assumptions", [])], "",
             "## 17. Risks & Mitigation",
             *[f"- {x}" for x in brief.get("risks", [])], "",
             "## 18. Testing & Optimization",
             *[f"- {x}" for x in brief.get("testing_recommendations", [])], ""]
    return "\n".join(lines)


def campaign_pack_markdown(db: Database, campaign_id: int, include_drafts: bool = False) -> str:
    camp = db.get_campaign(campaign_id)
    if not camp:
        raise ValueError("Campaign not found")
    brief_row = db.latest_brief(campaign_id)
    if not brief_row:
        raise ValueError("No brief exists for this campaign yet.")
    insights = [db.get_insight(i) for i in brief_row["insight_ids"]]
    insights = [i for i in insights if i]
    md = [brief_to_markdown(camp["setup"], brief_row["content"], "local_template/database export",
                            insights),
          "---", "# Content Assets", ""]
    assets = db.list_assets(campaign_id=campaign_id)
    included = 0
    for a in assets:
        if a["status"] != "approved" and not include_drafts:
            continue
        label = a["status"].upper() if a["status"] == "approved" else f"[DRAFT - NOT APPROVED - {a['status'].upper()}]"
        md.append(f"## {a['title']} ({a['asset_type']}) v{a['version']} - {label}")
        md.append(a["body"])
        if a.get("cta"):
            md.append(f"\nCTA: {a['cta']}")
        md.append("")
        included += 1
    if included == 0:
        md.append("_No approved assets exist yet. Use 'include drafts' or approve content first._")
    reviews = db.list_reviews("campaign_pack", campaign_id)
    md += ["---", "## Review & Approval History",
           *[f"- {r['created_at']} {r['action']}: {r['comment'][:120]}" for r in reviews]]
    return "\n".join(md)


def write_markdown_export(db: Database, campaign_id: int, include_drafts: bool = False) -> Path:
    camp = db.get_campaign(campaign_id)
    content = campaign_pack_markdown(db, campaign_id, include_drafts)
    path = _out_path(safe_filename(f"{camp['name']}_pack.md"))
    path.write_text(content, encoding="utf-8")
    db.record_export(campaign_id, "markdown", str(path), {"include_drafts": include_drafts,
                                                          "bytes": path.stat().st_size})
    return path


def write_text_export(db: Database, campaign_id: int, include_drafts: bool = False) -> Path:
    camp = db.get_campaign(campaign_id)
    md = campaign_pack_markdown(db, campaign_id, include_drafts)
    txt = re.sub(r"^#+\s*", "", md, flags=re.M)
    path = _out_path(safe_filename(f"{camp['name']}_pack.txt"))
    path.write_text(txt, encoding="utf-8")
    db.record_export(campaign_id, "text", str(path), {"bytes": path.stat().st_size})
    return path


# ------------------------------------------------------------------ pdf
def build_campaign_pdf(db: Database, campaign_id: int, include_drafts: bool = False) -> Path:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (KeepTogether, PageBreak, Paragraph, SimpleDocTemplate,
                                    Spacer, Table, TableStyle)
    from reportlab.lib import colors

    camp = db.get_campaign(campaign_id)
    if not camp:
        raise ValueError("Campaign not found")
    brief_row = db.latest_brief(campaign_id)
    if not brief_row:
        raise ValueError("No brief exists for this campaign yet - generate one before exporting.")
    brief = brief_row["content"]
    setup = camp["setup"]

    fname = safe_filename(f"{camp['name']}_campaign_pack.pdf")
    path = _out_path(fname)
    doc = SimpleDocTemplate(str(path), pagesize=A4, topMargin=1.6 * cm, bottomMargin=1.6 * cm,
                            title=f"Campaign Pack - {camp['name']}")
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("H1x", parent=styles["Heading1"], fontSize=16, spaceAfter=8)
    h2 = ParagraphStyle("H2x", parent=styles["Heading2"], fontSize=12.5, spaceBefore=12, spaceAfter=5)
    body = ParagraphStyle("Bodyx", parent=styles["Normal"], fontSize=9.5, leading=13)
    small = ParagraphStyle("Smallx", parent=styles["Normal"], fontSize=8, textColor=colors.grey)

    def esc(t: str) -> str:
        return (t or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    story = [Paragraph(f"Campaign Pack: {esc(camp['name'])}", h1),
             Paragraph(f"Generated {utcnow()} · MarketPulse AI &amp; Campaign Studio · "
                       f"Dataset ID {camp.get('dataset_id')} · Run ID {camp.get('run_id')} · "
                       f"Brief v{brief_row['version']} ({esc(brief_row['status'])})", small),
             Spacer(1, 8)]

    sections = [("Campaign Overview", brief.get("overview")),
                ("Business Objective", brief.get("business_objective")),
                ("Value Proposition", brief.get("value_proposition")),
                ("Unique Selling Proposition", brief.get("usp")),
                ("Call-to-Action Strategy", brief.get("cta_strategy"))]
    for title, val in sections:
        story.append(Paragraph(title, h2))
        story.append(Paragraph(esc(val or "-"), body))

    p = brief.get("persona", {})
    story.append(Paragraph("Audience Persona " + ("(Inferred Hypothesis)" if p.get("inferred") else ""), h2))
    persona_rows = [["Field", "Value"],
                    ["Name", esc(p.get("name", ""))],
                    ["Segment", esc(p.get("segment", ""))],
                    ["Demographics", esc(p.get("demographics_note", ""))],
                    ["Needs/Goals", esc("; ".join(p.get("needs_goals", [])))],
                    ["Pain points", esc("; ".join(p.get("pain_points", [])))],
                    ["Motivations", esc("; ".join(p.get("motivations", [])))],
                    ["Objections", esc("; ".join(p.get("objections", [])))],
                    ["Channels", esc(", ".join(p.get("preferred_channels", [])))]]
    tbl = Table(persona_rows, colWidths=[4 * cm, 12.5 * cm])
    tbl.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 8),
                             ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3b57")),
                             ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                             ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c8d2dc")),
                             ("VALIGN", (0, 0), (-1, -1), "TOP"),
                             ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f5f8")])]))
    story.append(tbl)

    for title, items in [("Key Messaging Pillars", brief.get("messaging_pillars", [])),
                         ("Channel Strategy", brief.get("channel_strategy", [])),
                         ("Content Themes", brief.get("content_themes", [])),
                         ("Campaign Timeline", brief.get("timeline", [])),
                         ("Success Metrics / KPIs", brief.get("kpis", [])),
                         ("Assumptions & Dependencies", brief.get("assumptions", [])),
                         ("Risks & Mitigation", brief.get("risks", [])),
                         ("Testing Recommendations", brief.get("testing_recommendations", []))]:
        story.append(Paragraph(title, h2))
        for it in items:
            story.append(Paragraph(f"&bull; {esc(str(it))}", body))

    story.append(PageBreak())
    story.append(Paragraph("Content Assets", h1))
    assets = db.list_assets(campaign_id=campaign_id)
    any_included = False
    groups = {"approved": [], "other": []}
    for a in assets:
        (groups["approved"] if a["status"] == "approved" else groups["other"]).append(a)
    for label, lst, sub in [("Approved Content", groups["approved"], None),
                          (f"Draft / Non-approved Content ({'included for review' if include_drafts else 'excluded - enable to include'})",
                           groups["other"] if include_drafts else [], "draft")]:
        if lst:
            story.append(Paragraph(label, h2))
        for a in lst:
            any_included = True
            tag = "APPROVED" if a["status"] == "approved" else f"NOT APPROVED ({a['status'].upper()})"
            story.append(KeepTogether([
                Paragraph(f"{esc(a['title'])} &mdash; {esc(a['asset_type'])} v{a['version']} "
                          f"[{tag}]", h2),
                Paragraph(esc(a["body"]).replace("\n", "<br/>"), body)]))
    if not any_included:
        story.append(Paragraph("_No assets matched the selected export mode._", body))

    reviews = db.list_reviews("campaign_pack", campaign_id) + db.list_reviews("brief", brief_row["id"])
    story.append(Paragraph("Review & Approval Record", h1))
    if reviews:
        for r in sorted(reviews, key=lambda x: x["id"]):
            story.append(Paragraph(f"{r['created_at']} · {esc(r['entity_type'])}#{r['entity_id']} · "
                                   f"{esc(r['action'])} ({esc(r.get('from_status') or '-')}→"
                                   f"{esc(r.get('to_status') or '-')}) · {esc(r['comment'][:200])}", body))
    else:
        story.append(Paragraph("No review events recorded.", body))
    story.append(Paragraph("This document is an internal planning artifact. Approval here does not "
                           "publish content anywhere; delivery requires separate integrations.", small))
    doc.build(story)
    if not path.exists() or path.stat().st_size < 500:
        raise RuntimeError("PDF generation produced no usable file.")
    db.record_export(campaign_id, "pdf", str(path), {"include_drafts": include_drafts,
                                                     "bytes": path.stat().st_size})
    return path


# ------------------------------------------------------------------ insights report
def insights_report_markdown(db: Database, run_id: int) -> Path:
    run = db.get_run(run_id)
    if not run:
        raise ValueError("Analysis run not found")
    import json as _json
    metrics = _json.loads(run["metrics"] or "{}")
    ds = db.get_dataset(run["dataset_id"]) or {}
    q = db.latest_quality_report(run["dataset_id"]) or {}
    insights = db.list_insights(run_id=run_id)
    total, valid = db.count_records(run["dataset_id"])
    lines = [f"# Market Insights Report - Dataset '{ds.get('name','')}'",
             f"_Run #{run['id']} · mode={run['mode']} · provider={run['provider']} · {run['created_at']}_", "",
             "## Dataset Description",
             f"- Source kind: {ds.get('source_kind','?')} · Origin label: {ds.get('origin_label','?')}",
             f"- Original rows: {q.get('original_row_count', total)} · Valid: {q.get('valid_row_count', valid)} "
             f"· Excluded: {q.get('excluded_row_count', total-valid)}",
             f"- Analysis period: {metrics.get('analysis_period',{}).get('start')} → "
             f"{metrics.get('analysis_period',{}).get('end')}", "",
             "## Data Quality Summary",
             *[f"- {k}: {v} missing" for k, v in (q.get('missing_field_summary') or {}).items()],
             *[f"- Exclusion row {e['row']} ({e['ref']}): {'; '.join(e['reasons'])}"
               for e in (q.get('exclusions') or [])[:20]], "",
             "## Sentiment Distribution",
             *[f"- {k}: {v} ({metrics.get('sentiment_percentages',{}).get(k,0)}%)"
               for k, v in metrics.get("sentiment_counts", {}).items()],
             f"- Average rating: {metrics.get('average_rating') if metrics.get('average_rating') is not None else 'not available (no rating column)'}", "",
             "## Top Customer Pain Points",
             *[f"- {i['title']} (n={i['supporting_count']}, confidence={i['confidence']})"
               for i in insights if i["category"] == "pain_point"], "",
             "## Satisfaction Drivers",
             *[f"- {i['title']} (n={i['supporting_count']})"
               for i in insights if i["category"] == "satisfaction_driver"], "",
             "## Competitor Comparison",
             "- Only reported when competitor data exists in supplied records."]
    comp = metrics.get("competitor_sentiment") or {}
    if comp:
        for c, d in comp.items():
            lines.append(f"- {c}: {d}")
    else:
        lines.append("- No competitor mentions detected in this dataset.")
    lines += ["", "## Supporting Evidence (sample)"]
    for i in insights[:6]:
        lines.append(f"### {i['title']} [{i['origin']}]")
        for ev in i["evidence"][:3]:
            lines.append(f"- {ev}")
    lines += ["", "## Strategic Recommendations",
              *[f"- {i['title']} → {i['recommended_action']}" for i in insights if i["recommended_action"]],
              "", "## Methodology & Limitations",
              f"- Mode: {run['mode']}. Local mode = deterministic lexicon+rating rules; AI mode = "
              "provider output validated against Pydantic schemas.",
              "- Rule-based sentiment cannot reliably detect sarcasm or negation scope; uncertain "
              "records are labelled explicitly.",
              "- No external market research was retrieved; nothing herein is independently verified "
              "against outside sources."]
    path = _out_path(safe_filename(f"insights_report_run{run_id}.md"))
    path.write_text("\n".join(lines), encoding="utf-8")
    db.record_export(None, "markdown", str(path), {"run_id": run_id})
    return path


# ------------------------------------------------------------------ csv
def sentiment_csv_bytes(db: Database, run_id: int, sentiment_filter: Optional[str] = None,
                        segment_filter: Optional[str] = None) -> bytes:
    """CSV of classification results joined to source records, respecting filters."""
    rows = db.query(
        "SELECT sr.record_id, r.external_ref, r.text, r.rating, r.review_date, r.product,"
        " r.segment, sr.sentiment, sr.confidence, sr.main_topic, sr.method"
        " FROM sentiment_results sr JOIN records r ON r.id = sr.record_id WHERE sr.run_id=?",
        (run_id,))
    if sentiment_filter:
        rows = [x for x in rows if x["sentiment"] == sentiment_filter]
    if segment_filter:
        rows = [x for x in rows if (x["segment"] or "") == segment_filter]
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["record_id", "external_ref", "text", "rating", "review_date", "product",
                     "segment", "sentiment", "confidence", "main_topic", "method"])
    for x in rows:
        writer.writerow([x["record_id"], x["external_ref"], (x["text"] or "")[:300], x["rating"],
                         x["review_date"], x["product"], x["segment"], x["sentiment"],
                         x["confidence"], x["main_topic"], x["method"]])
    return buf.getvalue().encode("utf-8")
