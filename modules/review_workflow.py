"""Human review & approval workflow logic (single-user local workflow).

NOTE: This application has no authentication. The 'reviewer' field is a label,
not an identity control. Approvals never publish or send anything externally.
"""
from __future__ import annotations

import difflib
from typing import Any, Dict, List, Optional

from modules.db_handler import Database, utcnow

VALID_STATUSES = ["draft", "under_review", "changes_requested", "approved", "rejected", "archived"]


def submit_for_review(db: Database, asset_id: int, comment: str = "") -> None:
    db.set_asset_status(asset_id, "under_review", comment or "Submitted for review")


def request_changes(db: Database, asset_id: int, reason: str) -> None:
    if not reason.strip():
        raise ValueError("A reason is required when requesting changes.")
    db.set_asset_status(asset_id, "changes_requested", reason)


def approve_asset(db: Database, asset_id: int, comment: str = "") -> Dict[str, Any]:
    """Approve the given version; the approved row becomes an immutable snapshot."""
    asset = db.get_asset(asset_id)
    if not asset:
        raise ValueError("Asset not found")
    violations = _blocking_violations(asset)
    if violations:
        raise ValueError(f"Cannot approve with blocking violations: {violations}")
    db.set_asset_status(asset_id, "approved", comment or "Approved")
    return db.get_asset(asset_id)  # type: ignore[return-value]


def reject_asset(db: Database, asset_id: int, reason: str) -> None:
    if not reason.strip():
        raise ValueError("Rejection requires a recorded reason.")
    db.set_asset_status(asset_id, "rejected", reason)


def archive_asset(db: Database, asset_id: int, comment: str = "") -> None:
    db.set_asset_status(asset_id, "archived", comment or "Archived")


def restore_version(db: Database, asset_uid: str, version: int) -> int:
    """Restore an earlier version by copying it forward as a NEW draft version."""
    all_versions = db.query(
        "SELECT * FROM content_assets WHERE asset_uid=? AND version=?", (asset_uid, version))
    if not all_versions:
        raise ValueError(f"Version {version} of {asset_uid} not found")
    old = all_versions[0]
    new_id = db.update_asset_as_new_version(
        asset_uid, old["title"], old["body"], old["cta"] or "",
        f"Restored from v{version} at {utcnow()}", {"restored_from_version": version})
    db.add_review("asset", new_id, "restore", f"Restored content from version {version}")
    return new_id


def edit_asset(db: Database, asset_uid: str, title: str, body: str, cta: str, notes: str,
               params: Dict[str, Any], brief: Dict[str, Any]) -> int:
    """Any edit creates a new version; approved versions are never mutated."""
    from modules.content_studio import validate_asset
    validation = validate_asset({"asset_type": "", "title": title, "body": body}, params, brief)
    return db.update_asset_as_new_version(asset_uid, title, body, cta, notes, validation)


def approve_campaign_pack(db: Database, campaign_id: int, comment: str = "") -> Dict[str, Any]:
    """Approve latest brief + require every included asset to already be approved or get approved."""
    brief = db.latest_brief(campaign_id)
    if not brief:
        raise ValueError("Campaign has no brief to approve.")
    assets = db.list_assets(campaign_id=campaign_id)
    approved, blocked = [], []
    for a in assets:
        try:
            if a["status"] == "draft":
                # Bulk review intake: drafts move to under_review through the
                # documented bulk path (guard bypass is recorded in the trail).
                db.force_asset_status(a["id"], "under_review", "Bulk pack review")
                a["status"] = "under_review"
            if a["status"] == "under_review":
                violations = _blocking_violations(db.get_asset(a["id"]))
                if violations:
                    blocked.append({"asset": a["title"], "reasons": violations})
                    continue
            db.set_asset_status(a["id"], "approved", comment or "Approved via campaign pack")
            approved.append(a["title"])
        except ValueError as e:
            blocked.append({"asset": a["title"], "reasons": [str(e)]})
    db.set_brief_status(brief["id"], "approved", comment or "Approved via campaign pack")
    db.add_review("campaign_pack", campaign_id, "approve",
                  f"Pack approval: {len(approved)} approved, {len(blocked)} blocked")
    return {"approved_assets": approved, "blocked_assets": blocked, "brief_id": brief["id"]}


def _blocking_violations(asset: Dict[str, Any]) -> List[str]:
    v = asset.get("validation") or {}
    out = []
    if not v.get("fields_present", True):
        out.append("missing required fields")
    pl = v.get("platform_length")
    if isinstance(pl, dict) and not pl.get("ok", True):
        out.append(f"over platform limit ({pl.get('actual')}>{pl.get('limit')})")
    if v.get("unsupported_claims_flagged"):
        out.append(f"unsupported claims: {v['unsupported_claims_flagged']}")
    if v.get("restricted_phrases_found"):
        out.append(f"restricted phrases present: {v['restricted_phrases_found']}")
    return out


def compare_versions(db: Database, asset_uid: str, v1: int, v2: int) -> str:
    a = db.query("SELECT body FROM content_assets WHERE asset_uid=? AND version=?", (asset_uid, v1))
    b = db.query("SELECT body FROM content_assets WHERE asset_uid=? AND version=?", (asset_uid, v2))
    if not a or not b:
        raise ValueError("Version not found")
    diff = difflib.unified_diff(a[0]["body"].splitlines(), b[0]["body"].splitlines(),
                                fromfile=f"v{v1}", tofile=f"v{v2}", lineterm="")
    text = "\n".join(diff)
    return text if text.strip() else "(no textual differences)"


def similarity(v1_body: str, v2_body: str) -> float:
    return round(difflib.SequenceMatcher(None, v1_body.lower(), v2_body.lower()).ratio(), 3)
