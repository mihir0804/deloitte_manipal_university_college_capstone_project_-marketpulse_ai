"""Page 5 - Multichannel content studio."""
from __future__ import annotations

import html
import uuid

import streamlit as st

from modules.ai_provider import AIError, generate_content_ai
from modules.config import get_ai_config
from modules.content_studio import (flag_near_duplicates, generate_local_assets,
                                    validate_asset)
from modules.state import (ai_status_badge, get_db, selected_campaign_id,
                           status_pill)

st.set_page_config(page_title="Content Studio", page_icon="✍️", layout="wide")
st.title("✍️ Module 5 · Multichannel Content Studio")
st.markdown(ai_status_badge())

db = get_db()
campaigns = db.list_campaigns()
if not campaigns:
    st.warning("Create a campaign brief first (page 4).")
    st.stop()
labels = {c["id"]: f"#{c['id']} {c['name']}" for c in campaigns}
sel = st.selectbox("Campaign", list(labels.keys()), format_func=lambda i: labels[i],
                   index=next((k for k, c in enumerate(campaigns)
                               if c["id"] == selected_campaign_id()), 0))
if sel != selected_campaign_id():
    st.session_state["mp_selected_campaign"] = sel
brief_row = db.latest_brief(sel)
if not brief_row:
    st.info("Selected campaign has no brief.")
    st.stop()
brief = brief_row["content"]
camp = db.get_campaign(sel)

gen_tab, edit_tab = st.tabs(["Generate assets", "Review & edit existing"])

with gen_tab:
    with st.form("content_form"):
        c1, c2, c3 = st.columns(3)
        channel = c1.selectbox("Marketing channel", ["linkedin", "email", "x", "instagram",
                                                     "facebook", "search_ad", "social_ad",
                                                     "landing_page", "faq", "video", "calendar",
                                                     "ab_test"])
        fmt = c2.selectbox("Content format", ["post", "caption", "script", "sequence", "set"])
        length = c2.text_input("Desired length hint", value="medium")
        objective = c3.selectbox("Campaign objective", [brief.get("business_objective", "")] or ["general"])
        voice = c1.text_input("Brand voice", value=camp["setup"].get("brand_voice", "practical"))
        primary_msg = st.text_area("Primary message",
                                   value=brief.get("value_proposition", "")[:300])
        cta = c2.text_input("Call to action",
                            value=camp["setup"].get("desired_action") or "Book a demo")
        variations = c3.slider("Number of variations", 1, 4, 2)
        required = st.text_input("Required phrases (comma separated)", value="")
        restricted = st.text_input("Restricted phrases (comma separated)", value="guaranteed,#1")
        mode = st.radio("Mode", ["local_template", "ai"], horizontal=True,
                        format_func=lambda m: "Local template" if m == "local_template"
                        else "AI-generated", key="content_mode")
        submitted = st.form_submit_button("Generate content", type="primary")

    if submitted:
        params = {"channel": channel, "format": fmt, "variations": variations, "cta": cta,
                  "brand_voice": voice, "primary_message": primary_msg,
                  "required_phrases": required, "restricted_phrases": restricted,
                  "product": camp["setup"].get("product_service", ""), "length": length}
        try:
            if mode == "ai":
                raw_assets = generate_content_ai(brief, params, get_ai_config())
                method_note = "AI-generated (validated)"
            else:
                raw_assets = generate_local_assets(brief, params)
                method_note = "Local template (deterministic — NOT LLM output)"
        except AIError as e:
            st.error(f"AI generation failed: {e}")
            st.info("Nothing was overwritten. Retry or switch to Local template mode.")
            st.stop()

        dup_pairs = flag_near_duplicates(raw_assets)
        created = 0
        for idx, a in enumerate(raw_assets):
            v = validate_asset(a, params, brief)
            v["generation_method"] = method_note
            if any(idx in pair for pair in dup_pairs):
                v["near_duplicate_of_other_variant"] = True
            uid = f"{channel}-{uuid.uuid4().hex[:8]}"
            db.create_asset(brief_row["id"], sel, uid, a["asset_type"], a["title"],
                            a["body"], a.get("cta", ""), a.get("notes", ""), v)
            created += 1
        db.audit("assets.generated", f"campaign={sel} count={created} mode={mode}")
        msg = f"Created {created} editable asset versions ({method_note})."
        if dup_pairs:
            msg += f" ⚠️ {len(dup_pairs)} near-duplicate variant pair(s) flagged."
        st.success(msg)
        st.rerun()

with edit_tab:
    assets = db.list_assets(campaign_id=sel)
    if not assets:
        st.info("No assets yet for this campaign.")
        st.stop()
    alabels = {a["id"]: f"[{a['status']}] {a['title']} ({a['asset_type']}) v{a['version']}"
               for a in assets}
    aid = st.selectbox("Asset", list(alabels.keys()), format_func=lambda i: alabels[i])
    asset = db.get_asset(aid)
    st.markdown(f"Status: {status_pill(asset['status'])} · uid `{asset['asset_uid']}` · "
                f"linked brief #{asset['brief_id']}", unsafe_allow_html=True)

    with st.form("edit_asset_form"):
        n_title = st.text_input("Title", asset["title"])
        n_body = st.text_area("Body", asset["body"], height=220)
        n_cta = st.text_input("CTA", asset.get("cta") or "")
        n_notes = st.text_input("Notes", asset.get("notes") or "")
        save_edit = st.form_submit_button("Save edit (creates new version; approved snapshots preserved)")
    if save_edit:
        params = {"cta": n_cta, "required_phrases": "", "restricted_phrases": ""}
        new_id = None
        try:
            from modules.review_workflow import edit_asset
            new_id = edit_asset(db, asset["asset_uid"], n_title, n_body, n_cta, n_notes,
                                params, brief)
        except Exception as e:
            st.error(str(e))
        if new_id:
            st.success(f"Saved as v{db.get_asset(new_id)['version']} (draft). Earlier versions unchanged.")
            st.rerun()

    st.subheader("Quality checks")
    v = asset["validation"] or {}
    rows = []
    for k, val in v.items():
        ok = val is True or (isinstance(val, list) and not val) or \
             (isinstance(val, dict) and val.get("ok", True)) or (k in ("pain_point_reflected",) and val is None)
        rows.append({"check": k, "result": "✅ pass" if ok else f"⚠️ {html.escape(str(val))}"})
    for r in rows:
        st.markdown(f"- **{r['check']}**: {r['result']}", unsafe_allow_html=True)

    st.subheader("Version history")
    vers = db.query("SELECT id, version, status, created_at FROM content_assets WHERE asset_uid=?"
                    " ORDER BY version", (asset["asset_uid"],))
    for vv in vers:
        st.markdown(f"- v{vv['version']} · {status_pill(vv['status'])} · {vv['created_at']}",
                    unsafe_allow_html=True)
    if len(vers) >= 2:
        c_a, c_b = st.columns(2)
        va = c_a.selectbox("Compare v", [x["version"] for x in vers], index=len(vers) - 2)
        vb = c_b.selectbox("with v", [x["version"] for x in vers], index=len(vers) - 1)
        from modules.review_workflow import compare_versions
        diff = compare_versions(db, asset["asset_uid"], va, vb)
        st.code(diff or "(no differences)", language="diff")
        restore = st.button(f"Restore v{va} as new draft version")
        if restore:
            from modules.review_workflow import restore_version
            new_id = restore_version(db, asset["asset_uid"], va)
            st.success(f"Restored → v{db.get_asset(new_id)['version']}.")
            st.rerun()
