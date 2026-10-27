"""Page 3 - Market intelligence & competitor analysis workspace."""
from __future__ import annotations

import json

import pandas as pd
import plotly.express as px
import streamlit as st

from modules.market_analyzer import competitor_comparison, market_intelligence_bundle
from modules.state import get_db, selected_run_id

st.set_page_config(page_title="Market Intelligence", page_icon="🧭", layout="wide")
st.title("🧭 Module 3 · Market Intelligence & Competitor Analysis")
st.caption("Three evidence tiers are kept strictly separate: **Observed evidence** (uploaded data), "
           "**AI interpretation**, and **Strategic hypothesis** (needs validation). "
           "No external market figures are asserted unless a real source was recorded.")

db = get_db()
run_id = selected_run_id() or (db.list_runs()[0]["id"] if db.list_runs() else None)
if not run_id:
    st.warning("Run an analysis first (page 2 · Insights & Analytics).")
    st.stop()

run = db.get_run(run_id)
ds = db.get_dataset(run["dataset_id"])
records = db.get_records(run["dataset_id"], only_valid=True)
results = db.get_sentiment_results(run_id)
for r in results:
    for fld in ("pain_points", "positive_attributes", "feature_requests"):
        r[fld] = json.loads(r[fld] or "[]")
insights = db.list_insights(run_id=run_id)
metrics = json.loads(run["metrics"] or "{}")

# ---- manual notes / competitor observations ----
with st.expander("➕ Add market research note / competitor observation"):
    ntitle = st.text_input("Title", key="note_title")
    nbody = st.text_area("Body (treat as your own observation; provenance recorded)", key="note_body")
    nkind = st.radio("Kind", ["note", "competitor_observation"], horizontal=True,
                     format_func=lambda k: "Research note" if k == "note" else "Competitor observation")
    if st.button("Save note", type="primary"):
        if not ntitle.strip() or not nbody.strip():
            st.error("Both title and body are required.")
        else:
            db.add_note(ntitle.strip(), nbody.strip(), nkind, ds["id"])
            st.success("Note saved with timestamp and provenance.")
            st.rerun()

notes = db.list_notes(ds["id"])

# ---- competitor comparison ----
st.subheader("Competitor comparison")
comp = competitor_comparison(records, results)
if comp["available"]:
    dfc = pd.DataFrame(comp["table"])
    st.dataframe(dfc, use_container_width=True, hide_index=True)
    fig = px.bar(dfc.melt(id_vars="competitor", value_vars=["positive", "negative", "other"],
                          var_name="Sentiment", value_name="Mentions"),
                 x="competitor", y="Mentions", color="Sentiment",
                 color_discrete_map={"positive": "#16a34a", "negative": "#dc2626", "other": "#8a94a6"},
                 barmode="stack", title="Customer-stated sentiment per competitor (from supplied records)")
    st.plotly_chart(fig, use_container_width=True)
    with st.expander("Verbatim quotes behind competitor mentions"):
        for c, qs in comp["quotes"].items():
            st.markdown(f"**{c}**")
            for q in qs:
                st.caption("“" + q + "”")
    st.caption("⚠️ These reflect what customers *said* about competitors in the uploaded data. "
               "They are not independently verified competitor facts.")
else:
    st.info(comp["reason"])

# ---- three-tier intelligence ----
bundle = market_intelligence_bundle(records, results, insights, notes, metrics)
col1, col2, col3 = st.columns(3)
for col, key, icon, tone in [(col1, "observed_evidence", "🟦 Observed evidence", "#eaf2fb"),
                             (col2, "ai_interpretation", "🟪 AI interpretation", "#f3ecfb"),
                             (col3, "strategic_hypothesis", "🟨 Strategic hypothesis", "#fdf6e3")]:
    with col:
        items = bundle[key]
        st.markdown(f"##### {icon} ({len(items)})")
        if not items:
            st.caption("Nothing qualifies for this tier from current data — intentionally empty.")
        for it in items:
            st.markdown(
                f"<div style='background:{tone};border:1px solid #d7dee6;border-radius:8px;"
                f"padding:8px;margin-bottom:6px'><b>{it['title']}</b><br>"
                f"<span style='font-size:0.85rem'>{it['detail']}</span><br>"
                f"<span style='color:#57606a;font-size:0.75rem'>evidence: {it['evidence_count']}</span></div>",
                unsafe_allow_html=True)
st.caption(bundle["note"])

# ---- needs/gaps summary from actual insights ----
st.subheader("Needs, gaps & campaign opportunities (derived)")
rows = []
for i in insights:
    rows.append({"category": i["category"], "title": i["title"], "n": i["supporting_count"],
                 "confidence": i["confidence"], "origin": i["origin"],
                 "segments": ", ".join(i["segments"])})
if rows:
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    opps = [i for i in insights if i["category"] in ("marketing_opportunity", "differentiator",
                                                    "churn_risk")]
    if opps:
        st.markdown("**Potential campaign angles:**")
        for o in opps:
            st.markdown(f"- {o['title']} → {o['recommended_action']}")
else:
    st.info("No insights available for this run.")
