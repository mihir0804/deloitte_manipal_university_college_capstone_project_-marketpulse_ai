"""Page 1 - Multi-source customer & market data ingestion."""
from __future__ import annotations

import html
from pathlib import Path

import pandas as pd
import streamlit as st

from modules.config import SAMPLE_CSV, UPLOAD_DIR
from modules.data_parser import (FIELD_ROLES, IngestionError, detect_column_mapping,
                                 load_document_as_records, map_dataframe, read_csv_bytes,
                                 validate_file_meta)
from modules.data_validator import validate_records
from modules.state import get_db, set_selected_dataset

st.set_page_config(page_title="Data Ingestion", page_icon="📥", layout="wide")
st.title("📥 Module 1 · Data Ingestion & Quality Validation")

db = get_db()

tab_csv, tab_doc, tab_paste, tab_manage = st.tabs(
    ["CSV feedback", "Research documents", "Pasted feedback", "Datasets & quality"])

ORIGINS = {"own_customers": "Own customer feedback",
           "competitor": "Competitor reviews",
           "market_research": "Market research notes"}


def _ingest_tab_csv():
    with st.expander("Built-in sample dataset (fictional)", expanded=False):
        st.markdown("`assets/sample_feedback.csv` — **FICTIONAL SAMPLE DATA** for demonstration: "
                    "25 labelled reviews with ratings, dates, segments and products.")
        if st.button("Load sample dataset", type="primary"):
            data = SAMPLE_CSV.read_bytes()
            df = read_csv_bytes(data)
            mapping = detect_column_mapping(df)
            raw = map_dataframe(df, mapping, [])
            res = validate_records(raw, drop_duplicates=True)
            ds_id = db.create_dataset("Sample Feedback (fictional)", "sample",
                                      "own_customers", str(SAMPLE_CSV), mapping,
                                      res["report"]["original_row_count"])
            for r in res["records"]:
                r["dataset_id"] = ds_id
            db.insert_records(res["records"])
            db.save_quality_report(ds_id, res["report"])
            set_selected_dataset(ds_id)
            st.success(f"Sample loaded as dataset #{ds_id} "
                       f"({res['report']['valid_row_count']}/{res['report']['original_row_count']} valid).")
            st.rerun()

    uploaded = st.file_uploader("Upload CSV (customer / competitor reviews)",
                                type=["csv"], key="csv_upload")
    if uploaded is None:
        return
    data = uploaded.getvalue()
    try:
        validate_file_meta(uploaded.name, len(data))
        df = read_csv_bytes(data)
    except IngestionError as e:
        st.error(str(e))
        return
    if df.empty:
        st.warning("CSV parsed but contains no rows.")
        return
    st.write(f"Detected {len(df.columns)} columns × {len(df)} rows. Preview:")
    st.dataframe(df.head(8), use_container_width=True)

    auto = detect_column_mapping(df)
    st.subheader("Column mapping (auto-detected — adjust if uncertain)")
    opts = [None] + list(df.columns)
    mapping = {}
    cols = st.columns(4)
    for i, role in enumerate(FIELD_ROLES):
        with cols[i % 4]:
            default_idx = opts.index(auto[role]) if auto.get(role) in opts else 0
            mapping[role] = st.selectbox(f"Role: {role}", [str(o) for o in opts],
                                         index=default_idx, key=f"map_{role}")
            if mapping[role] == "None":
                mapping[role] = None
    origin_key = st.radio("Source origin label (keeps competitor vs own data distinct)",
                          list(ORIGINS.keys()), format_func=lambda k: ORIGINS[k],
                          horizontal=True)
    dedupe = st.checkbox("Drop duplicate feedback texts during validation", value=True)
    min_len = st.slider("Minimum feedback length (characters)", 5, 50, 10)

    if st.button("Validate & ingest dataset", type="primary"):
        if not mapping.get("text"):
            st.error("A feedback/text column must be mapped.")
            return
        raw = map_dataframe(df, mapping, [])
        res = validate_records(raw, drop_duplicates=dedupe, min_text_len=min_len)
        if res["report"]["valid_row_count"] == 0:
            st.error("No valid records after validation — nothing ingested. Inspect exclusions below.")
        ds_id = db.create_dataset(Path(uploaded.name).stem, "csv", origin_key,
                                  None, mapping, res["report"]["original_row_count"])
        for r in res["records"]:
            r["dataset_id"] = ds_id
        db.insert_records(res["records"])
        db.save_quality_report(ds_id, res["report"])
        set_selected_dataset(ds_id)
        st.success(f"Ingested as dataset #{ds_id}. Original {res['report']['original_row_count']} → "
                   f"valid {res['report']['valid_row_count']} → excluded "
                   f"{res['report']['excluded_row_count']}.")
        st.rerun()


def _ingest_tab_doc():
    st.markdown("TXT / Markdown research notes (PDF & DOCX supported when `pypdf`/`python-docx` "
                "are installed). Each note becomes traceable records.")
    up = st.file_uploader("Upload research document", type=["txt", "md", "markdown", "pdf", "docx"],
                          key="doc_upload")
    if up is None:
        return
    data = up.getvalue()
    try:
        validate_file_meta(up.name, len(data))
        recs = load_document_as_records(data, up.name)
    except IngestionError as e:
        st.error(str(e))
        return
    if not recs:
        st.warning("No substantial text extracted from this document.")
        return
    st.write(f"Extracted {len(recs)} feedback units:")
    st.dataframe(pd.DataFrame(recs).head(10), use_container_width=True)
    origin_key = st.radio("Origin label", ["market_research", "competitor", "own_customers"],
                          format_func=lambda k: ORIGINS[k], horizontal=True, key="doc_origin")
    if st.button("Ingest document", type="primary"):
        kind = "markdown" if Path(up.name).suffix.lower() in (".md", ".markdown") else \
               Path(up.name).suffix.lower().lstrip(".") or "txt"
        ds_id = db.create_dataset(Path(up.name).stem, kind, origin_key, None, {}, len(recs))
        rows = [{"dataset_id": ds_id, "external_ref": r["external_ref"], "text": r["text"],
                 "rating": None, "review_date": None, "product": None, "segment": None,
                 "competitor": None, "channel": None, "valid": 1, "exclusion_reason": None,
                 "payload": "{}"} for r in recs]
        db.insert_records(rows)
        db.save_quality_report(ds_id, {"original_row_count": len(recs), "valid_row_count": len(recs),
                                       "excluded_row_count": 0, "exclusions": [], "notes":
                                       ["Document split into paragraph-level records."],
                                       "missing_field_summary": {}, "config": {}})
        set_selected_dataset(ds_id)
        st.success(f"Document ingested as dataset #{ds_id}.")
        st.rerun()


def _ingest_tab_paste():
    txt = st.text_area("Paste customer feedback or market observations (one item per line/paragraph)",
                       height=220, placeholder="Trial too short for our team...\nLove the export API...")
    origin_key = st.radio("Origin label", list(ORIGINS.keys()), format_func=lambda k: ORIGINS[k],
                          horizontal=True, key="paste_origin")
    name = st.text_input("Dataset name", value="Pasted feedback")
    if st.button("Ingest pasted text", type="primary"):
        from modules.data_parser import split_text_into_feedback
        recs = split_text_into_feedback(txt or "")
        if not recs:
            st.error("Nothing to ingest — text was empty or too short.")
            return
        ds_id = db.create_dataset(name.strip() or "Pasted feedback", "pasted", origin_key,
                                  None, {}, len(recs))
        rows = [{"dataset_id": ds_id, "external_ref": r["external_ref"], "text": r["text"],
                 "rating": None, "review_date": None, "product": None, "segment": None,
                 "competitor": None, "channel": None, "valid": 1, "exclusion_reason": None,
                 "payload": "{}"} for r in recs]
        db.insert_records(rows)
        db.save_quality_report(ds_id, {"original_row_count": len(recs), "valid_row_count": len(recs),
                                       "excluded_row_count": 0, "exclusions": [], "notes": [],
                                       "missing_field_summary": {}, "config": {}})
        set_selected_dataset(ds_id)
        st.success(f"Ingested {len(recs)} records as dataset #{ds_id}.")
        st.rerun()


def _ingest_tab_manage():
    datasets = db.list_datasets(include_archived=True)
    if not datasets:
        st.info("No datasets yet — load the sample or upload a file.")
        return
    df = pd.DataFrame(datasets)[["id", "name", "source_kind", "origin_label", "row_count",
                                 "archived", "created_at"]]
    st.dataframe(df, use_container_width=True, hide_index=True)

    labels = {d["id"]: f"#{d['id']} {d['name']} ({ORIGINS.get(d['origin_label'],'?')})"
              for d in datasets}
    active = [d for d in datasets if not d["archived"]]
    if active:
        sel = st.selectbox("Select active dataset for downstream pages",
                          [d["id"] for d in active],
                          format_func=lambda i: labels[i],
                          index=next((k for k, d in enumerate(active)
                                      if d["id"] == st.session_state.get("mp_selected_dataset")), 0))
        if sel != st.session_state.get("mp_selected_dataset"):
            set_selected_dataset(sel)
            st.rerun()

    st.subheader("Data quality report (selected dataset)")
    ds_id = st.session_state.get("mp_selected_dataset")
    q = db.latest_quality_report(ds_id) if ds_id else None
    if q:
        c1, c2, c3 = st.columns(3)
        c1.metric("Original rows", q["original_row_count"])
        c2.metric("Valid rows", q["valid_row_count"])
        c3.metric("Excluded", q["excluded_row_count"])
        if q.get("exclusions"):
            st.markdown("**Exclusion reasons (nothing is silently discarded):**")
            ex = pd.DataFrame([{"row": e["row"], "ref": e["ref"], "reasons": "; ".join(e["reasons"])}
                               for e in q["exclusions"]])
            st.dataframe(ex, use_container_width=True, hide_index=True)
        if q.get("notes"):
            for n in q["notes"][:10]:
                st.caption("ℹ️ " + html.escape(str(n)))
        mf = q.get("missing_field_summary") or {}
        if mf:
            st.caption("Missing-value counts: " + ", ".join(f"{k}={v}" for k, v in mf.items()))
    else:
        st.caption("No quality report available for the current selection.")

    st.subheader("Manage dataset")
    with st.expander("Inspect raw records (incl. invalid)"):
        if ds_id:
            recs = db.get_records(ds_id)
            st.dataframe(pd.DataFrame(recs)[["id", "external_ref", "text", "rating", "review_date",
                                             "product", "segment", "valid", "exclusion_reason"]],
                         use_container_width=True, hide_index=True)
    del_id = st.selectbox("Dataset id to archive/delete",
                          [d["id"] for d in datasets if not d["archived"]],
                          format_func=lambda i: labels[i], key="del_sel")
    dependent = db.query("SELECT COUNT(*) c FROM campaigns WHERE dataset_id=?", (del_id,))
    warn = (dependent[0]["c"] if dependent else 0)
    confirm = st.checkbox(f"I understand {warn} campaign(s) reference this dataset. Delete permanently.")
    col_a, col_b = st.columns(2)
    if col_a.button("Archive dataset"):
        db.archive_dataset(del_id)
        st.success(f"Dataset #{del_id} archived (recoverable via DB; UI hides it).")
        st.rerun()
    if col_b.button("Delete dataset permanently", disabled=not confirm, type="secondary"):
        db.delete_dataset(del_id)
        if st.session_state.get("mp_selected_dataset") == del_id:
            st.session_state.pop("mp_selected_dataset", None)
        st.warning(f"Dataset #{del_id} and its records/insights deleted. Campaigns keep their briefs "
                   "but lose the dataset link.")
        st.rerun()


with tab_csv:
    _ingest_tab_csv()
with tab_doc:
    _ingest_tab_doc()
with tab_paste:
    _ingest_tab_paste()
with tab_manage:
    _ingest_tab_manage()
