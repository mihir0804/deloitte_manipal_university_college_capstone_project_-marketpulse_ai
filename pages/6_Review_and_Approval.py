"""Page 6 - Human review & approval workflow (local single-user)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from modules import review_workflow as rw
from modules.state import get_db, selected_campaign_id, status_pill

st.set_page_config(page_title="Review & Approval", page_icon="✅", layout="wide")
st.title("✅ Module 6 · Human Review & Approval Workflow")
st.warning("**Local single-user workflow.** There is no authentication: the reviewer field is a "
           "label only. Approving content here never publishes or sends anything externally.")

db = get_db()
campaigns = db.list_campaigns()
if not campaigns:
    st.info("No campaigns yet — create one on page 4.")
    st.stop()
labels = {c["id"]: f"#{c['id']} {c['name']}" for c in campaigns}
sel = st.selectbox("Campaign", list(labels.keys()), format_func=lambda i: labels[i],
                   index=next((k for k, c in enumerate(campaigns)
                               if c["id"] == selected_campaign_id()), 0))
st.session_state["mp_selected_campaign"] = sel

tab_assets, tab_brief, tab_pack, tab_history = st.tabs(
    ["Content assets", "Brief review", "Campaign pack approval", "Review history"])

with tab_assets:
    assets = db.list_assets(campaign_id=sel)
    if not assets:
        st.info("No assets generated yet (page 5).")
    else:
        df = pd.DataFrame([{"id": a["id"], "title": a["title"], "type": a["asset_type"],
                            "v": a["version"], "status": a["status"]} for a in assets])
        st.dataframe(df, use_container_width=True, hide_index=True)
        aid = st.selectbox("Asset to act on", [a["id"] for a in assets],
                           format_func=lambda i: f"#{i} · " + next(a["title"] for a in assets if a["id"] == i))
        asset = db.get_asset(aid)
        st.markdown(f"Current status: {status_pill(asset['status'])}", unsafe_allow_html=True)
        comment = st.text_area("Reviewer comment / reason", key="review_comment")
        b1, b2, b3, b4, b5 = st.columns(5)
        if b1.button("Submit for review"):
            try:
                rw.submit_for_review(db, aid, comment); st.rerun()
            except ValueError as e:
                st.error(str(e))
        if b2.button("Request changes"):
            try:
                rw.request_changes(db, aid, comment); st.rerun()
            except ValueError as e:
                st.error(str(e))
        if b3.button("Approve"):
            try:
                approved = rw.approve_asset(db, aid, comment)
                st.success(f"Approved v{approved['version']} — snapshot preserved.")
                st.rerun()
            except ValueError as e:
                st.error(str(e))
        if b4.button("Reject"):
            try:
                rw.reject_asset(db, aid, comment); st.rerun()
            except ValueError as e:
                st.error(str(e))
        if b5.button("Archive"):
            try:
                rw.archive_asset(db, aid, comment); st.rerun()
            except ValueError as e:
                st.error(str(e))

        st.subheader("Full body")
        st.text(asset["body"])
        hist = db.list_reviews("asset", aid)
        if hist:
            st.subheader("This asset's review trail")
            for h in hist:
                st.caption(f"{h['created_at']} · {h['action']} "
                           f"({h['from_status'] or '-'}→{h['to_status'] or '-'}) · {h['comment']}")

with tab_brief:
    brief_row = db.latest_brief(sel)
    if not brief_row:
        st.info("No brief for this campaign.")
    else:
        st.markdown(f"Brief v{brief_row['version']} — {status_pill(brief_row['status'])}",
                    unsafe_allow_html=True)
        versions = db.list_brief_versions(sel)
        st.dataframe(pd.DataFrame(versions), use_container_width=True, hide_index=True)
        bcomment = st.text_area("Brief review comment", key="brief_comment")
        bb1, bb2, bb3 = st.columns(3)
        if bb1.button("Submit brief for review"):
            try:
                db.set_brief_status(brief_row["id"], "under_review", bcomment); st.rerun()
            except ValueError as e:
                st.error(str(e))
        if bb2.button("Approve brief"):
            try:
                db.set_brief_status(brief_row["id"], "approved", bcomment or "Brief approved")
                st.success("Brief version approved and locked; later edits create new versions.")
                st.rerun()
            except ValueError as e:
                st.error(str(e))
        if bb3.button("Request brief changes"):
            try:
                db.set_brief_status(brief_row["id"], "changes_requested", bcomment)
                st.rerun()
            except ValueError as e:
                st.error(str(e))

with tab_pack:
    st.markdown("Approve the **complete campaign pack**: latest brief + all currently valid assets. "
                "Assets with blocking violations are listed instead of force-approved.")
    pcomment = st.text_input("Pack approval note", value="Campaign pack review session")
    if st.button("Approve complete campaign pack", type="primary"):
        try:
            result = rw.approve_campaign_pack(db, sel, pcomment)
            st.success(f"Approved {len(result['approved_assets'])} assets + brief #{result['brief_id']}.")
            if result["blocked_assets"]:
                st.warning("Blocked (fix and re-approve individually):")
                st.dataframe(pd.DataFrame(result["blocked_assets"]), use_container_width=True,
                             hide_index=True)
            st.rerun()
        except ValueError as e:
            st.error(str(e))

with tab_history:
    reviews = db.list_reviews()
    if not reviews:
        st.info("No review events yet.")
    else:
        st.dataframe(pd.DataFrame(reviews)[["created_at", "entity_type", "entity_id", "action",
                                            "from_status", "to_status", "comment", "reviewer"]],
                     use_container_width=True, hide_index=True)
