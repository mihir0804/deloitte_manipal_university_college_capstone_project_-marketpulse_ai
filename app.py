"""MarketPulse AI & Campaign Studio - Streamlit entry point."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from modules.config import ASSETS_DIR, get_ai_config
from modules.state import ai_status_badge, get_db

st.set_page_config(
    page_title="MarketPulse AI & Campaign Studio",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

_css = Path(ASSETS_DIR) / "style.css"
if _css.exists():
    st.markdown(f"<style>{_css.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)

db = get_db()
datasets = db.list_datasets()
runs = db.list_runs()
campaigns = db.list_campaigns()
assets = db.list_assets()
approved = sum(1 for a in assets if a["status"] == "approved")

st.title("📈 MarketPulse AI & Campaign Studio")
st.caption("Enterprise market intelligence, customer insights and generative campaign automation. "
           "**Local single-user workflow** — no authentication or external publishing is performed.")
st.markdown(ai_status_badge())

st.divider()
c1, c2, c3, c4 = st.columns(4)
c1.metric("Datasets", len(datasets))
c2.metric("Analysis runs", len(runs))
c3.metric("Campaigns", len(campaigns))
c4.metric("Approved assets", f"{approved}/{len(assets)}")

st.subheader("Workflow")
st.markdown("""
**Customer Data → Quality Validation → Sentiment Analysis → Market Insights → Personas →
Campaign Strategy → Content Generation → Human Review → Approved Pack → Export**
""")

if not datasets:
    st.info("No datasets yet. Open **1 · Data Ingestion** to load the built-in sample dataset "
            "or upload your own CSV/TXT/MD feedback.")
else:
    st.subheader("Recent activity (audit trail)")
    events = db.list_audit(limit=12)
    for e in events:
        st.text(f"{e['created_at']}  {e['event']}: {e['detail']}")

with st.sidebar:
    st.header("Navigation")
    st.markdown("""
1. **Data Ingestion** – load & validate sources
2. **Insights & Analytics** – sentiment + evidence drill-down
3. **Market Intelligence** – competitor & positioning
4. **Campaign Strategy** – brief generator
5. **Content Studio** – multichannel copy
6. **Review & Approval** – workflow states
7. **History & Exports** – PDF/MD/CSV packs
""")
    cfg = get_ai_config()
    st.caption(f"Provider: `{cfg.provider}` | model: "
               f"`{cfg.openai_model if cfg.provider=='openai' else cfg.gemini_model if cfg.provider=='gemini' else 'n/a'}`")
    st.caption("Credentials are read from environment variables only (.env supported).")
