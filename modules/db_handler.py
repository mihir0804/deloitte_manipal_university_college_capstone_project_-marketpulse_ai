"""SQLite persistence layer for MarketPulse AI & Campaign Studio.

All SQL is parameterized.  Foreign keys are enforced.  Every write goes
through a transaction so failed operations never leave partial state.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from modules.config import DB_PATH, ensure_dirs

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS datasets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    source_kind TEXT NOT NULL,            -- csv | txt | markdown | pasted | sample | pdf | docx
    origin_label TEXT NOT NULL DEFAULT 'own_customers',  -- own_customers | competitor | market_research
    file_path TEXT,
    column_mapping TEXT,                  -- JSON
    row_count INTEGER NOT NULL DEFAULT 0,
    archived INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id INTEGER NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    external_ref TEXT,                    -- original identifier from file
    text TEXT NOT NULL,
    rating REAL,
    review_date TEXT,
    product TEXT,
    segment TEXT,
    competitor TEXT,
    channel TEXT,
    valid INTEGER NOT NULL DEFAULT 1,
    exclusion_reason TEXT,
    payload TEXT                          -- JSON of unmapped columns
);

CREATE TABLE IF NOT EXISTS quality_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id INTEGER NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    report TEXT NOT NULL,                 -- JSON
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analysis_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id INTEGER NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    mode TEXT NOT NULL,                   -- local | ai
    provider TEXT,
    config TEXT,                          -- JSON (reproducibility)
    metrics TEXT,                         -- JSON summary
    status TEXT NOT NULL DEFAULT 'completed',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sentiment_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
    record_id INTEGER NOT NULL REFERENCES records(id) ON DELETE CASCADE,
    sentiment TEXT NOT NULL,
    confidence REAL,
    main_topic TEXT,
    pain_points TEXT, positive_attributes TEXT, feature_requests TEXT,
    customer_intent TEXT, evidence TEXT, method TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS insights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
    dataset_id INTEGER NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    title TEXT NOT NULL, description TEXT NOT NULL, category TEXT NOT NULL,
    evidence TEXT NOT NULL,               -- JSON list
    record_ids TEXT NOT NULL,             -- JSON list
    supporting_count INTEGER NOT NULL DEFAULT 0,
    segments TEXT, business_implication TEXT, recommended_action TEXT,
    confidence TEXT, origin TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id INTEGER REFERENCES datasets(id) ON DELETE CASCADE,
    kind TEXT NOT NULL DEFAULT 'note',    -- note | competitor_observation
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    provenance TEXT NOT NULL DEFAULT 'user_supplied',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    dataset_id INTEGER REFERENCES datasets(id) ON DELETE SET NULL,
    run_id INTEGER REFERENCES analysis_runs(id) ON DELETE SET NULL,
    setup TEXT NOT NULL,                  -- JSON CampaignSetup
    created_at TEXT NOT NULL,
    archived INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS briefs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    content TEXT NOT NULL,                -- JSON CampaignBriefSchema
    insight_ids TEXT,                     -- JSON list of insights used
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL,
    UNIQUE(campaign_id, version)
);

CREATE TABLE IF NOT EXISTS content_assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brief_id INTEGER NOT NULL REFERENCES briefs(id) ON DELETE CASCADE,
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    asset_uid TEXT NOT NULL,              -- stable logical id across versions
    asset_type TEXT NOT NULL,
    version INTEGER NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    cta TEXT, notes TEXT,
    validation TEXT,                      -- JSON checks
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL,
    UNIQUE(asset_uid, version)
);

CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,            -- insight | brief | asset | campaign_pack
    entity_id INTEGER NOT NULL,
    action TEXT NOT NULL,                 -- comment | submit | request_changes | approve | reject | archive | restore | edit
    from_status TEXT, to_status TEXT,
    comment TEXT,
    reviewer TEXT NOT NULL DEFAULT 'local_user',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS exports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER REFERENCES campaigns(id) ON DELETE SET NULL,
    export_type TEXT NOT NULL,            -- pdf | markdown | text | csv
    file_path TEXT NOT NULL,
    meta TEXT,                            -- JSON
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Optional[str] = None):
        ensure_dirs()
        self.path = str(path or DB_PATH)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            conn.commit()

    # ---------------- generic helpers ----------------
    def execute(self, sql: str, params: tuple = ()) -> int:
        with self.connect() as conn:
            cur = conn.execute(sql, params)
            conn.commit()
            return cur.lastrowid

    def query(self, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def query_one(self, sql: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def audit(self, event: str, detail: str = "") -> None:
        self.execute(
            "INSERT INTO audit_events(event, detail, created_at) VALUES (?,?,?)",
            (event, detail[:2000], utcnow()),
        )

    # ---------------- datasets ----------------
    def create_dataset(self, name: str, source_kind: str, origin_label: str,
                       file_path: Optional[str], mapping: dict, row_count: int) -> int:
        ds_id = self.execute(
            "INSERT INTO datasets(name, source_kind, origin_label, file_path, column_mapping,"
            " row_count, created_at) VALUES (?,?,?,?,?,?,?)",
            (name, source_kind, origin_label, file_path, json.dumps(mapping), row_count, utcnow()),
        )
        self.audit("dataset.created", f"dataset={ds_id} name={name}")
        return ds_id

    def list_datasets(self, include_archived: bool = False) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM datasets"
        if not include_archived:
            sql += " WHERE archived = 0"
        return self.query(sql + " ORDER BY id DESC")

    def get_dataset(self, ds_id: int) -> Optional[Dict[str, Any]]:
        return self.query_one("SELECT * FROM datasets WHERE id = ?", (ds_id,))

    def archive_dataset(self, ds_id: int) -> None:
        self.execute("UPDATE datasets SET archived = 1 WHERE id = ?", (ds_id,))
        self.audit("dataset.archived", f"dataset={ds_id}")

    def delete_dataset(self, ds_id: int) -> None:
        """Hard delete with cascade; caller must warn about dependent assets."""
        with self.connect() as conn:
            conn.execute("DELETE FROM datasets WHERE id = ?", (ds_id,))
            conn.commit()
        self.audit("dataset.deleted", f"dataset={ds_id}")

    def insert_records(self, rows: List[Dict[str, Any]]) -> None:
        if not rows:
            return
        with self.connect() as conn:
            conn.executemany(
                "INSERT INTO records(dataset_id, external_ref, text, rating, review_date,"
                " product, segment, competitor, channel, valid, exclusion_reason, payload)"
                " VALUES (:dataset_id, :external_ref, :text, :rating, :review_date,"
                " :product, :segment, :competitor, :channel, :valid, :exclusion_reason, :payload)",
                rows,
            )
            conn.commit()

    def get_records(self, dataset_id: int, only_valid: bool = False) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM records WHERE dataset_id = ?"
        if only_valid:
            sql += " AND valid = 1"
        return self.query(sql + " ORDER BY id", (dataset_id,))

    def count_records(self, dataset_id: int) -> tuple:
        total = self.query_one("SELECT COUNT(*) c FROM records WHERE dataset_id=?", (dataset_id,))["c"]
        valid = self.query_one("SELECT COUNT(*) c FROM records WHERE dataset_id=? AND valid=1",
                               (dataset_id,))["c"]
        return total, valid

    def save_quality_report(self, dataset_id: int, report: dict) -> int:
        return self.execute(
            "INSERT INTO quality_reports(dataset_id, report, created_at) VALUES (?,?,?)",
            (dataset_id, json.dumps(report), utcnow()),
        )

    def latest_quality_report(self, dataset_id: int) -> Optional[dict]:
        row = self.query_one(
            "SELECT report FROM quality_reports WHERE dataset_id=? ORDER BY id DESC LIMIT 1",
            (dataset_id,))
        return json.loads(row["report"]) if row else None

    # ---------------- analysis ----------------
    def create_run(self, dataset_id: int, mode: str, provider: str, config: dict,
                   metrics: dict, status: str = "completed") -> int:
        run_id = self.execute(
            "INSERT INTO analysis_runs(dataset_id, mode, provider, config, metrics, status, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (dataset_id, mode, provider, json.dumps(config), json.dumps(metrics), status, utcnow()),
        )
        self.audit("analysis.run", f"run={run_id} dataset={dataset_id} mode={mode}")
        return run_id

    def list_runs(self, dataset_id: Optional[int] = None) -> List[Dict[str, Any]]:
        if dataset_id:
            return self.query("SELECT * FROM analysis_runs WHERE dataset_id=? ORDER BY id DESC",
                              (dataset_id,))
        return self.query("SELECT * FROM analysis_runs ORDER BY id DESC")

    def get_run(self, run_id: int) -> Optional[Dict[str, Any]]:
        return self.query_one("SELECT * FROM analysis_runs WHERE id=?", (run_id,))

    def save_sentiment_results(self, run_id: int, results: List[Dict[str, Any]]) -> None:
        if not results:
            return
        # inject run_id for callers that omit it; keep caller dicts untouched
        rows = [dict(r) for r in results]
        for r in rows:
            r.setdefault("run_id", run_id)
        with self.connect() as conn:
            conn.executemany(
                "INSERT INTO sentiment_results(run_id, record_id, sentiment, confidence, main_topic,"
                " pain_points, positive_attributes, feature_requests, customer_intent, evidence, method)"
                " VALUES (:run_id, :record_id, :sentiment, :confidence, :main_topic,"
                " :pain_points, :positive_attributes, :feature_requests, :customer_intent,"
                " :evidence, :method)", rows)
            conn.commit()

    def get_sentiment_results(self, run_id: int) -> List[Dict[str, Any]]:
        return self.query("SELECT * FROM sentiment_results WHERE run_id=? ORDER BY record_id", (run_id,))

    def save_insights(self, run_id: int, dataset_id: int, insights: List[Dict[str, Any]]) -> List[int]:
        ids = []
        with self.connect() as conn:
            for ins in insights:
                cur = conn.execute(
                    "INSERT INTO insights(run_id, dataset_id, title, description, category, evidence,"
                    " record_ids, supporting_count, segments, business_implication, recommended_action,"
                    " confidence, origin, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (run_id, dataset_id, ins["title"], ins["description"], ins["category"],
                     json.dumps(ins.get("evidence", [])), json.dumps(ins.get("record_ids", [])),
                     ins.get("supporting_count", 0), json.dumps(ins.get("segments", [])),
                     ins.get("business_implication", ""), ins.get("recommended_action", ""),
                     ins.get("confidence", "medium"), ins.get("origin", "data_derived"), utcnow()))
                ids.append(cur.lastrowid)
            conn.commit()
        self.audit("insights.saved", f"run={run_id} count={len(ids)}")
        return ids

    def list_insights(self, run_id: Optional[int] = None, dataset_id: Optional[int] = None) -> List[Dict[str, Any]]:
        sql, params = "SELECT * FROM insights WHERE 1=1", []
        if run_id:
            sql += " AND run_id=?"; params.append(run_id)
        if dataset_id:
            sql += " AND dataset_id=?"; params.append(dataset_id)
        rows = self.query(sql + " ORDER BY id", tuple(params))
        for r in rows:
            r["evidence"] = json.loads(r["evidence"] or "[]")
            r["record_ids"] = json.loads(r["record_ids"] or "[]")
            r["segments"] = json.loads(r["segments"] or "[]")
        return rows

    def get_insight(self, insight_id: int) -> Optional[Dict[str, Any]]:
        rows = self.list_insights()
        return next((r for r in rows if r["id"] == insight_id), None)

    # ---------------- research notes ----------------
    def add_note(self, title: str, body: str, kind: str = "note",
                 dataset_id: Optional[int] = None) -> int:
        nid = self.execute(
            "INSERT INTO research_notes(dataset_id, kind, title, body, created_at) VALUES (?,?,?,?,?)",
            (dataset_id, kind, title, body, utcnow()))
        self.audit("note.added", f"note={nid} kind={kind}")
        return nid

    def list_notes(self, dataset_id: Optional[int] = None) -> List[Dict[str, Any]]:
        if dataset_id:
            return self.query("SELECT * FROM research_notes WHERE dataset_id=? OR dataset_id IS NULL"
                              " ORDER BY id DESC", (dataset_id,))
        return self.query("SELECT * FROM research_notes ORDER BY id DESC")

    # ---------------- campaigns / briefs ----------------
    def create_campaign(self, name: str, setup: dict, dataset_id: Optional[int],
                        run_id: Optional[int]) -> int:
        cid = self.execute(
            "INSERT INTO campaigns(name, dataset_id, run_id, setup, created_at) VALUES (?,?,?,?,?)",
            (name, dataset_id, run_id, json.dumps(setup), utcnow()))
        self.audit("campaign.created", f"campaign={cid} name={name}")
        return cid

    def list_campaigns(self) -> List[Dict[str, Any]]:
        return self.query("SELECT * FROM campaigns WHERE archived=0 ORDER BY id DESC")

    def get_campaign(self, cid: int) -> Optional[Dict[str, Any]]:
        c = self.query_one("SELECT * FROM campaigns WHERE id=?", (cid,))
        if c:
            c["setup"] = json.loads(c["setup"])
        return c

    def save_brief(self, campaign_id: int, content: dict, insight_ids: List[int],
                   status: str = "draft") -> tuple:
        """Create a NEW version; approved versions are never mutated."""
        with self.connect() as conn:
            row = conn.execute("SELECT COALESCE(MAX(version),0) v FROM briefs WHERE campaign_id=?",
                               (campaign_id,)).fetchone()
            version = row["v"] + 1
            cur = conn.execute(
                "INSERT INTO briefs(campaign_id, version, content, insight_ids, status, created_at)"
                " VALUES (?,?,?,?,?,?)",
                (campaign_id, version, json.dumps(content), json.dumps(insight_ids), status, utcnow()))
            conn.commit()
            bid = cur.lastrowid
        self.audit("brief.saved", f"brief={bid} campaign={campaign_id} v{version}")
        return bid, version

    def update_brief_content(self, brief_id: int, content: dict) -> None:
        """In-place edit allowed ONLY while status is draft/changes_requested."""
        b = self.query_one("SELECT status FROM briefs WHERE id=?", (brief_id,))
        if not b:
            raise ValueError("Brief not found")
        if b["status"] not in ("draft", "changes_requested"):
            raise ValueError(f"Brief is '{b['status']}'; edits require a new version.")
        self.execute("UPDATE briefs SET content=? WHERE id=?", (json.dumps(content), brief_id))

    def get_brief(self, brief_id: int) -> Optional[Dict[str, Any]]:
        b = self.query_one("SELECT * FROM briefs WHERE id=?", (brief_id,))
        if b:
            b["content"] = json.loads(b["content"])
            b["insight_ids"] = json.loads(b["insight_ids"] or "[]")
        return b

    def latest_brief(self, campaign_id: int) -> Optional[Dict[str, Any]]:
        b = self.query_one("SELECT * FROM briefs WHERE campaign_id=? ORDER BY version DESC LIMIT 1",
                           (campaign_id,))
        if b:
            b["content"] = json.loads(b["content"])
            b["insight_ids"] = json.loads(b["insight_ids"] or "[]")
        return b

    def list_brief_versions(self, campaign_id: int) -> List[Dict[str, Any]]:
        return self.query("SELECT id, version, status, created_at FROM briefs WHERE campaign_id=?"
                          " ORDER BY version DESC", (campaign_id,))

    # ---------------- content assets ----------------
    def create_asset(self, brief_id: int, campaign_id: int, asset_uid: str, asset_type: str,
                     title: str, body: str, cta: str, notes: str, validation: dict,
                     status: str = "draft") -> int:
        with self.connect() as conn:
            row = conn.execute("SELECT COALESCE(MAX(version),0) v FROM content_assets WHERE asset_uid=?",
                               (asset_uid,)).fetchone()
            version = row["v"] + 1
            cur = conn.execute(
                "INSERT INTO content_assets(brief_id, campaign_id, asset_uid, asset_type, version,"
                " title, body, cta, notes, validation, status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (brief_id, campaign_id, asset_uid, asset_type, version, title, body, cta, notes,
                 json.dumps(validation), status, utcnow()))
            conn.commit()
            aid = cur.lastrowid
        self.audit("asset.created", f"asset={aid} uid={asset_uid} v{version}")
        return aid

    def update_asset_as_new_version(self, asset_uid: str, title: str, body: str, cta: str,
                                    notes: str, validation: dict) -> int:
        a = self.get_asset_by_uid_latest(asset_uid)
        if not a:
            raise ValueError(f"Asset {asset_uid} not found")
        return self.create_asset(a["brief_id"], a["campaign_id"], asset_uid, a["asset_type"],
                                 title, body, cta, notes, validation, status="draft")

    def get_asset(self, asset_id: int) -> Optional[Dict[str, Any]]:
        a = self.query_one("SELECT * FROM content_assets WHERE id=?", (asset_id,))
        if a:
            a["validation"] = json.loads(a["validation"] or "{}")
        return a

    def get_asset_by_uid_latest(self, asset_uid: str) -> Optional[Dict[str, Any]]:
        a = self.query_one("SELECT * FROM content_assets WHERE asset_uid=? ORDER BY version DESC LIMIT 1",
                           (asset_uid,))
        if a:
            a["validation"] = json.loads(a["validation"] or "{}")
        return a

    def list_assets(self, campaign_id: Optional[int] = None, brief_id: Optional[int] = None,
                    latest_only: bool = True) -> List[Dict[str, Any]]:
        sql, params = "SELECT * FROM content_assets WHERE 1=1", []
        if campaign_id:
            sql += " AND campaign_id=?"; params.append(campaign_id)
        if brief_id:
            sql += " AND brief_id=?"; params.append(brief_id)
        rows = self.query(sql + " ORDER BY asset_uid, version", tuple(params))
        for r in rows:
            r["validation"] = json.loads(r["validation"] or "{}")
        if latest_only:
            best: Dict[str, Dict[str, Any]] = {}
            for r in rows:
                cur = best.get(r["asset_uid"])
                if cur is None or r["version"] > cur["version"]:
                    best[r["asset_uid"]] = r
            rows = sorted(best.values(), key=lambda x: x["id"])
        return rows

    def set_asset_status(self, asset_id: int, new_status: str, comment: str = "",
                         reviewer: str = "local_user") -> None:
        a = self.get_asset(asset_id)
        if not a:
            raise ValueError("Asset not found")
        self._check_transition(a["status"], new_status)
        with self.connect() as conn:
            conn.execute("UPDATE content_assets SET status=? WHERE id=?", (new_status, asset_id))
            conn.execute(
                "INSERT INTO reviews(entity_type, entity_id, action, from_status, to_status,"
                " comment, reviewer, created_at) VALUES ('asset',?,?,?,?,?,?,?)",
                (asset_id, self._action_for(new_status), a["status"], new_status, comment,
                 reviewer, utcnow()))
            conn.commit()
        self.audit("asset.status", f"asset={asset_id} {a['status']}->{new_status}")

    @staticmethod
    def _action_for(status: str) -> str:
        return {"under_review": "submit", "changes_requested": "request_changes",
                "approved": "approve", "rejected": "reject", "archived": "archive"}.get(status, "edit")

    @staticmethod
    def _check_transition(old: str, new: str) -> None:
        allowed = {
            "draft": {"under_review", "archived"},
            "under_review": {"approved", "changes_requested", "rejected", "archived"},
            "changes_requested": {"under_review", "draft", "archived"},
            "approved": {"changes_requested", "archived"},
            "rejected": {"draft", "archived"},
            "archived": {"draft"},
        }
        if new not in allowed.get(old, set()):
            raise ValueError(f"Illegal status transition: {old} -> {new}")

    def force_asset_status(self, asset_id: int, new_status: str, comment: str = "",
                           reviewer: str = "local_user") -> None:
        """Set an asset's status bypassing the transition guard.

        Used only by the campaign-pack bulk review to move drafts straight to
        'under_review' before validating them. The action is recorded in the
        review trail so the workflow history stays complete and auditable.
        """
        a = self.get_asset(asset_id)
        if not a:
            raise ValueError("Asset not found")
        if new_status not in ("draft", "under_review", "changes_requested",
                              "approved", "rejected", "archived"):
            raise ValueError(f"Unknown status '{new_status}'")
        with self.connect() as conn:
            conn.execute("UPDATE content_assets SET status=? WHERE id=?", (new_status, asset_id))
            conn.execute(
                "INSERT INTO reviews(entity_type, entity_id, action, from_status, to_status,"
                " comment, reviewer, created_at) VALUES ('asset',?,?,?,?,?,?,?)",
                (asset_id, self._action_for(new_status), a["status"], new_status,
                 comment or "Bulk pack review (transition guard bypassed)", reviewer, utcnow()))
            conn.commit()
        self.audit("asset.status", f"asset={asset_id} {a['status']}->{new_status} (bulk)")

    def set_brief_status(self, brief_id: int, new_status: str, comment: str = "") -> None:
        b = self.get_brief(brief_id)
        if not b:
            raise ValueError("Brief not found")
        self._check_transition(b["status"], new_status)
        with self.connect() as conn:
            conn.execute("UPDATE briefs SET status=? WHERE id=?", (new_status, brief_id))
            conn.execute(
                "INSERT INTO reviews(entity_type, entity_id, action, from_status, to_status,"
                " comment, reviewer, created_at) VALUES ('brief',?,?,?,?,?,?,?)",
                (brief_id, self._action_for(new_status), b["status"], new_status, comment,
                 "local_user", utcnow()))
            conn.commit()
        self.audit("brief.status", f"brief={brief_id} {b['status']}->{new_status}")

    def add_review(self, entity_type: str, entity_id: int, action: str,
                   comment: str, from_status: str = "", to_status: str = "") -> int:
        return self.execute(
            "INSERT INTO reviews(entity_type, entity_id, action, from_status, to_status, comment,"
            " reviewer, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (entity_type, entity_id, action, from_status, to_status, comment, "local_user", utcnow()))

    def list_reviews(self, entity_type: Optional[str] = None, entity_id: Optional[int] = None) -> List[Dict[str, Any]]:
        sql, params = "SELECT * FROM reviews WHERE 1=1", []
        if entity_type:
            sql += " AND entity_type=?"; params.append(entity_type)
        if entity_id:
            sql += " AND entity_id=?"; params.append(entity_id)
        return self.query(sql + " ORDER BY id", tuple(params))

    # ---------------- exports ----------------
    def record_export(self, campaign_id: Optional[int], export_type: str, file_path: str,
                      meta: dict) -> int:
        eid = self.execute(
            "INSERT INTO exports(campaign_id, export_type, file_path, meta, created_at) VALUES (?,?,?,?,?)",
            (campaign_id, export_type, file_path, json.dumps(meta), utcnow()))
        self.audit("export.created", f"export={eid} type={export_type}")
        return eid

    def list_exports(self) -> List[Dict[str, Any]]:
        return self.query("SELECT * FROM exports ORDER BY id DESC")

    def list_audit(self, limit: int = 100) -> List[Dict[str, Any]]:
        return self.query("SELECT * FROM audit_events ORDER BY id DESC LIMIT ?", (limit,))
