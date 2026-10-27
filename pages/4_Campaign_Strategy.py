"""Page 4 - Campaign brief & strategy generator."""
from __future__ import annotations

import json

import streamlit as st
from pydantic import ValidationError

from modules.ai_provider import AIError, generate_brief_ai
from modules.campaign_builder import build_local_brief, regenerate_section
from modules.config import get_ai_config
from modules.models import CHANNELS, CampaignSetup
from modules.state import (ai_status_badge, get_db, selected_campaign_id,
                           selected_run_id, set_selected_campaign)

st.set_page_config(page_title="Campaign Strategy", page_icon="🎯", layout="wide")
st.title("🎯 Module 4 · Campaign Brief & Strategy Generator")
st.markdown(ai_status_badge())

db = get_db()
run_id = selected_run_id() or (db.list_runs()[0]["id"] if db.list_runs() else None)
if not run_id:
    st.warning("No analysis run exists. Generate insights first (page 2).")
    st.stop()

insights = db.list_insights(run_id=run_id)
if not insights:
    st.error("The selected run produced no insights; a brief requires insight records.")
    st.stop()
run = db.get_run(run_id)
metrics = json.loads(run["metrics"] or "{}")

tab_setup, tab_briefs = st.tabs(["New campaign", "Existing campaigns"])

with tab_setup:
    st.subheader("Campaign setup")
    with st.form("campaign_form"):
        c1, c2 = st.columns(2)
        name = c1.text_input("Campaign name *", value="Q4 Feedback-Led Growth")
        product = c2.text_input("Product / service *", value="InsightHub Pro")
        objective = c1.text_input("Business objective *",
                                  value="Increase qualified demo requests among mid-market buyers")
        target = c2.text_input("Target market *", value="B2B SaaS operations & CX teams")
        segment_opts = sorted({s for i in insights for s in i["segments"]}) or ["all segments"]
        segment = c1.selectbox("Preferred audience segment", segment_opts)
        geo = c2.text_input("Geographic market", value="North America")
        positioning = c1.text_input("Brand positioning", value="Evidence-led customer intelligence")
        budget = c2.text_input("Budget (optional)", value="$40k")
        duration = c1.text_input("Duration", value="6 weeks")
        action = c2.text_input("Desired customer action", value="Book a guided demo")
        voice = c1.text_input("Brand voice", value="Practical, credible, jargon-light")
        restrictions = c2.text_area("Messaging restrictions", value="No competitor disparagement; no unverified numbers")
        comp_ctx = st.text_area("Optional competitor context (your observations only)")
        channels = st.multiselect("Primary channels", CHANNELS, default=["linkedin", "email"])
        mode = st.radio("Generation mode", ["local_template", "ai"], horizontal=True,
                        format_func=lambda m: "Local template (deterministic)" if m == "local_template"
                        else "AI-generated (validated)", key="brief_mode")
        submitted = st.form_submit_button("Generate campaign brief", type="primary")

    if submitted:
        try:
            setup = CampaignSetup(campaign_name=name, product_service=product,
                                  business_objective=objective, target_market=target,
                                  audience_segment=segment, geographic_market=geo,
                                  brand_positioning=positioning, budget=budget,
                                  duration=duration, channels=channels, desired_action=action,
                                  brand_voice=voice, restrictions=restrictions,
                                  competitor_context=comp_ctx)
        except ValidationError as e:
            st.error(f"Fix these inputs:\n{e}")
            st.stop()
        setup_d = setup.model_dump()
        cid = db.create_campaign(name, setup_d, run["dataset_id"], run_id)
        set_selected_campaign(cid)
        cfg = get_ai_config()
        try:
            if mode == "ai":
                content = generate_brief_ai(setup_d, insights, cfg)
                method = f"ai:{cfg.provider}"
            else:
                built = build_local_brief(setup_d, insights, metrics)
                content, method = built["brief"], "local_template"
            bid, version = db.save_brief(cid, content, [i["id"] for i in insights], status="draft")
            db.audit("brief.generated", f"campaign={cid} method={method}")
            st.success(f"Campaign #{cid} created · brief v{version} generated via **{method}**.")
            st.rerun()
        except AIError as e:
            db.add_review("campaign", cid, "comment",
                          f"AI generation failed ({str(e)[:200]}); campaign setup preserved.")
            st.error(f"AI generation failed: {e}")
            st.info("Your campaign setup is saved (campaign id shown above). Retry, or regenerate "
                    "this campaign's brief using Local template mode.")
        except Exception as e:  # schema validation etc.
            st.error(f"Brief generation error: {e}. Setup preserved as campaign #{cid}.")

with tab_briefs:
    campaigns = db.list_campaigns()
    if not campaigns:
        st.info("No campaigns yet.")
    else:
        labels = {c["id"]: f"#{c['id']} {c['name']}" for c in campaigns}
        sel = st.selectbox("Select campaign", list(labels.keys()),
                           format_func=lambda i: labels[i],
                           index=next((k for k, c in enumerate(campaigns)
                                       if c["id"] == selected_campaign_id()), 0))
        if sel != selected_campaign_id():
            set_selected_campaign(sel)
        camp = db.get_campaign(sel)
        brief_row = db.latest_brief(sel)
        if not brief_row:
            st.info("This campaign has no brief yet — generate one in the New campaign tab.")
            st.stop()
        brief = brief_row["content"]

        versions = db.list_brief_versions(sel)
        st.caption(f"Brief v{brief_row['version']} · status **{brief_row['status']}** · "
                   f"{len(versions)} version(s) total")

        st.subheader("Persona (editable)")
        p = brief["persona"]
        with st.form("persona_form"):
            p_name = st.text_input("Persona name", p["name"])
            p_needs = st.text_area("Needs & goals (one per line)", "\n".join(p["needs_goals"]))
            p_pains = st.text_area("Pain points (one per line)", "\n".join(p["pain_points"]))
            p_obj = st.text_area("Objections (one per line)", "\n".join(p["objections"]))
            p_msg = st.text_area("Messaging preferences", p["messaging_preferences"])
            st.caption("⚠️ Demographics are labelled inferred unless present in the dataset.")
            save = st.form_submit_button("Save persona edit (new brief version)")
        if save:
            new_persona = dict(p)
            new_persona.update({"name": p_name,
                                "needs_goals": [x for x in p_needs.splitlines() if x.strip()],
                                "pain_points": [x for x in p_pains.splitlines() if x.strip()],
                                "objections": [x for x in p_obj.splitlines() if x.strip()],
                                "messaging_preferences": p_msg})
            updated = regenerate_section(brief, "persona", new_persona)
            bid, version = db.save_brief(sel, updated, brief_row["insight_ids"], status="draft")
            db.add_review("brief", bid, "edit", "Persona edited -> new version")
            st.success(f"Saved as brief v{version}.")
            st.rerun()

        st.subheader("Regenerate / edit an individual section")
        sec_keys = [k for k in brief.keys() if k != "persona"]
        sec = st.selectbox("Section", sec_keys, key="sec_sel")
        cur = brief[sec]
        cur_txt = json.dumps(cur, indent=2, ensure_ascii=False) if isinstance(cur, (list, dict)) else str(cur)
        new_txt = st.text_area(f"Content of '{sec}'", cur_txt, height=180, key="sec_edit")
        colA, colB = st.columns(2)
        if colA.button("Apply section edit"):
            try:
                val = json.loads(new_txt) if isinstance(cur, (list, dict)) else new_txt
                updated = regenerate_section(brief, sec, val)
                bid, version = db.save_brief(sel, updated, brief_row["insight_ids"], status="draft")
                db.add_review("brief", bid, "edit", f"Section '{sec}' edited")
                st.success(f"Applied → brief v{version}.")
                st.rerun()
            except (ValueError, ValidationError) as e:
                st.error(f"Invalid content for this section: {e}")
        if colB.button(f"Regenerate '{sec}' from insights (local)"):
            rebuilt = build_local_brief(camp["setup"], insights, metrics)["brief"]
            updated = regenerate_section(brief, sec, rebuilt[sec])
            bid, version = db.save_brief(sel, updated, brief_row["insight_ids"], status="draft")
            db.add_review("brief", bid, "edit", f"Section '{sec}' regenerated from insights")
            st.success(f"Section regenerated → brief v{version}.")
            st.rerun()

        st.subheader("Full brief view")
        for k in ["overview", "business_objective", "value_proposition", "usp", "cta_strategy"]:
            st.markdown(f"**{k.replace('_',' ').title()}:** {brief[k]}")
        for k in ["messaging_pillars", "supporting_evidence", "channel_strategy", "kpis",
                  "assumptions", "risks", "testing_recommendations", "timeline", "content_themes"]:
            st.markdown(f"**{k.replace('_',' ').title()}:**")
            for item in brief[k]:
                st.markdown(f"- {item}")
        st.markdown(f"**Linked insights:** {[i['title'] for i in insights][:6]} …")
