"""
Regression tests for the inventory transaction fixes (cumulative receipts,
movement-date guards, request fulfillment, transaction rollback).
Each test uses a fresh temporary database, so your real data is never touched.
"""

from datetime import date, timedelta

import pytest

import db
import purchasing as pu


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    yield c
    c.close()


def on_order(conn, item_id):
    _, open_pos = db.load_stock(conn)
    return int(open_pos.loc[open_pos["item_id"] == item_id, "qty"].sum())


def add_lot(conn, item_id, lot_no, qty, days_to_expiry=700):
    with conn:
        conn.execute("INSERT INTO lots (item_id, lot_no, expiry_date, qty, received_date) VALUES (?, ?, ?, ?, ?)",
                     (item_id, lot_no, (db.today(conn) + timedelta(days=days_to_expiry)).isoformat(),
                      qty, db.today(conn).isoformat()))


# --- Cumulative partial receipts --------------------------------------------

def test_partial_40_then_60_of_100_closes_and_on_order_remainder(conn):
    T = db.today(conn)
    po_id = db.create_po(conn, "MED005", 100, T - timedelta(days=10))
    db.receive(conn, po_id, 40, "LOT40", T + timedelta(days=600))
    row = conn.execute("SELECT status, received_qty FROM purchase_orders WHERE po_id = ?", (po_id,)).fetchone()
    assert row["status"] == "OPEN" and row["received_qty"] == 40
    assert on_order(conn, "MED005") == 60
    assert int(db.load_stock(conn)[1].query('item_id == "MED005"')["ordered_qty"].sum()) == 100
    db.receive(conn, po_id, 60, "LOT60", T + timedelta(days=600))
    assert conn.execute("SELECT status FROM purchase_orders WHERE po_id = ?", (po_id,)).fetchone()[0] == "RECEIVED"
    assert conn.execute("SELECT received_qty FROM purchase_orders WHERE po_id = ?", (po_id,)).fetchone()[0] == 100
    assert on_order(conn, "MED005") == 0
    assert conn.execute("SELECT COUNT(*) FROM deliveries WHERE po_id = ?", (po_id,)).fetchone()[0] == 2


def test_overreceive_is_rejected_and_rolls_back(conn):
    T = db.today(conn)
    po_id = db.create_po(conn, "MED005", 100, T - timedelta(days=10))
    db.receive(conn, po_id, 90, "PART", T + timedelta(days=600))
    before = db.on_hand(conn, "MED005")
    with pytest.raises(db.StockError):
        db.receive(conn, po_id, 15, "TOO", T + timedelta(days=600))          # only 10 outstanding
    assert db.on_hand(conn, "MED005") == before
    row = conn.execute("SELECT status, received_qty FROM purchase_orders WHERE po_id = ?", (po_id,)).fetchone()
    assert row["status"] == "OPEN" and row["received_qty"] == 90
    assert conn.execute("SELECT COUNT(*) FROM lots WHERE lot_no = 'TOO'").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM deliveries WHERE po_id = ?", (po_id,)).fetchone()[0] == 1
    with pytest.raises(db.StockError):
        db.receive(conn, po_id, 11, "Y", T + timedelta(days=600))            # overdelivers 1 past remaining 10
    assert conn.execute("SELECT COUNT(*) FROM lots WHERE lot_no = 'Y'").fetchone()[0] == 0


def test_expired_second_line_rolls_back_whole_shipment(conn):
    start = db.today(conn)
    order_no = pu.create_order(conn, "Overseas Medical Imports", [("MED005", 100), ("CON006", 50)])
    pu.send_order(conn, order_no)
    arrive = date.fromisoformat(pu.order_header(conn, order_no)["arrive_date"])
    with conn:                                                     # second line arrives already expired
        conn.execute("UPDATE purchase_orders SET asn_expiry = ? WHERE order_no = ? AND line_no = 2",
                     ((arrive - timedelta(days=1)).isoformat(), order_no))
        conn.execute("UPDATE asn_lots SET expiry_date = ? WHERE po_id IN (SELECT po_id FROM purchase_orders "
                     "WHERE order_no = ? AND line_no = 2)", ((arrive - timedelta(days=1)).isoformat(), order_no))
    db.set_today(conn, arrive)
    med_before = db.on_hand(conn, "MED005")
    con_before = db.on_hand(conn, "CON006")
    with pytest.raises(db.StockError, match="expired"):
        pu.receive_order(conn, order_no)
    assert db.on_hand(conn, "MED005") == med_before and db.on_hand(conn, "CON006") == con_before
    assert conn.execute(
        "SELECT COUNT(*) FROM lots WHERE po_id IN (SELECT po_id FROM purchase_orders WHERE order_no = ?)",
        (order_no,)).fetchone()[0] == 0
    assert set(pu.order_lines(conn, order_no)["status"]) == {"OPEN"}
    assert conn.execute(
        "SELECT COUNT(*) FROM deliveries WHERE po_id IN (SELECT po_id FROM purchase_orders WHERE order_no = ?)",
        (order_no,)).fetchone()[0] == 0


# --- Demand requests --------------------------------------------------------

def test_manual_request_shortage_is_true_demand_and_duplicate_id(conn):
    T = db.today(conn)
    with conn:
        conn.execute("DELETE FROM lots WHERE item_id = 'MED005'")
    add_lot(conn, "MED005", "MANUAL", 4)
    used = conn.execute("SELECT COUNT(*) FROM usage WHERE date = ?", (T.isoformat(),)).fetchone()[0]
    out = conn.execute("SELECT COUNT(*) FROM stockouts WHERE date = ?", (T.isoformat(),)).fetchone()[0]
    r = db.fulfill_request(conn, "MED005", 10, "ICU", T, "trauma tray", "REQ1")
    assert (r["requested"], r["filled"], r["short"]) == (10, 4, 6)
    assert [p[0] for p in r["picks"]] == ["MANUAL"]
    req = conn.execute("SELECT * FROM demand_requests WHERE request_id = 'REQ1'").fetchone()
    assert (req["item_id"], req["ward"], req["requested"], req["filled"], req["short"]) == ("MED005", "ICU", 10, 4, 6)
    assert conn.execute("SELECT SUM(qty_used) FROM usage WHERE item_id = 'MED005' AND date = ?",
                        (T.isoformat(),)).fetchone()[0] == 10            # filled + short = true demand
    assert conn.execute("SELECT qty_short FROM stockouts WHERE item_id = 'MED005' AND date = ?",
                        (T.isoformat(),)).fetchone()[0] == 6
    assert conn.execute("SELECT COUNT(*) FROM usage WHERE date = ?", (T.isoformat(),)).fetchone()[0] == used + 2
    assert conn.execute("SELECT COUNT(*) FROM stockouts WHERE date = ?", (T.isoformat(),)).fetchone()[0] == out + 1
    again = db.fulfill_request(conn, "MED005", 10, "ICU", T, "trauma tray", "REQ1")
    assert again["filled"] == 4 and again["short"] == 6 and again["picks"] == [["MANUAL", 4]]
    assert db.on_hand(conn, "MED005") == 0                                # the 4 were served once, not twice
    assert conn.execute("SELECT COUNT(*) FROM usage WHERE date = ?", (T.isoformat(),)).fetchone()[0] == used + 2
    assert conn.execute("SELECT COUNT(*) FROM stockouts WHERE date = ?", (T.isoformat(),)).fetchone()[0] == out + 1
    with pytest.raises(db.StockError):                                   # same id, different request
        db.fulfill_request(conn, "MED005", 12, "ICU", T, "trauma tray", "REQ1")


# --- Movement dates ---------------------------------------------------------

def test_movements_before_receipt_are_rejected(conn):
    T = db.today(conn)
    po_id = db.create_po(conn, "MED005", 100, T - timedelta(days=10))
    db.receive(conn, po_id, 100, "NEWLOT", T + timedelta(days=600))
    with pytest.raises(db.StockError, match="before"):
        db.issue(conn, "MED005", 1, "ICU", T - timedelta(days=1))
    lot = conn.execute("SELECT lot_id FROM lots WHERE lot_no = 'NEWLOT'").fetchone()[0]
    with pytest.raises(db.StockError, match="before"):
        db.write_off(conn, lot, 1, "Expired", T - timedelta(days=1))
    with pytest.raises(db.StockError, match="before"):
        db.cycle_count(conn, lot, 99, T - timedelta(days=1))
    po2 = db.create_po(conn, "MED005", 50, T - timedelta(days=1))
    with pytest.raises(db.StockError, match="before"):
        db.receive(conn, po2, 10, "EARLY", T + timedelta(days=600), T - timedelta(days=2))


# --- Transaction rollback ---------------------------------------------------

def test_nested_atomic_rolls_back_cleanly(conn):
    T = db.today(conn)
    add_lot(conn, "MED005", "NEST", 7)
    before = db.on_hand(conn, "MED005")
    used = conn.execute("SELECT COUNT(*) FROM usage WHERE item_id = 'MED005' AND date = ?",
                        (T.isoformat(),)).fetchone()[0]
    with pytest.raises(RuntimeError):
        with db.atomic(conn), db.atomic(conn):
            db.issue(conn, "MED005", 3, "ICU", T)
            db.issue(conn, "MED005", 3, "ICU", T)
            raise RuntimeError("fail mid-transaction")
    assert db.on_hand(conn, "MED005") == before                          # both issues undone
    assert conn.execute("SELECT COUNT(*) FROM transactions WHERE item_id = 'MED005' AND type = 'ISSUE'"
                        ).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM usage WHERE item_id = 'MED005' AND date = ?",
                        (T.isoformat(),)).fetchone()[0] == used
    db.issue(conn, "MED005", 2, "ICU", T)                                # the connection still works
    assert db.on_hand(conn, "MED005") == before - 2


def test_shelf_life_warning_only_for_orders_the_cap_really_cut(conn):
    """order_qty is a whole number, so it is usually a little below the exact target. That rounding must not
    raise the shelf-life warning; only the shelf-life cap may."""
    import planning
    items, usage, deliveries, open_pos, _ = db.load_frames(conn)
    plan = planning.build_plan(items, usage, deliveries, open_pos=open_pos)
    capped = plan[plan["order_capped"]]
    assert len(capped) < len(plan[plan["status"].str.startswith("🔴")])
    for r in capped.itertuples():
        assert r.order_qty == int(r.d * r.shelf_life_days * 0.8)       # the cap decided the quantity
