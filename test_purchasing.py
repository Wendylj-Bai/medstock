"""
Tests for vendor purchase orders (purchasing.py) and the simulation clock (simulation.py).
Each test uses a fresh temporary database, so your real data is never touched.
"""

import hashlib
from datetime import date, timedelta

import pytest

import db
import events
import planning
import purchasing as pu
import simulation as sim


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    yield c
    c.close()


def plan_for(conn):
    items, usage, deliveries, open_pos, _ = db.load_frames(conn)
    return planning.build_plan(items, usage, deliveries, open_pos=open_pos)


def on_order(conn, item_id):
    _, open_pos = db.load_stock(conn)
    return int(open_pos.loc[open_pos["item_id"] == item_id, "qty"].sum())


def test_suggested_drafts_are_one_po_per_vendor_and_not_on_order_yet(conn):
    plan = plan_for(conn)
    red = plan[plan["status"].str.startswith("🔴")]
    made = pu.draft_suggested_orders(conn, plan)
    assert len(made) == red["supplier"].nunique()                  # consolidated by vendor
    for order_no in made:
        h = pu.order_header(conn, order_no)
        lines = pu.order_lines(conn, order_no)
        assert set(lines["item_id"]) == set(red.loc[red["supplier"] == h["supplier"], "item_id"])
        # quantities and prices pre-filled from the plan and the item master
        for line in lines.itertuples():
            r = red.set_index("item_id").loc[line.item_id]
            assert line.qty == r["order_qty"] and line.unit_cost == r["unit_cost"]
    # A draft is not an order: nothing is on order yet, and the items stay red
    assert on_order(conn, red["item_id"].iloc[0]) == 0
    # ... but they are not drafted twice
    assert pu.draft_suggested_orders(conn, plan_for(conn)) == []


def test_lines_must_belong_to_the_vendor(conn):
    with pytest.raises(db.StockError):
        pu.create_order(conn, "Cascade Surgical Supply", [("MED005", 10)])     # neither its vendor nor its backup
    with pytest.raises(db.StockError):
        pu.create_order(conn, "Overseas Medical Imports", [("MED005", 0)])     # no quantity


def test_order_lifecycle_follows_the_clock(conn):
    start = db.today(conn)
    order_no = pu.create_order(conn, "Overseas Medical Imports", [("CON004", 100), ("CON006", 20)])
    assert pu.stage(pu.order_header(conn, order_no), start) == "DRAFT"
    pu.send_order(conn, order_no)
    h = pu.order_header(conn, order_no)
    assert on_order(conn, "CON004") > 0                             # sent = on order
    with pytest.raises(db.StockError):
        pu.send_order(conn, order_no)                               # cannot send twice
    ack, ship, arrive = (date.fromisoformat(h[k]) for k in ("ack_date", "ship_date", "arrive_date"))
    assert start <= ack <= ship <= arrive
    assert pu.stage(h, start) == ("SENT" if ack > start else "CONFIRMED")
    assert pu.stage(h, ship) == ("SHIPPED" if arrive > ship else "ARRIVED")
    assert pu.stage(h, arrive) == "ARRIVED"

    if arrive > start:                                              # cannot receive before it arrives
        with pytest.raises(db.StockError):
            pu.receive_order(conn, order_no)
    db.set_today(conn, arrive)
    got = pu.receive_order(conn, order_no)
    assert len(got) == 2 and all(lt == (arrive - start).days for *_, lt in got)
    h = pu.order_header(conn, order_no)
    assert h["status"] == "RECEIVED" and on_order(conn, "CON004") == 0
    # the ASN lots are now on the shelf, and the real lead time feeds σL
    lines = pu.order_lines(conn, order_no)
    for line in lines.itertuples():
        lot = conn.execute("SELECT qty, expiry_date FROM lots WHERE lot_no = ?", (line.asn_lot_no,)).fetchone()
        assert lot["qty"] == line.confirmed_qty and lot["expiry_date"] == line.asn_expiry


def test_vendor_story_is_fixed_once_sent(conn):
    """Reloading the page must not change when an order arrives."""
    order_no = pu.create_order(conn, "Overseas Medical Imports", [("CON004", 50)])
    pu.send_order(conn, order_no)
    first = pu.order_header(conn, order_no)["arrive_date"]
    assert pu._rng(order_no).normal() == pu._rng(order_no).normal()
    assert pu.order_header(conn, order_no)["arrive_date"] == first


def test_vendor_backorder_reduces_on_order_after_acknowledgement(conn):
    order_no = pu.create_order(conn, "Overseas Medical Imports", [("MED005", 100)])
    pu.send_order(conn, order_no)
    with conn:                                                      # force a vendor backorder
        conn.execute("UPDATE purchase_orders SET confirmed_qty = 60 WHERE order_no = ?", (order_no,))
        conn.execute("UPDATE po_headers SET ack_date = ? WHERE order_no = ?",
                     ((db.today(conn) + timedelta(days=1)).isoformat(), order_no))
    assert on_order(conn, "MED005") == 100                          # not acknowledged yet: what we asked for
    db.set_today(conn, db.today(conn) + timedelta(days=1))
    assert on_order(conn, "MED005") == 60                           # acknowledged: what the vendor confirmed
    msgs = " ".join(m for _, m in pu.vendor_messages(conn, order_no, db.today(conn)))
    assert "only 60 of 100" in msgs


def test_cancel_rules(conn):
    a = pu.create_order(conn, "Northwest Medical Distributors", [("CON001", 10)])
    pu.cancel_order(conn, a)                                        # a draft can always be deleted
    assert pu.order_header(conn, a)["status"] == "CANCELLED"
    b = pu.create_order(conn, "Overseas Medical Imports", [("CON004", 10)])
    pu.send_order(conn, b)
    db.set_today(conn, date.fromisoformat(pu.order_header(conn, b)["ship_date"]))
    with pytest.raises(db.StockError):                              # too late once shipped
        pu.cancel_order(conn, b)


def test_clock_blocks_future_dates_and_reset_restores_sample_data(conn):
    real = db.today(conn)
    db.set_today(conn, real + timedelta(days=10))
    assert db.today(conn) == real + timedelta(days=10)
    with pytest.raises(db.StockError):
        db.issue(conn, "CON004", 1, db.WARDS[0], real + timedelta(days=11))
    db.reset(conn)
    assert db.today(conn) == date.today()
    assert conn.execute("SELECT COUNT(*) FROM po_headers").fetchone()[0] == 0


def test_simulation_consumes_stock_and_keeps_history_continuous(conn):
    start = db.today(conn)
    before = conn.execute("SELECT SUM(qty) FROM lots").fetchone()[0]
    rep = sim.advance(conn, 3, seed=1)
    assert db.today(conn) == start + timedelta(days=3)
    assert rep["demand"] > 0 and rep["issued"] <= rep["demand"]
    after = conn.execute("SELECT SUM(qty) FROM lots").fetchone()[0]
    assert before - after == rep["issued"]
    # every requested unit (filled or not) is in the demand history, day by day
    used = conn.execute("SELECT SUM(qty_used) FROM usage WHERE date > ?", (start.isoformat(),)).fetchone()[0]
    assert used == rep["demand"]
    short = conn.execute("SELECT COALESCE(SUM(qty_short), 0) FROM stockouts").fetchone()[0]
    assert short == rep["demand"] - rep["issued"]


def test_automatic_mode_sends_orders_and_drafts_mode_waits(conn):
    rep = sim.advance(conn, 1, auto_mode=sim.AUTO_MODES[2], seed=1)
    assert rep["sent"] and not rep["drafted"]
    assert all(pu.order_header(conn, o)["status"] == "SENT" for o in rep["sent"])
    db.reset(conn)
    rep = sim.advance(conn, 1, auto_mode=sim.AUTO_MODES[1], seed=1)
    assert rep["drafted"] and not rep["sent"]
    _, open_pos = db.load_stock(conn)
    assert open_pos.empty                                           # drafts are not on order


def test_a_shipped_line_can_arrive_as_several_lots(conn, monkeypatch):
    monkeypatch.setattr(pu, "SPLIT_LOT_CHANCE", 1.0)                 # every line splits
    order_no = pu.create_order(conn, "Overseas Medical Imports", [("CON004", 80)])
    pu.send_order(conn, order_no)
    line = pu.order_lines(conn, order_no).iloc[0]
    asn = db.asn_lots(conn, line["po_id"])
    assert len(asn) >= 2
    assert sum(q for _, _, q in asn) == line["confirmed_qty"]         # the lots add up to the confirmed qty
    assert len({l for l, _, _ in asn}) == len(asn)                   # different lot numbers
    assert [e for _, e, _ in asn] == sorted(e for _, e, _ in asn)    # earliest expiry first
    db.set_today(conn, pu._d(pu.order_header(conn, order_no)["arrive_date"]))
    got = pu.receive_order(conn, order_no)
    assert len(got) == len(asn)
    for lot_no, expiry, qty in asn:
        row = conn.execute("SELECT qty, expiry_date FROM lots WHERE lot_no = ?", (lot_no,)).fetchone()
        assert row["qty"] == qty and row["expiry_date"] == expiry.isoformat()


def test_lot_split_does_not_change_the_vendors_other_choices(conn, monkeypatch):
    def story(split):
        c = db.connect(conn.execute("PRAGMA database_list").fetchone()[2].replace("test.db", f"s{split}.db"))
        monkeypatch.setattr(pu, "SPLIT_LOT_CHANCE", split)
        o = pu.create_order(c, "Overseas Medical Imports", [("CON004", 80), ("CON006", 30)])
        pu.send_order(c, o)
        h = pu.order_header(c, o)
        out = (h["ack_date"], h["ship_date"], h["arrive_date"], list(pu.order_lines(c, o)["confirmed_qty"]))
        c.close()
        return out
    assert story(0.0) == story(1.0)


# ---------------------------------------------------------------------------
# Golden run of the live vendor path. Recorded on the code BEFORE the vendor draws were moved behind
# purchasing.OrderNumberDraws, so it proves that normal (non-scenario) orders tell exactly the same story
# as before. If a numpy upgrade changes it, re-record it from unchanged code; never edit it to make it pass.
# ---------------------------------------------------------------------------
GOLDEN_TABLES = ["po_headers", "purchase_orders", "asn_lots", "lots", "deliveries", "transactions",
                 "transaction_lots", "usage", "stockouts", "demand_requests", "vendor_outages", "recalls"]
GOLDEN_FINGERPRINT = "565117e29c822dd9b9f6403fa1d56896e22eb28cba69f3dbc3f39a80fb3f80dd"


def fingerprint(conn, tables=GOLDEN_TABLES):
    """sha256 of every row of the given tables. transactions.created_at is the wall-clock time the row
    was written, so it is left out."""
    h = hashlib.sha256()
    for t in tables:
        cols = ", ".join(r[1] for r in conn.execute(f"PRAGMA table_info({t})") if r[1] != "created_at")
        h.update(t.encode())
        for row in sorted(repr(tuple(r)) for r in conn.execute(f"SELECT {cols} FROM {t}")):
            h.update(row.encode())
    return h.hexdigest()


def test_live_vendor_path_matches_the_recorded_golden_run(conn):
    start = date(2026, 11, 1)
    db.set_today(conn, start)
    # an outage that starts tomorrow: the manual OMI order is acknowledged during it and rejected
    events.start_outage(conn, "Overseas Medical Imports", 10, "Golden test", on_date=start + timedelta(days=1))
    rejected = pu.create_order(conn, "Overseas Medical Imports", [("CON004", 80), ("CON006", 30)])
    pu.send_order(conn, rejected)
    cascade = conn.execute("SELECT item_id FROM items WHERE supplier = 'Cascade Surgical Supply' "
                           "ORDER BY item_id LIMIT 2").fetchall()
    normal = pu.create_order(conn, "Cascade Surgical Supply", [(r[0], 60) for r in cascade])
    pu.send_order(conn, normal)
    sim.advance(conn, 30, auto_mode=sim.AUTO_MODES[2], seed=3, random_events=True)
    assert pu.order_header(conn, rejected)["vendor_note"]                # the rejection path was exercised
    assert conn.execute("SELECT COUNT(*) FROM asn_lots GROUP BY po_id HAVING COUNT(*) > 1").fetchone()  # and a split
    assert fingerprint(conn) == GOLDEN_FINGERPRINT


def test_default_vendor_draws_are_the_order_number_draws(tmp_path):
    """send_order without draws behaves exactly like OrderNumberDraws for that order."""
    stories = []
    for name, explicit in (("a", False), ("b", True)):
        c = db.connect(tmp_path / f"{name}.db")
        o = pu.create_order(c, "Overseas Medical Imports", [("CON004", 80), ("CON006", 30)])
        pu.send_order(c, o, draws=pu.OrderNumberDraws(o) if explicit else None)
        stories.append(fingerprint(c, ["po_headers", "purchase_orders", "asn_lots"]))
        c.close()
    assert stories[0] == stories[1]
