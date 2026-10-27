"""Page 2 - Sentiment analysis, quantitative analytics and insight drill-down."""
from __future__ import annotations

import json
from collections import Counter

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from modules.ai_provider import AIError, classify_sentiment_ai
from modules.config import get_ai_config
from modules.insight_extractor import extract_insights
from modules.sentiment_engine import LIMITATIONS_NOTE, run_local_analysis
from modules.state import ai_status_badge, get_db, selected_run_id, set_selected_run

st.set_page_config(page_title="Insights & Analytics", page_icon="📊", layout="wide")
st.title("📊 Module 2 · Customer Sentiment & Market Insight Engine")
st.markdown(ai_status_badge())

db = get_db()
datasets = [d for d in db.list_datasets() if not d["archived"]]
if not datasets:
    st.warning("No datasets available. Load data on page **1 · Data Ingestion** first.")
    st.stop()

ds_map = {d["id"]: f"#{d['id']} {d['name']} [{d['origin_label']}]" for d in datasets}
default_idx = next((k for k, d in enumerate(datasets)
                    if d["id"] == st.session_state.get("mp_selected_dataset")), 0)
ds_id = st.selectbox("Dataset", list(ds_map.keys()), format_func=lambda i: ds_map[i],
                     index=default_idx)
if ds_id != st.session_state.get("mp_selected_dataset"):
    st.session_state["mp_selected_dataset"] = ds_id

runs = db.list_runs(ds_id)
run_labels = {r["id"]: f"Run #{r['id']} · {r['mode']} · {r['created_at']}" for r in runs}
c_mode, c_run = st.columns([3, 2])
with c_mode:
    mode = st.radio("Analysis mode", ["local", "ai"], horizontal=True,
                    format_func=lambda m: "Local Analysis Mode (deterministic)" if m == "local"
                    else "AI Mode (OpenAI/Gemini)", key="mode_sel")
with c_run:
    sel_run = st.selectbox("Existing analysis run", [None] + list(run_labels.keys()),
                           format_func=lambda r: "— none —" if r is None else run_labels[r],
                           index=(list(run_labels.keys()).index(selected_run_id()) + 1
                                  if selected_run_id() in run_labels else 0),
                           key="run_sel")
    if sel_run != selected_run_id():
        if sel_run:
            set_selected_run(sel_run)
        else:
            st.session_state.pop("mp_selected_run", None)

records = db.get_records(ds_id, only_valid=True)

if st.button("▶ Run analysis", type="primary"):
    if not records:
        st.error("Dataset has no valid records to analyze.")
    else:
        cfg = get_ai_config()
        with st.spinner("Classifying feedback..."):
            try:
                if mode == "ai":
                    classifications = classify_sentiment_ai(records, cfg)
                    # recompute metrics locally from the AI labels (never ask LLM for counts)
                    from modules.sentiment_engine import compute_metrics
                    decoded = []
                    for c in classifications:
                        d = dict(c)
                        for fld in ("pain_points", "positive_attributes", "feature_requests"):
                            d[fld] = json.loads(d[fld]) if isinstance(d.get(fld), str) else d.get(fld, [])
                        decoded.append(d)
                    metrics = compute_metrics(records, decoded)
                    provider = cfg.display_name()
                    save_rows = classifications
                else:
                    decoded, metrics = run_local_analysis(records)
                    provider = "none"
                    save_rows = []
                    for c in decoded:
                        row = dict(c)
                        row["pain_points"] = json.dumps(row["pain_points"])
                        row["positive_attributes"] = json.dumps(row["positive_attributes"])
                        row["feature_requests"] = json.dumps(row["feature_requests"])
                        save_rows.append(row)
            except AIError as e:
                st.error(f"AI request failed: {e}")
                st.info("Your inputs are preserved. Retry, or switch the mode selector to "
                        "**Local Analysis Mode** and run again.")
                st.stop()
        run_id = db.create_run(ds_id, mode, provider, {"mode": mode, "records": len(records)}, metrics)
        db.save_sentiment_results(run_id, save_rows)
        insights = extract_insights(records, decoded, metrics)
        db.save_insights(run_id, ds_id, insights)
        set_selected_run(run_id)
        st.success(f"Run #{run_id} completed using {'AI provider' if mode=='ai' else 'Local Analysis Mode'}."
                   if mode == "ai" else
                   f"Run #{run_id} completed using Local Analysis Mode (rule-based; NOT LLM inference).")
        st.rerun()

run_id = selected_run_id()
if not run_id:
    st.info("Select a dataset and press **Run analysis** to produce metrics, sentiment results and insights.")
    st.stop()

run = db.get_run(run_id)
metrics = json.loads(run["metrics"])
results = db.get_sentiment_results(run_id)
for r in results:
    for fld in ("pain_points", "positive_attributes", "feature_requests"):
        r[fld] = json.loads(r[fld] or "[]")
insights = db.list_insights(run_id=run_id)

# freshness indicator
if run["dataset_id"] != ds_id:
    st.warning("⚠️ This run belongs to a different dataset than the one currently selected — "
               "insights below come from an earlier analysis run.")

# ---------- filters ----------
seg_opts = sorted({(r.get("segment") or "") for r in records if r.get("segment")})
f1, f2 = st.columns(2)
f_seg = f1.multiselect("Filter by segment", seg_opts)
f_sent = f2.multiselect("Filter by sentiment", ["positive", "neutral", "negative", "mixed", "uncertain"])
rec_by_id = {r["id"]: r for r in records}
filt_ids = {r["id"] for r in records if (not f_seg or (r.get("segment") in f_seg))}
filtered = [r for r in results if r["record_id"] in filt_ids
            and (not f_sent or r["sentiment"] in f_sent)]

st.subheader("Quantitative summary")
cc = st.columns(5)
n = max(len(filtered), 1)
cnt = Counter(r["sentiment"] for r in filtered)
cc[0].metric("Valid records", len(records))
cc[1].metric("Classified (filtered)", len(filtered))
cc[2].metric("Positive %", f"{round(100*cnt.get('positive',0)/n,1)}%")
cc[3].metric("Negative %", f"{round(100*cnt.get('negative',0)/n,1)}%")
avg_ratings = [rec_by_id[r["record_id"]]["rating"] for r in filtered
               if rec_by_id.get(r["record_id"], {}).get("rating") is not None]
cc[4].metric("Avg rating", round(sum(avg_ratings)/len(avg_ratings), 2) if avg_ratings else "n/a")
if not avg_ratings:
    cc[4].caption("No rating column mapped/available — value intentionally omitted, not invented.")

ch1, ch2 = st.columns(2)
with ch1:
    fig = px.bar(x=list(cnt.keys()), y=list(cnt.values()), color=list(cnt.keys()),
                 color_discrete_map={"positive": "#16a34a", "negative": "#dc2626",
                                     "neutral": "#8a94a6", "mixed": "#d97706",
                                     "uncertain": "#6b7280"},
                 labels={"x": "Sentiment", "y": "Records"})
    fig.update_layout(title="Sentiment distribution (current filter)", height=320, showlegend=False)
    st.plotly_chart(fig, use_container_width=True)
with ch2:
    if metrics.get("rating_distribution"):
        rd = metrics["rating_distribution"]
        fig = px.bar(x=list(rd.keys()), y=list(rd.values()),
                     labels={"x": "Rating", "y": "Count"}, title="Rating distribution (full run)")
        fig.update_traces(marker_color="#1f6feb")
        fig.update_layout(height=320)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Rating distribution unavailable — the dataset contains no usable ratings.")

ch3, ch4 = st.columns(2)
with ch3:
    sp = metrics.get("sentiment_by_product") or {}
    if sp:
        rows = [{"Product": p, **{s: d.get(s, 0) for s in cnt.keys()}} for p, d in sp.items()]
        dfp = pd.DataFrame(rows).set_index("Product")
        fig = go.Figure()
        for colname in dfp.columns:
            fig.add_bar(x=dfp.index, y=dfp[colname], name=colname)
        fig.update_layout(barmode="stack", title="Sentiment by product", height=340)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No product column mapped — per-product breakdown omitted.")
with ch4:
    ss = metrics.get("sentiment_by_segment") or {}
    if ss:
        rows = [{"Segment": s, **{lab: d.get(lab, 0) for lab in ["positive", "negative", "neutral", "mixed", "uncertain"]}}
                for s, d in ss.items()]
        dfs = pd.DataFrame(rows).fillna(0)
        fig = px.bar(dfs.melt(id_vars="Segment", var_name="Sentiment", value_name="Count"),
                     x="Segment", y="Count", color="Sentiment", title="Sentiment by segment",
                     height=340)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No customer-segment column mapped — segment breakdown omitted.")

t = metrics.get("sentiment_over_time") or {}
if t:
    rows = [{"Month": m, **{lab: d.get(lab, 0) for lab in ["positive", "negative", "neutral", "mixed", "uncertain"]}}
            for m, d in t.items()]
    dft = pd.DataFrame(rows).fillna(0)
    fig = px.line(dft, x="Month", y=["positive", "negative", "neutral"], markers=True,
                  title="Sentiment over time", height=320)
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("Time series unavailable — no parseable review dates in this dataset.")

tp = metrics.get("top_topics") or []
if tp:
    fig = px.bar(x=[v for _, v in tp], y=[k for k, _ in tp], orientation="h",
                 labels={"x": "Mentions", "y": "Topic"}, title="Most frequent topics (actual records)")
    fig.update_layout(height=380)
    st.plotly_chart(fig, use_container_width=True)

if run["mode"] == "local":
    st.caption("⚗ Method: " + LIMITATIONS_NOTE)

# ---------- insights with traceability ----------
st.subheader(f"Insights ({len(insights)})")
if not insights:
    st.info("No insights met the minimum evidence threshold (≥2 supporting records).")
for ins in insights:
    badge = {"data_derived": "🟦 data-derived", "ai_interpreted": "🟪 AI-interpreted",
             "hypothesis": "🟨 hypothesis"}[ins["origin"]]
    with st.expander(f"[{ins['category']}] {ins['title']} — n={ins['supporting_count']} "
                     f"· confidence={ins['confidence']} · {badge}"):
        st.write(ins["description"])
        st.markdown(f"**Business implication:** {ins['business_implication']}")
        st.markdown(f"**Recommended action:** {ins['recommended_action']}")
        if ins["segments"]:
            st.markdown(f"**Segments:** {', '.join(ins['segments'])}")
        st.markdown("**Supporting evidence (traceable records):**")
        ev_rows = []
        for rid in ins["record_ids"]:
            rec = rec_by_id.get(rid)
            if rec:
                ev_rows.append({"record_id": rid, "ref": rec["external_ref"],
                                "text": rec["text"][:220], "rating": rec["rating"],
                                "segment": rec["segment"], "product": rec["product"]})
        if ev_rows:
            st.dataframe(pd.DataFrame(ev_rows), use_container_width=True, hide_index=True)
        for e in ins["evidence"][:3]:
            st.caption("“" + e + "”")

# CSV download of current results respecting filters
buf_rows = [{"record_id": r["record_id"], "external_ref": rec_by_id.get(r["record_id"], {}).get("external_ref"),
             "sentiment": r["sentiment"], "confidence": r["confidence"],
             "topic": r["main_topic"], "method": r["method"]} for r in filtered]
st.download_button("⬇ Download filtered classifications CSV",
                   pd.DataFrame(buf_rows).to_csv(index=False).encode("utf-8"),
                   file_name=f"sentiment_run{run_id}.csv", mime="text/csv")
