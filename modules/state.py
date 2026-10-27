"""Shared Streamlit state helpers (DB handle, selection persistence)."""
from __future__ import annotations

from typing import Any, Dict, Optional

import streamlit as st

from modules.config import get_ai_config
from modules.db_handler import Database


def get_db() -> Database:
    if "mp_db" not in st.session_state:
        st.session_state.mp_db = Database()
    return st.session_state.mp_db


def selected_dataset_id() -> Optional[int]:
    return st.session_state.get("mp_selected_dataset")


def set_selected_dataset(ds_id: int) -> None:
    st.session_state["mp_selected_dataset"] = ds_id


def selected_run_id() -> Optional[int]:
    return st.session_state.get("mp_selected_run")


def set_selected_run(run_id: int) -> None:
    st.session_state["mp_selected_run"] = run_id


def selected_campaign_id() -> Optional[int]:
    return st.session_state.get("mp_selected_campaign")


def set_selected_campaign(cid: int) -> None:
    st.session_state["mp_selected_campaign"] = cid


def ai_status_badge() -> str:
    cfg = get_ai_config()
    if cfg.available():
        return f"🟢 AI mode available: {cfg.display_name()}"
    return "🟠 Local Analysis Mode (no API key configured)"


STATUS_LABELS = {
    "draft": "Draft", "under_review": "Under Review", "changes_requested": "Changes Requested",
    "approved": "Approved", "rejected": "Rejected", "archived": "Archived",
}
STATUS_COLORS = {"draft": "#8a94a6", "under_review": "#d97706", "changes_requested": "#dc2626",
                 "approved": "#16a34a", "rejected": "#7f1d1d", "archived": "#4b5563"}


def status_pill(status: str) -> str:
    color = STATUS_COLORS.get(status, "#8a94a6")
    label = STATUS_LABELS.get(status, status)
    return (f"<span style='background:{color};color:white;padding:2px 10px;"
            f"border-radius:12px;font-size:0.78rem;font-weight:600'>{label}</span>")
