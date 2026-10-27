"""Page 7 - History, exports and audit trail."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from modules.export_service import (build_campaign_pdf, insights_report_markdown,
                                    sentiment_csv_bytes, write_markdown_export,
                                    write_text_export)
from modules.state import get_db, selected_campaign_id, selected_run_id

st.set_page_config(page_title="History & Exports", page_icon="🗂️", layout="wide")
st.title("🗂️ Module 7 · History, Exports & Audit Trail")

db = get_db()

tab_exports, tab_reports, tab_runs, tab_audit = st.tabs(
    ["Campaign pack exports", "Insights report & CSV", "Analysis run history", "Audit log"])

with tab_exports:
    campaigns = db.list_campaigns()
    if not campaigns:
        st.info("No campaigns to export yet.")
    else:
        labels = {c["id"]: f"#{c['id']} {c['name']}" for c in campaigns}
        sel = st.selectbox("Campaign", list(labels.keys()), format_func=lambda i: labels[i],
                           index=next((k for k, c in enumerate(campaigns)
                                       if c["id"] == selected_campaign_id()), 0))
        include_drafts = st.checkbox("Include draft/non-approved assets (clearly labelled)", value=False)
        c1, c2, c3 = st.columns(3)
        if c1.button("Build campaign PDF", type="primary"):
            try:
                p = build_campaign_pdf(db, sel, include_drafts)
                st.success(f"PDF written: {p.name}")
                st.download_button("⬇ Download PDF", p.read_bytes(), file_name=p.name,
                                   mime="application/pdf", key="dl_pdf")
            except Exception as e:
                st.error(str(e))
        if c2.button("Export Markdown pack"):
            try:
                p = write_markdown_export(db, sel, include_drafts)
                st.success(f"Markdown written: {p.name}")
                st.download_button("⬇ Download Markdown", p.read_bytes().decode("utf-8"),
                                   file_name=p.name, mime="text/markdown", key="dl_md")
            except Exception as e:
                st.error(str(e))
        if c3.button("Export text pack"):
            try:
                p = write_text_export(db, sel, include_drafts)
                st.success(f"Text written: {p.name}")
                st.download_button("⬇ Download text", p.read_text(encoding="utf-8"),
                                   file_name=p.name, mime="text/plain", key="dl_txt")
            except Exception as e:
                st.error(str(e))

        exports = db.list_exports()
        if exports:
            st.subheader("Export metadata")
            st.dataframe(pd.DataFrame(exports)[["id", "campaign_id", "export_type", "file_path",
                                                "created_at"]], use_container_width=True,
                         hide_index=True)

with tab_reports:
    runs = db.list_runs()
    if not runs:
        st.info("No analysis runs yet.")
    else:
        rlabels = {r["id"]: f"Run #{r['id']} · ds {r['dataset_id']} · {r['mode']} · {r['created_at']}"
                   for r in runs}
        rid = st.selectbox("Run", list(rlabels.keys()), format_func=lambda i: rlabels[i],
                           index=(list(rlabels.keys()).index(selected_run_id())
                                  if selected_run_id() in rlabels else 0))
        filt_sent = st.selectbox("CSV sentiment filter", ["all", "positive", "negative", "neutral",
                                                          "mixed", "uncertain"])
        if st.button("Generate insights report (Markdown)"):
            try:
                p = insights_report_markdown(db, rid)
                st.success(f"Report written: {p.name}")
                st.download_button("⬇ Download report", p.read_text(encoding="utf-8"),
                                   file_name=p.name, mime="text/markdown")
            except Exception as e:
                st.error(str(e))
        if st.button("Generate filtered classification CSV"):
            data = sentiment_csv_bytes(db, rid, None if filt_sent == "all" else filt_sent)
            st.download_button(f"⬇ Download CSV ({filt_sent})", data,
                               file_name=f"sentiment_run{rid}_{filt_sent}.csv", mime="text/csv")

with tab_runs:
    runs = db.list_runs()
    if runs:
        rows = []
        for r in runs:
            m = json.loads(r["metrics"] or "{}")
            rows.append({"run": r["id"], "dataset": r["dataset_id"], "mode": r["mode"],
                         "provider": r["provider"], "records": m.get("classified_records"),
                         "avg_rating": m.get("average_rating"),
                         "period_start": (m.get("analysis_period") or {}).get("start"),
                         "period_end": (m.get("analysis_period") or {}).get("end"),
                         "created": r["created_at"]})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        with st.expander("Reproduce configuration of a run"):
            rid = st.selectbox("Run id", [x["run"] for x in rows])
            r = db.get_run(rid)
            st.json(json.loads(r["config"] or "{}"))
            st.caption("Re-run the same dataset/mode on page 2 to reproduce; stored metrics above "
                       "are the recorded outcome.")
    else:
        st.info("None yet.")

with tab_audit:
    events = db.list_audit(limit=200)
    if events:
        st.dataframe(pd.DataFrame(events), use_container_width=True, hide_index=True)
    else:
        st.info("No audit events recorded.")
