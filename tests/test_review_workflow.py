import pytest

from modules import review_workflow as rw

BRIEF = {"overview": "o", "business_objective": "b", "persona": {"name": "p", "pain_points": ["slow reports"]},
         "value_proposition": "v", "usp": "u", "messaging_pillars": ["mp"],
         "supporting_evidence": [], "recommended_channels": [], "channel_strategy": [],
         "content_themes": [], "cta_strategy": "", "timeline": [], "kpis": [],
         "assumptions": [], "risks": [], "testing_recommendations": []}


def make_asset(db, validation=None, status="draft"):
    ds = db.create_dataset("d", "csv", "own_customers", None, {}, 0)
    cid = db.create_campaign("c", {}, ds, None)
    bid, _ = db.save_brief(cid, BRIEF, [])
    aid = db.create_asset(bid, cid, "u-" + str(len(db.list_assets())), "linkedin_post",
                          "Title", "Body text", "CTA", "", validation or {"fields_present": True})
    return cid, bid, aid


def test_happy_path_transitions(db):
    cid, bid, aid = make_asset(db)
    rw.submit_for_review(db, aid)
    assert db.get_asset(aid)["status"] == "under_review"
    approved = rw.approve_asset(db, aid, "looks good")
    assert approved["status"] == "approved"


def test_illegal_transition_rejected(db):
    cid, bid, aid = make_asset(db)
    with pytest.raises(ValueError):
        db.set_asset_status(aid, "approved", "skip review")  # draft -> approved illegal


def test_changes_requested_then_resubmit(db):
    cid, bid, aid = make_asset(db)
    rw.submit_for_review(db, aid)
    rw.request_changes(db, aid, "tone too casual")
    assert db.get_asset(aid)["status"] == "changes_requested"
    with pytest.raises(ValueError):
        rw.request_changes(db, aid, "   ")  # empty reason rejected
    db.set_asset_status(aid, "under_review", "fixed")


def test_approved_snapshot_immutable_edit_creates_version(db):
    cid, bid, aid = make_asset(db)
    rw.submit_for_review(db, aid)
    rw.approve_asset(db, aid)
    asset = db.get_asset(aid)
    new_id = rw.edit_asset(db, asset["asset_uid"], "New title", "Edited body", "CTA", "",
                           {"cta": "CTA"}, BRIEF)
    assert db.get_asset(aid)["status"] == "approved"       # snapshot untouched
    assert db.get_asset(aid)["body"] == "Body text"
    assert db.get_asset(new_id)["version"] == 2
    assert db.get_asset(new_id)["status"] == "draft"


def test_approval_blocked_on_violations(db):
    cid, bid, aid = make_asset(db, validation={"fields_present": True,
                                               "unsupported_claims_flagged": ["300%"]})
    rw.submit_for_review(db, aid)
    with pytest.raises(ValueError):
        rw.approve_asset(db, aid)


def test_reject_requires_reason(db):
    cid, bid, aid = make_asset(db)
    rw.submit_for_review(db, aid)
    with pytest.raises(ValueError):
        rw.reject_asset(db, aid, "")


def test_restore_version(db):
    cid, bid, aid = make_asset(db)
    asset = db.get_asset(aid)
    rw.edit_asset(db, asset["asset_uid"], "Changed", "Changed body", "", "", {}, BRIEF)
    new_id = rw.restore_version(db, asset["asset_uid"], 1)
    restored = db.get_asset(new_id)
    assert restored["version"] == 3 and restored["body"] == "Body text"


def test_review_history_records_comments(db):
    cid, bid, aid = make_asset(db)
    rw.submit_for_review(db, aid, "first pass")
    rw.request_changes(db, aid, "add CTA emphasis")
    hist = db.list_reviews("asset", aid)
    assert len(hist) == 2
    assert hist[0]["action"] == "submit" and hist[1]["action"] == "request_changes"
    assert hist[1]["comment"] == "add CTA emphasis"


def test_compare_versions(db):
    cid, bid, aid = make_asset(db)
    a = db.get_asset(aid)
    rw.edit_asset(db, a["asset_uid"], "T", "Body text changed", "", "", {}, BRIEF)
    diff = rw.compare_versions(db, a["asset_uid"], 1, 2)
    assert "Body text" in diff


def test_pack_approval_and_blocking(db):
    cid, bid, aid = make_asset(db)
    bad_ds = cid
    bad = db.create_asset(bid, cid, "bad-uid", "x_post", "Bad", "x" * 300, "", "",
                          {"fields_present": True, "platform_length": {"limit": 280, "actual": 300, "ok": False}})
    result = rw.approve_campaign_pack(db, cid)
    assert "Title" in result["approved_assets"]
    assert any(x["asset"] == "Bad" for x in result["blocked_assets"])
    assert db.get_asset(bad)["status"] != "approved"
    assert db.latest_brief(cid)["status"] == "approved"
