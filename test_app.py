"""
App-level regression tests: drive the REAL Streamlit UI (AppTest) against a
temporary database, so your saved data is never touched.
"""

from datetime import timedelta

import pytest

import db
import streamlit as st
from pathlib import Path
from streamlit.testing.v1 import AppTest

APP = Path(__file__).parent / "app.py"


@pytest.fixture
def app(tmp_path, monkeypatch):
    """Run the app against a fresh temporary database (patched db.connect)."""
    db_path = tmp_path / "app.db"
    orig = db.connect
    opened = []

    def patched(*a, **k):
        c = orig(db_path)
        opened.append(c)
        return c

    monkeypatch.setattr(db, "connect", patched)
    st.cache_resource.clear()
    st.cache_data.clear()
    at = AppTest.from_file(str(APP), default_timeout=180)
    at.session_state["view"] = "demo"
    at.session_state["user"] = "tester"        # signed in (sign-in itself is tested in test_homepage.py)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    try:
        yield at, opened[0]
    finally:
        at.session_state["view"] = "demo"
        st.cache_resource.clear()
        st.cache_data.clear()
        for c in opened:
            c.close()


def usage_since(conn, days):
    cutoff = (db.today(conn) - timedelta(days=days)).isoformat()
    with conn:
        conn.execute("DELETE FROM usage WHERE date < ?", (cutoff,))


def metric_value(at, label):
    match = [m.value for m in at.metric if m.label == label]
    return int(match[0]) if match else None


def vital_at_risk(at):
    return metric_value(at, "Vital items at risk")


def test_app_sample_data_shows_risk_and_requests(app):
    at, conn = app
    assert len(at.exception) == 0
    assert vital_at_risk(at) >= 1
    infos = " | ".join(i.value for i in at.info)
    assert "No ward requests have been logged yet" in infos     # measured fill rate is real, not synthetic
    reports = " | ".join(m.value for m in at.metric if m.label == "Overall measured fill rate") == ""
    assert reports
    # the dashboard reorder table carries the availability column
    dash_df = at.tabs[0].dataframe[0].value
    assert "availability_risk" in dash_df.columns


def test_app_with_no_usage_history_still_renders(app):
    at, conn = app
    usage_since(conn, 0)
    at.run()
    assert len(at.exception) == 0
    assert vital_at_risk(at) is not None                        # stock / purchasing still accessible
    f_infos = " | ".join(i.value for i in at.tabs[5].info)
    assert "Not enough usage history" in f_infos


def test_app_with_short_history_renders_and_falls_back(app):
    at, conn = app
    usage_since(conn, 59)                                       # ~2 months: no Winters, few methods
    at.run()
    assert len(at.exception) == 0
    assert vital_at_risk(at) is not None
    at.tabs[5]                                                   # forecast tab renders too


def test_app_with_six_months_history_renders(app):
    at, conn = app
    usage_since(conn, 183)                                      # ~6 months: Winters still not eligible
    at.run()
    assert len(at.exception) == 0
    assert vital_at_risk(at) is not None


def test_app_zero_usage_item_does_not_crash_forecast(app):
    at, conn = app
    with conn:
        conn.execute("UPDATE usage SET qty_used = 0 WHERE item_id = 'MED005'")
    at.run()
    assert len(at.exception) == 0
    assert vital_at_risk(at) is not None


def test_app_future_po_does_not_hide_empty_vital_risk(app):
    """A vital item with ZERO usable stock stays flagged even with a future
    (or even today-dated) receipt planned: you cannot give patients stock that
    is not on the shelf yet."""
    at, conn = app
    T = db.today(conn)
    with conn:
        conn.execute("DELETE FROM lots WHERE item_id = 'MED007'")       # Insulin, vital
    po = db.create_po(conn, "MED007", 50, T)
    with conn:
        conn.execute("UPDATE purchase_orders SET expected_date = ? WHERE po_id = ?",
                     ((T + timedelta(days=10)).isoformat(), po))
    at.run()
    assert len(at.exception) == 0
    assert "Insulin regular 10mL vial" in " | ".join(e.value for e in at.error)
    # receipt planned for TODAY still does not erase the zero-usable risk
    with conn:
        conn.execute("UPDATE purchase_orders SET expected_date = ? WHERE po_id = ?",
                     (T.isoformat(), po))
    at.run()
    assert "Insulin regular 10mL vial" in " | ".join(e.value for e in at.error)


def test_app_issue_shortage_writes_once_and_reports_honestly(app):
    """Issue to ward is a logged request: one click -> one demand_requests row,
    one stockout row, and the UI shows what was actually served vs. unfilled
    (no false 'all issued' success). A second click rotates the request id and
    writes a NEW request."""
    at, conn = app
    T = db.today(conn)
    with conn:
        conn.execute("DELETE FROM lots WHERE item_id = 'MED005'")       # nothing usable -> all short
    at.tabs[3].selectbox(key="issue_item").select("MED005")
    at.number_input(key="issue_qty").set_value(99999)
    at.run()
    next(b for b in at.tabs[3].button if b.label == "Issue stock").click()
    at.run()
    assert len(at.exception) == 0
    row = conn.execute("SELECT requested, filled, short FROM demand_requests").fetchone()
    assert tuple(row) == (99999, 0, 99999)                       # nothing usable -> all short
    assert conn.execute("SELECT COUNT(*) FROM stockouts").fetchone()[0] == 1
    assert conn.execute(
        "SELECT SUM(qty_used) FROM usage WHERE item_id = 'MED005' AND date = ?",
        (T.isoformat(),)).fetchone()[0] == 99999                 # true demand counts once
    errs = " | ".join(e.value for e in at.error)
    assert "Only **0 of 99,999" in errs and "not available" in errs
    toasts = " ".join(t.value for t in at.toast) if at.toast else ""
    assert "All 99999" not in toasts                              # no false success
    # re-running the app must not re-record the same request
    at.run()
    assert conn.execute("SELECT COUNT(*) FROM demand_requests").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM stockouts").fetchone()[0] == 1
    # a second submission is a new request with its own id -> a second row
    next(b for b in at.tabs[3].button if b.label == "Issue stock").click()
    at.run()
    assert conn.execute("SELECT COUNT(*) FROM demand_requests").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM stockouts").fetchone()[0] == 2


def test_dashboard_filters_and_sort_change_the_table(app):
    at, _ = app
    table = lambda: at.tabs[0].dataframe[0].value
    total = len(table())
    at.multiselect(key="dash_ved").set_value(["V"]).run()
    assert len(table()) < total and set(table()["ved"]) == {"V"}
    at.multiselect(key="dash_ved").set_value([]).run()
    at.multiselect(key="dash_status").set_value(["🟢 OK"]).run()
    assert set(table()["status"]) <= {"🟢 OK"}                    # strict: no red/yellow rows sneak in
    at.multiselect(key="dash_status").set_value([]).run()
    at.selectbox(key="dash_sort").set_value("Criticality (Vital first)").run()
    order = table()["ved"].map({"V": 0, "E": 1, "D": 2}).tolist()
    assert order == sorted(order)
    at.selectbox(key="dash_sort").set_value("Order value (highest first)").run()
    vals = table()["order_value"].tolist()
    assert vals == sorted(vals, reverse=True)


def test_dashboard_reorder_status_is_first_column_and_ok_can_go_on_top(app):
    at, _ = app
    table = lambda: at.tabs[0].dataframe[0].value
    assert list(table().columns[:2]) == ["status", "availability_risk"]
    ranks = table()["status"].map({"🔴 Order now": 0, "🟡 Order soon": 1, "🟢 OK": 2}).tolist()
    assert ranks == sorted(ranks)                                 # default: 🔴 first
    at.selectbox(key="dash_sort").set_value("Reorder status (green first)").run()
    ranks = table()["status"].map({"🔴 Order now": 0, "🟡 Order soon": 1, "🟢 OK": 2}).tolist()
    assert ranks == sorted(ranks, reverse=True)                   # 🟢 OK on top
    assert "🟢 OK" not in set(table()["availability_risk"])       # the two OKs no longer look alike


def test_approving_a_draft_moves_on_to_the_next_vendors_draft(app):
    import planning
    import purchasing as pu
    at, conn = app
    items, usage, deliveries, open_pos, _ = db.load_frames(conn)
    made = pu.draft_suggested_orders(conn, planning.build_plan(items, usage, deliveries, open_pos=open_pos))
    assert len(made) >= 2
    at.run()
    first = at.selectbox(key="po_pick").value
    assert first in made                                          # a draft opens first, not an old order
    at.button(key=f"send_{first}").click().run()
    assert not at.exception
    second = at.selectbox(key="po_pick").value
    assert second in made and second != first                     # moved on to the next vendor
    assert pu.order_header(conn, first)["status"] == "SENT"
    assert pu.order_header(conn, first)["supplier"] != pu.order_header(conn, second)["supplier"]
