"""
App-level regression tests: drive the REAL Streamlit UI (AppTest) against a
temporary database, so your saved data is never touched.
"""

from datetime import timedelta

import pytest

import db
import ui
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


def open_page(at, title):
    """Click a sidebar menu item and return the main area (only the open page is drawn)."""
    at.button(key=ui.nav_key(title)).click().run()
    assert at.session_state["page"] == title
    return at.main


def reorder_table(at):
    """The full item table on the Inventory page (all underlying columns, statuses as plain text)."""
    return next(d.value for d in at.main.dataframe if "primary" in d.value.columns)


def urgent_table(at):
    """The dashboard's 'Urgent inventory actions' table, or None when nothing is urgent."""
    return next((d.value for d in at.main.dataframe if "Days left" in d.value.columns), None)


def vital_table_items(at):
    """Item names (without the ' (Vital)' tag) in the dashboard's urgent-actions table."""
    t = urgent_table(at)
    return set() if t is None else {name.removesuffix(" (Vital)") for name in t["Item"]}


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
    open_page(at, "KPIs")                                         # measured fill rate lives on Reports
    infos = " | ".join(i.value for i in at.info)
    assert "No ward requests have been logged yet" in infos     # measured fill rate is real, not synthetic
    assert not [m for m in at.metric if m.label == "Overall measured fill rate"]
    open_page(at, "Inventory")                                    # the item table carries availability
    assert "availability_risk" in reorder_table(at).columns


def test_app_with_no_usage_history_still_renders(app):
    at, conn = app
    usage_since(conn, 0)
    at.run()
    assert len(at.exception) == 0
    assert vital_at_risk(at) is not None                        # stock / purchasing still accessible
    f_infos = " | ".join(i.value for i in open_page(at, "Forecast").info)
    assert "Not enough usage history" in f_infos


def test_app_with_short_history_renders_and_falls_back(app):
    at, conn = app
    usage_since(conn, 59)                                       # ~2 months: no Winters, few methods
    at.run()
    assert len(at.exception) == 0
    assert vital_at_risk(at) is not None
    open_page(at, "Forecast")                                    # forecast page renders too
    assert len(at.exception) == 0


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
    assert "Insulin regular 10mL vial" in vital_table_items(at)
    # receipt planned for TODAY still does not erase the zero-usable risk
    with conn:
        conn.execute("UPDATE purchase_orders SET expected_date = ? WHERE po_id = ?",
                     (T.isoformat(), po))
    at.run()
    assert "Insulin regular 10mL vial" in vital_table_items(at)


def test_app_issue_shortage_writes_once_and_reports_honestly(app):
    """Issue to ward is a logged request: one click -> one demand_requests row,
    one stockout row, and the UI shows what was actually served vs. unfilled
    (no false 'all issued' success). A second click rotates the request id and
    writes a NEW request."""
    at, conn = app
    T = db.today(conn)
    with conn:
        conn.execute("DELETE FROM lots WHERE item_id = 'MED005'")       # nothing usable -> all short
    open_page(at, "Stock movements").selectbox(key="issue_item").select("MED005")
    at.number_input(key="issue_qty").set_value(99999)
    at.run()
    at.button(key="issue_submit").click().run()
    assert len(at.exception) == 0
    # more than the usable stock: a confirmation opens first and nothing is written yet
    assert at.session_state["pending_action"]["kind"] == "issue"
    assert conn.execute("SELECT COUNT(*) FROM demand_requests").fetchone()[0] == 0
    at.button(key="confirm_yes").click().run()
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
    at.button(key="issue_submit").click().run()
    at.button(key="confirm_yes").click().run()
    assert conn.execute("SELECT COUNT(*) FROM demand_requests").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM stockouts").fetchone()[0] == 2


def test_dashboard_filters_and_sort_change_the_table(app):
    at, _ = app
    open_page(at, "Inventory")
    at.selectbox(key="inv_page_size").set_value("All").run()
    table = lambda: reorder_table(at)
    total = len(table())
    assert total == 150
    at.multiselect(key="dash_ved").set_value(["V"]).run()
    assert len(table()) < total and set(table()["ved"]) == {"Vital"}
    at.multiselect(key="dash_ved").set_value([]).run()
    at.multiselect(key="dash_status").set_value(["🟢 OK"]).run()
    assert set(table()["status"]) <= {"OK"}                       # strict: no red/yellow rows sneak in
    at.multiselect(key="dash_status").set_value([]).run()
    at.selectbox(key="dash_sort").set_value("Criticality (Vital first)").run()
    order = table()["ved"].map({"Vital": 0, "Essential": 1, "Desirable": 2}).tolist()
    assert order == sorted(order)
    at.selectbox(key="dash_sort").set_value("Order value (highest first)").run()
    vals = table()["order_value"].tolist()
    assert vals == sorted(vals, reverse=True)


def test_dashboard_reorder_status_is_first_column_and_ok_can_go_on_top(app):
    at, _ = app
    open_page(at, "Inventory")
    table = lambda: reorder_table(at)
    assert list(table().columns[:3]) == ["name", "item_id", "primary"]   # item first, then one status
    ranks = table()["status"].map({"Order now": 0, "Order soon": 1, "OK": 2}).tolist()
    assert ranks == sorted(ranks)                                 # default: Order now first
    at.selectbox(key="dash_sort").set_value("Reorder status (green first)").run()
    ranks = table()["status"].map({"Order now": 0, "Order soon": 1, "OK": 2}).tolist()
    assert ranks == sorted(ranks, reverse=True)                   # OK on top
    assert "OK" not in set(table()["availability_risk"])          # the two OKs no longer look alike
    assert not any(str(v)[:1] in "🔴🟡🟢" for v in table()["primary"])   # text labels, no emoji


def test_approving_a_draft_moves_on_to_the_next_vendors_draft(app):
    import planning
    import purchasing as pu
    at, conn = app
    items, usage, deliveries, open_pos, _ = db.load_frames(conn)
    made = pu.draft_suggested_orders(conn, planning.build_plan(items, usage, deliveries, open_pos=open_pos))
    assert len(made) >= 2
    open_page(at, "Purchasing")
    first = at.selectbox(key="po_pick").value
    assert first in made                                          # a draft opens first, not an old order
    at.button(key=f"send_{first}").click().run()
    assert pu.order_header(conn, first)["status"] == "DRAFT"     # review step: nothing sent yet
    at.button(key="confirm_yes").click().run()
    assert not at.exception
    second = at.selectbox(key="po_pick").value
    assert second in made and second != first                     # moved on to the next vendor
    assert pu.order_header(conn, first)["status"] == "SENT"
    assert pu.order_header(conn, first)["supplier"] != pu.order_header(conn, second)["supplier"]


def test_every_sidebar_page_opens_without_errors(app):
    """Only the open page is drawn, so a page must not rely on names set up by another page."""
    at, _ = app
    for title, _, _ in ui.PAGES:
        open_page(at, title)
        assert not at.exception, (title, [e.value for e in at.exception])


def test_preparing_drafts_on_the_dashboard_opens_purchasing_on_the_first_draft(app):
    at, conn = app
    with conn:                                                   # make sure something needs ordering
        conn.execute("DELETE FROM lots WHERE item_id = 'MED005'")
    at.run()
    at.button(key="prepare_drafts").click().run()
    assert not at.exception
    assert at.session_state["page"] == "Purchasing"
    drafts = [r[0] for r in conn.execute("SELECT order_no FROM po_headers WHERE status = 'DRAFT' ORDER BY order_no")]
    assert drafts and at.selectbox(key="po_pick").value == drafts[0]


def test_ask_medstock_without_an_api_key_explains_how_to_set_it_up(app, monkeypatch):
    import assistant
    at, _ = app
    monkeypatch.setattr(assistant, "get_api_key", lambda *a, **k: None)   # the secrets file may hold a real key
    main = open_page(at, "Ask MedStock")
    assert not at.exception
    info = " ".join(i.value for i in main.info)
    assert "GEMINI_API_KEY" in info and "Everything else in MedStock works" in info
    captions = " ".join(c.value for c in main.caption)
    assert "fictional demo data" in captions and "improve its products" in captions      # privacy note
    assert all(b.disabled for b in main.button if b.key and b.key.startswith("ai_example_"))


def test_every_page_works_without_any_ai_key(app, monkeypatch):
    import assistant
    at, _ = app
    monkeypatch.setattr(assistant, "get_api_key", lambda *a, **k: None)
    for title, _, _ in ui.PAGES:
        open_page(at, title)
        assert not at.exception, (title, [e.value for e in at.exception])


def test_ask_medstock_answers_an_example_question_with_a_fake_gemini(app, monkeypatch):
    from types import SimpleNamespace as NS
    from google.genai import types as gt
    import assistant
    at, conn = app
    usage = NS(prompt_token_count=900, candidates_token_count=60, thoughts_token_count=0, cached_content_token_count=0,
               tool_use_prompt_token_count=0)
    replies = [
        NS(candidates=[NS(content=gt.Content(role="model", parts=[gt.Part(function_call=gt.FunctionCall(
            id="c1", name="get_supply_risks", args={}))]), finish_reason=NS(name="STOP"))],
           usage_metadata=usage, prompt_feedback=None),
        NS(candidates=[NS(content=gt.Content(role="model", parts=[gt.Part(text="No vendors are disrupted right now.")]),
                          finish_reason=NS(name="STOP"))], usage_metadata=usage, prompt_feedback=None),
    ]
    fake = NS(models=NS(generate_content=lambda **kw: replies.pop(0)))
    monkeypatch.setattr(assistant, "get_api_key", lambda *a, **k: "test-key-not-real")
    monkeypatch.setattr(assistant, "make_provider", lambda cfg, key: assistant.GeminiProvider(fake, cfg["model"]))
    open_page(at, "Ask MedStock")
    at.button(key="ai_example_3").click().run()
    assert not at.exception, [e.value for e in at.exception]
    shown = " ".join(m.value for m in at.main.markdown)
    assert "No vendors are disrupted right now." in shown
    caption = " ".join(c.value for c in at.main.caption)
    assert "at paid rates" in caption and "billing not verified" in caption       # an estimate, labelled as one
    row = conn.execute("SELECT provider, model, status, cost_usd FROM ai_runs").fetchone()
    assert tuple(row)[:3] == ("gemini", "gemini-3.5-flash-lite", "ok")
    assert row["cost_usd"] == pytest.approx((1800 * 0.30 + 120 * 2.50) / 1e6, abs=1e-6)


def test_urgent_actions_table_is_short_sorted_and_labelled(app):
    """The dashboard shows only the most urgent items (at most 8), worst first, with text labels."""
    at, _ = app
    t = urgent_table(at)
    if t is None:                                                # nothing urgent in this sample
        return
    assert list(t.columns) == ["Item", "Risk", "Days left", "On order", "Suggested order", "Vendor"]
    assert 1 <= len(t) <= 8
    order = {"No usable stock": 0, "Shortage risk": 1, "Shortage watch": 2, "Order now": 3}
    ranks = t["Risk"].map(order).tolist()
    assert None not in ranks and ranks == sorted(ranks)          # worst first, plain-text labels (no emoji)
    assert not any(ch in "".join(t["Risk"]) for ch in "🔴🟡🟢")
    assert at.button(key="view_all_items")                         # "View all items" goes to Inventory
    at.button(key="view_all_items").click().run()
    assert at.session_state["page"] == "Inventory"


def test_dashboard_has_no_full_item_table_and_kpis_line_up(app):
    at, _ = app
    assert all("order_value" not in d.value.columns for d in at.main.dataframe)
    labels = [m.label for m in at.metric][:4]
    assert labels == ["Order now", "Vital items at risk", "Fill rate", "Inventory value"]
    assert all(m.delta for m in at.metric[:4])                    # every card has one line of context


def test_every_page_is_reachable_from_main_menu_or_more(app):
    at, _ = app
    keys = {b.key for b in at.sidebar.button}
    for title, _, _ in ui.PAGES:
        assert ui.nav_key(title) in keys, title
    assert set(ui.MAIN_PAGES) | set(ui.MORE_PAGES) == {t for t, _, _ in ui.PAGES}


def test_main_menu_order_puts_ask_medstock_after_reports(app):
    at, _ = app
    assert [ui.nav_label(t) for t in ui.MAIN_PAGES] == [
        "Dashboard", "Inventory", "Purchasing", "Forecast", "Alerts", "Reports", "Ask MedStock"]
    assert "Ask MedStock" not in ui.MORE_PAGES
    labels = [b.label for b in at.sidebar.button]
    assert labels.count("Ask MedStock") == 1                      # exactly once in the sidebar
    assert labels.index("Ask MedStock") == labels.index("Reports") + 1
    main_keys = [b.key for b in at.sidebar.button if b.key in {ui.nav_key(t) for t in ui.MAIN_PAGES}]
    assert main_keys == [ui.nav_key(t) for t in ui.MAIN_PAGES]   # drawn in that order
    at.sidebar.button(key=ui.nav_key("Ask MedStock")).click().run()
    assert not at.exception and at.session_state["page"] == "Ask MedStock"


# ---------------------------------------------------------------------------
# Help, page links and confirmations (audit Phase 0)
# ---------------------------------------------------------------------------
def test_help_opens_without_signing_out(app):
    at, _ = app
    main = open_page(at, "Help")
    assert not at.exception
    assert at.session_state["user"] == "tester" and at.session_state["view"] == "demo"
    assert any(h.value == "Help" for h in main.header)
    assert at.query_params["page"] == ["help"] or at.query_params["page"] == "help"
    open_page(at, "Dashboard")                                    # and back again, still signed in
    assert at.session_state["user"] == "tester"


def test_page_link_opens_that_page_after_sign_in(app):
    at, _ = app
    at.query_params["page"] = "expiry"
    at.run()
    assert at.session_state["page"] == "Expiry" and not at.exception


def test_page_link_in_a_new_session_asks_for_sign_in(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "connect", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no db before sign-in")))
    at = AppTest.from_file(str(APP), default_timeout=180)
    at.query_params["page"] = "help"
    at.run()
    assert not at.exception
    assert at.session_state["view"] == "login" and at.session_state["page"] == "Help"
    assert at.text_input(key="login_pass")                        # sign-in form, not the demo


def a_lot_on_the_shelf(conn):
    return conn.execute("SELECT lot_no FROM lots WHERE qty > 0 AND expiry_date > ? ORDER BY lot_id LIMIT 1",
                        (db.today(conn).isoformat(),)).fetchone()[0]


def test_recall_asks_first_cancel_changes_nothing_confirm_applies_once(app):
    at, conn = app
    open_page(at, "Recalls & disruptions")
    lot = a_lot_on_the_shelf(conn)
    at.selectbox(key="recall_lot").set_value(lot)
    at.button(key="recall_submit").click().run()
    assert at.session_state["pending_action"]["lot_no"] == lot
    assert conn.execute("SELECT COUNT(*) FROM recalls").fetchone()[0] == 0     # opening it changes nothing
    at.button(key="confirm_no").click().run()
    assert "pending_action" not in at.session_state
    assert conn.execute("SELECT COUNT(*) FROM recalls").fetchone()[0] == 0     # cancel changes nothing
    at.button(key="recall_submit").click().run()
    pending = dict(at.session_state["pending_action"])
    at.button(key="confirm_yes").click().run()
    assert not at.exception
    assert conn.execute("SELECT COUNT(*) FROM recalls").fetchone()[0] == 1
    assert any("Recall of lot" in s.value for s in at.success)
    # a rerun, or the same request arriving again, does not recall twice
    at.session_state["pending_action"] = pending
    at.run()
    at.button(key="confirm_yes").click().run()
    assert conn.execute("SELECT COUNT(*) FROM recalls").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM transactions WHERE type = 'RECALL'").fetchone()[0] >= 1


def test_random_recall_and_disruption_show_the_target_before_anything_changes(app):
    at, conn = app
    open_page(at, "Recalls & disruptions")
    at.button(key="recall_random").click().run()
    p = at.session_state["pending_action"]
    assert p["kind"] == "recall" and p["origin"] == "Simulated notice" and p["lot_no"]
    assert conn.execute("SELECT COUNT(*) FROM recalls").fetchone()[0] == 0
    at.button(key="confirm_no").click().run()
    at.button(key="outage_random").click().run()
    p = at.session_state["pending_action"]
    assert p["kind"] == "outage" and p["origin"] == "Simulated" and 7 <= p["days"] <= 28
    assert conn.execute("SELECT COUNT(*) FROM vendor_outages").fetchone()[0] == 0
    at.button(key="confirm_yes").click().run()
    assert not at.exception
    row = conn.execute("SELECT supplier, origin FROM vendor_outages").fetchall()
    assert [tuple(r) for r in row] == [(p["supplier"], "Simulated")]


def test_vendor_disruption_cancel_and_confirm(app):
    at, conn = app
    open_page(at, "Recalls & disruptions")
    at.button(key="outage_submit").click().run()
    assert conn.execute("SELECT COUNT(*) FROM vendor_outages").fetchone()[0] == 0
    at.button(key="confirm_no").click().run()
    assert conn.execute("SELECT COUNT(*) FROM vendor_outages").fetchone()[0] == 0
    at.button(key="outage_submit").click().run()
    at.button(key="confirm_yes").click().run()
    assert conn.execute("SELECT COUNT(*) FROM vendor_outages").fetchone()[0] == 1


def test_write_off_all_expired_asks_and_writes_off_exactly_once(app):
    at, conn = app
    T = db.today(conn)
    with conn:                                                    # make sure there is expired stock
        conn.execute("UPDATE lots SET expiry_date = ? WHERE lot_id IN (SELECT lot_id FROM lots WHERE qty > 0 "
                     "ORDER BY lot_id LIMIT 2)", ((T - timedelta(days=3)).isoformat(),))
    count_expired = lambda: conn.execute("SELECT COUNT(*) FROM lots WHERE qty > 0 AND expiry_date <= ?",
                                         (T.isoformat(),)).fetchone()[0]
    before = count_expired()
    assert before >= 2
    open_page(at, "Expiry")
    at.button(key="wo_all_expired").click().run()
    assert count_expired() == before
    at.button(key="confirm_no").click().run()
    assert count_expired() == before
    at.button(key="wo_all_expired").click().run()
    at.button(key="confirm_yes").click().run()
    assert not at.exception and count_expired() == 0
    writeoffs = conn.execute("SELECT COUNT(*) FROM transactions WHERE type = 'WRITE-OFF'").fetchone()[0]
    at.run()
    assert conn.execute("SELECT COUNT(*) FROM transactions WHERE type = 'WRITE-OFF'").fetchone()[0] == writeoffs


def test_bulk_write_off_is_blocked_when_the_expired_list_changed(app):
    at, conn = app
    T = db.today(conn)
    with conn:
        conn.execute("UPDATE lots SET expiry_date = ? WHERE lot_id = (SELECT MIN(lot_id) FROM lots WHERE qty > 0)",
                     ((T - timedelta(days=3)).isoformat(),))
    open_page(at, "Expiry")
    at.button(key="wo_all_expired").click().run()
    with conn:                                                    # another lot expires before Confirm
        conn.execute("UPDATE lots SET expiry_date = ? WHERE lot_id = (SELECT MAX(lot_id) FROM lots WHERE qty > 0)",
                     ((T - timedelta(days=1)).isoformat(),))
    at.run()
    assert at.button(key="confirm_yes").disabled
    assert any("changed" in e.value for e in at.error)


def test_single_write_off_needs_confirmation(app):
    at, conn = app
    open_page(at, "Stock movements")
    at.session_state["move_tab"] = "Write-off"
    at.run()
    total = lambda: conn.execute("SELECT SUM(qty) FROM lots").fetchone()[0]
    before = total()
    reason = next(s for s in at.selectbox if s.label == "Reason (required)")
    if reason.value is None:                                      # a reason is required before review
        assert at.button(key="wo_submit").disabled
        reason.set_value("Damaged").run()
    at.button(key="wo_submit").click().run()
    assert at.session_state["pending_action"]["kind"] == "write_off_lot"
    assert total() == before
    at.button(key="confirm_yes").click().run()
    assert not at.exception and total() == before - 1


# ---------------------------------------------------------------------------
# Inventory workbench
# ---------------------------------------------------------------------------
def test_inventory_search_finds_by_name_and_id(app):
    at, _ = app
    open_page(at, "Inventory")
    at.text_input(key="inv_search").input("insulin").run()
    names = set(reorder_table(at)["name"])
    assert names and all("insulin" in nm.lower() for nm in names)
    at.text_input(key="inv_search").input("med007").run()
    assert list(reorder_table(at)["item_id"]) == ["MED007"]
    at.button(key="inv_clear").click().run()                       # one click clears everything
    assert at.text_input(key="inv_search").value == ""
    assert at.session_state["inv_quick"] == "All"


def test_inventory_quick_views_match_their_counts(app):
    at, _ = app
    open_page(at, "Inventory")
    at.selectbox(key="inv_page_size").set_value("All").run()
    for view, check in [("Order now", lambda t: set(t["status"]) == {"Order now"}),
                        ("Shortage risk", lambda t: set(t["availability_risk"]) <= {"No usable stock", "Shortage risk"}),
                        ("Incoming", lambda t: (t["on_order"] > 0).all())]:
        at.segmented_control(key="inv_quick").set_value(view).run()
        t = reorder_table(at) if any("primary" in d.value.columns for d in at.main.dataframe) else None
        if t is not None:
            assert check(t), view
            label = at.segmented_control(key="inv_quick").format_func(view)
            assert label == f"{view} ({len(t)})"                   # the count on the button is the row count


def test_inventory_csv_has_full_precision_values(app, monkeypatch):
    at, _ = app
    sent = {}
    real = st.download_button

    def spy(label, data=None, *a, **k):
        if k.get("key") == "inv_csv":
            sent["csv"] = data
        return real(label, data, *a, **k)

    monkeypatch.setattr(st, "download_button", spy)
    open_page(at, "Inventory")
    import io
    import pandas as pd
    csv = pd.read_csv(io.StringIO(sent["csv"]))
    assert len(csv) == 150
    assert {"rop", "safety_stock", "days_of_supply", "order_value", "status", "availability_risk"} <= set(csv.columns)
    assert not csv["status"].astype(str).str[0].isin(list("🔴🟡🟢")).any()          # plain labels
    assert (csv["rop"] % 1 != 0).any()                                            # not rounded for display


def test_inventory_row_actions_open_the_item_elsewhere(app):
    at, _ = app
    open_page(at, "Inventory")
    first = reorder_table(at).iloc[0]["item_id"]
    at.session_state["detail_item"] = first
    at.session_state["page"] = "Item detail"
    at.run()
    assert not at.exception and at.session_state["page"] == "Item detail"


def test_cycle_count_reports_expected_and_counted_after_saving(app):
    at, conn = app
    open_page(at, "Stock movements")
    at.session_state["move_tab"] = "Cycle count"
    at.run()
    lot_box = next(s for s in at.selectbox if s.label == "Lot")
    lot_id = lot_box.value
    system = conn.execute("SELECT qty FROM lots WHERE lot_id = ?", (lot_id,)).fetchone()[0]
    next(n for n in at.number_input if n.label.startswith("Counted quantity")).set_value(system + 2).run()
    at.button(key="cc_submit").click().run()
    assert not at.exception
    msg = " ".join(w.value for w in at.warning)
    assert f"counted {system + 2:,}" in msg and f"expected {system:,}" in msg and "+2" in msg


def test_item_detail_every_tab_renders_and_formulas_are_kept(app):
    at, _ = app
    at.session_state["detail_item"] = "MED007"
    open_page(at, "Item detail")
    for tab in ["Summary", "Stock", "Availability", "Ordering", "Expiry", "History", "Calculations"]:
        at.session_state["detail_tab"] = tab
        at.run()
        assert not at.exception, (tab, [e.value for e in at.exception])
    text = " ".join(m.value for m in at.markdown)
    assert "EOQ = √(2DS/H)" in text and "ROP = DDLT + SS" in text      # course formulas still shown
    assert not any(h.value.endswith(("🔴 Order now", "🟢 OK")) for h in at.header)   # no emoji-only status


def test_history_filters_and_view_history_for_an_item_without_movements(app):
    at, conn = app
    main = open_page(at, "History")
    assert not at.exception
    assert any(b.label == "Record stock movement" for b in main.button) or main.dataframe   # empty state or table
    at.session_state["hist_items"] = ["MED007"]                  # as set by "View history" on another page
    at.run()
    assert not at.exception


def test_calculators_validate_inputs_and_reset_to_the_example(app):
    at, _ = app
    open_page(at, "Calculators")
    assert any(m.label == "EOQ" and m.value == "100.0 units" for m in at.metric)     # slide 188: EOQ = 100
    at.number_input(key="c_D").set_value(0.0).run()
    assert any("Annual demand D must be more than 0" in e.value for e in at.error)
    assert not any(m.label == "EOQ" for m in at.metric)                          # no silent substitute
    at.button(key="reset_EOQ").click().run()
    assert at.number_input(key="c_D").value == 1000.0 and not at.error
    at.session_state["calc_tab"] = "Newsvendor (single period)"
    at.run()
    assert any(m.label == "Order quantity Q" and m.value == "83.6 units" for m in at.metric)


def test_purchasing_opens_when_a_drafts_need_by_date_has_passed(app):
    """A draft left unapproved while the clock moves on must not crash Purchasing."""
    import planning
    import purchasing as pu
    at, conn = app
    items, usage, deliveries, open_pos, _ = db.load_frames(conn)
    made = pu.draft_suggested_orders(conn, planning.build_plan(items, usage, deliveries, open_pos=open_pos))
    with conn:
        conn.execute("UPDATE po_headers SET need_by = ? WHERE order_no = ?",
                     ((db.today(conn) - timedelta(days=10)).isoformat(), made[0]))
    at.session_state["open_order"] = made[0]
    open_page(at, "Purchasing")
    assert not at.exception, [e.value for e in at.exception]


# ---------------------------------------------------------------------------
# Notification bell, ending a disruption and refusing a line at the dock
# ---------------------------------------------------------------------------
def test_bell_shows_the_alert_count_and_opens_alerts(app):
    import events
    at, conn = app
    bell = at.button(key="bell_btn")
    T = db.today(conn)
    expiring_items = conn.execute("SELECT COUNT(DISTINCT item_id) FROM lots WHERE qty > 0 AND expiry_date <= ?",
                                  ((T + timedelta(days=30)).isoformat(),)).fetchone()[0]
    assert bell.label == ui.alerts_label(expiring_items)          # no recalls or disruptions yet
    events.start_outage(conn, "Pacific Pharma Supply", 10, "test")
    at.run()
    assert at.button(key="bell_btn").label == ui.alerts_label(expiring_items + 1)
    at.button(key="bell_btn").click().run()
    assert not at.exception and at.session_state["page"] == "Recalls & disruptions"


def outage_count(conn):
    return conn.execute("SELECT end_date FROM vendor_outages").fetchall()


def test_ending_a_disruption_asks_first_and_applies_once(app):
    import events
    at, conn = app
    events.start_outage(conn, "Pacific Pharma Supply", 10, "test")
    open_page(at, "Recalls & disruptions")
    oid = conn.execute("SELECT outage_id FROM vendor_outages").fetchone()[0]
    before = [tuple(r) for r in outage_count(conn)]
    at.button(key=f"end_outage_{oid}").click().run()
    assert at.session_state["pending_action"]["kind"] == "end_outage"
    assert [tuple(r) for r in outage_count(conn)] == before                 # opening changes nothing
    at.button(key="confirm_no").click().run()
    assert [tuple(r) for r in outage_count(conn)] == before                 # cancel changes nothing
    at.button(key=f"end_outage_{oid}").click().run()
    pending = dict(at.session_state["pending_action"])
    at.button(key="confirm_yes").click().run()
    assert not at.exception
    after = [tuple(r) for r in outage_count(conn)]
    assert after != before and after[0][0] == (db.today(conn) - timedelta(days=1)).isoformat()
    at.session_state["pending_action"] = pending                            # the same request again
    at.run()
    assert at.button(key="confirm_yes").disabled                            # vendor is no longer disrupted
    assert [tuple(r) for r in outage_count(conn)] == after                  # not applied twice
    assert not at.exception


def test_dismissing_a_dialog_clears_the_request_without_changes(app):
    """AppTest cannot press Escape or the dialog's X. Both call the dialog's on_dismiss callback
    (cancel_pending), which only removes the pending request. This test reproduces that effect; the
    browser check in the build notes covers the real key press."""
    import events
    at, conn = app
    events.start_outage(conn, "Pacific Pharma Supply", 10, "test")
    open_page(at, "Recalls & disruptions")
    oid = conn.execute("SELECT outage_id FROM vendor_outages").fetchone()[0]
    before = [tuple(r) for r in outage_count(conn)]
    at.button(key=f"end_outage_{oid}").click().run()
    del at.session_state["pending_action"]                                  # what cancel_pending does
    at.run()
    assert not at.exception and "confirm_yes" not in [b.key for b in at.button]
    assert [tuple(r) for r in outage_count(conn)] == before


def test_refusing_a_line_at_the_dock_asks_first_and_applies_once(app):
    at, conn = app
    po = db.create_po(conn, "MED005", 40, db.today(conn))
    status = lambda: conn.execute("SELECT status FROM purchase_orders WHERE po_id = ?", (po,)).fetchone()[0]
    open_page(at, "Stock movements")                                        # the app adopts it into a vendor order
    with conn:                                                              # ... which has now arrived at the dock
        conn.execute("UPDATE po_headers SET arrive_date = ? WHERE order_no = (SELECT order_no FROM purchase_orders "
                     "WHERE po_id = ?)", (db.today(conn).isoformat(), po))
    at.session_state["move_tab"] = "Receive delivery"
    at.run()
    line = next(s for s in at.selectbox if s.label == "Delivery line")
    line.set_value(po).run()
    at.button(key="refuse_line").click().run()
    p = at.session_state["pending_action"]
    assert p["kind"] == "refuse_line" and p["po_id"] == po and p["qty"] == 40
    assert status() == "OPEN"                                               # opening changes nothing
    at.button(key="confirm_no").click().run()
    assert status() == "OPEN"                                               # cancel changes nothing
    at.button(key="refuse_line").click().run()
    pending = dict(at.session_state["pending_action"])
    at.button(key="confirm_yes").click().run()
    assert not at.exception and status() == "CANCELLED"
    n_ledger = conn.execute("SELECT COUNT(*) FROM transactions WHERE type = 'PO CANCELLED'").fetchone()[0]
    assert n_ledger == 1
    at.session_state["pending_action"] = pending                            # the same request again
    at.run()
    assert at.button(key="confirm_yes").disabled                            # line no longer open
    assert conn.execute("SELECT COUNT(*) FROM transactions WHERE type = 'PO CANCELLED'").fetchone()[0] == 1


def sidebar_badges(at):
    """Every count badge drawn in the app's CSS: (container key, text) for each '::after{content:...}'."""
    import re
    css = " ".join(e.proto.body for e in at.get("html"))
    return re.findall(r'\.st-key-([\w-]+) button::after\{content:"([^"]+)"', css)


def test_the_bell_is_the_only_notification_badge(app):
    import events
    at, conn = app
    with conn:                                                    # no expiring stock, so nothing is active
        conn.execute("UPDATE lots SET expiry_date = '2099-01-01'")
    at.run()
    assert sidebar_badges(at) == []                               # zero alerts: no red badge anywhere
    events.start_outage(conn, "Pacific Pharma Supply", 10, "test")
    lot = conn.execute("SELECT lot_no FROM lots WHERE qty > 0 ORDER BY lot_id LIMIT 1").fetchone()[0]
    events.recall_lot(conn, lot, "II", "test")
    at.run()
    assert sidebar_badges(at) == [("bell_btn", "2")]              # one badge, on the bell, nothing on Alerts
    assert at.button(key="bell_btn").label == "Open alerts, 2 active"


# ---------------------------------------------------------------------------
# Ask MedStock: shortcuts and wording
# ---------------------------------------------------------------------------
def test_dashboard_has_one_compact_ask_medstock_shortcut(app):
    at, _ = app
    asks = [b for b in at.main.button if b.key == "dash_ask"]
    assert len(asks) == 1 and asks[0].label == "Open Ask MedStock"
    assert not at.main.chat_input                                   # no second copy of the assistant
    css = " ".join(e.proto.body for e in at.get("html"))
    assert "Ask a question about today" in css
    at.button(key="dash_ask").click().run()
    assert not at.exception and at.session_state["page"] == "Ask MedStock"


def test_help_explains_what_ask_medstock_can_and_cannot_do(app):
    at, _ = app
    open_page(at, "Help")
    text = " ".join(m.value for m in at.main.markdown)
    assert "read-only" in text and "cannot place or approve orders" in text
    for label in ["Item search", "Reorder plan", "Item detail", "KPIs", "Supply risks", "Purchase orders", "Lot trace"]:
        assert f"| {label} |" in text
    assert "Coming later" in text and "autonomous" not in text.lower()
    at.button(key="help_go_ask").click().run()
    assert at.session_state["page"] == "Ask MedStock"


def test_ask_medstock_page_leads_with_value_and_keeps_safeguards(app, monkeypatch):
    import assistant
    at, _ = app
    monkeypatch.setattr(assistant, "get_api_key", lambda *a, **k: "test-key-not-real")   # never used: no question asked
    main = open_page(at, "Ask MedStock")
    assert not at.exception
    assert main.caption[0].value.startswith("Ask about stock risks")                     # value first
    captions = " ".join(c.value for c in main.caption)
    assert "cannot place orders" in captions and "several lookups" in captions
    assert "gemini-3.5-flash-lite" in captions and "fictional demo data" in captions      # model and privacy kept
    assert "autonomous" not in captions.lower()
    assert len([b for b in main.button if (b.key or "").startswith("ai_example_")]) == len(assistant.EXAMPLE_QUESTIONS)
