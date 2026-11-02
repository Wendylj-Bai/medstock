"""
Tests for the stock movement rules in db.py and the expiry projection in planning.py.
Each test uses a fresh temporary database, so your real data is never touched.
"""

from datetime import date, timedelta

import pandas as pd
import pytest

import db
import planning

TODAY = date.today()


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")      # new file -> imports the sample CSVs
    yield c
    c.close()


def add_lot(conn, item_id, lot_no, days_to_expiry, qty):
    """Put a lot directly on the shelf (test helper)."""
    with conn:
        conn.execute("INSERT INTO lots (item_id, lot_no, expiry_date, qty, received_date) VALUES (?, ?, ?, ?, ?)",
                     (item_id, lot_no, (TODAY + timedelta(days=days_to_expiry)).isoformat(), qty, TODAY.isoformat()))
    return conn.execute("SELECT lot_id FROM lots WHERE lot_no = ?", (lot_no,)).fetchone()[0]


def lot_qty(conn, lot_no):
    return conn.execute("SELECT qty FROM lots WHERE lot_no = ?", (lot_no,)).fetchone()[0]


@pytest.fixture
def item(conn):
    """An item with a clean, known set of lots: 10 expired, 5 (30 days), 20 (300 days)."""
    with conn:
        conn.execute("DELETE FROM lots WHERE item_id = 'CON004'")
    add_lot(conn, "CON004", "OLD", -3, 10)
    add_lot(conn, "CON004", "SOON", 30, 5)
    add_lot(conn, "CON004", "LATE", 300, 20)
    return "CON004"


# --- Issue -----------------------------------------------------------------

def test_issue_is_fefo_and_skips_expired(conn, item):
    picks = db.issue(conn, item, 8, "ICU")
    assert picks == [("SOON", 5), ("LATE", 3)]        # soonest-expiring USABLE lot first
    assert lot_qty(conn, "OLD") == 10                  # expired lot untouched
    assert db.on_hand(conn, item) == 10 + 0 + 17


def test_cannot_issue_expired_stock(conn, item):
    with pytest.raises(db.StockError, match="expired"):
        db.issue(conn, item, 26, "ICU")                # 35 on shelf but only 25 usable
    assert db.on_hand(conn, item) == 35                # nothing changed
    assert db.ledger(conn).empty                       # and nothing was logged


def test_issue_counts_as_usage_and_is_logged(conn, item):
    usage_rows = conn.execute("SELECT COUNT(*) FROM usage").fetchone()[0]
    db.issue(conn, item, 4, "Emergency Department")
    assert conn.execute("SELECT COUNT(*) FROM usage").fetchone()[0] == usage_rows + 1
    log = db.ledger(conn)
    assert log.iloc[0]["type"] == "ISSUE" and log.iloc[0]["qty"] == -4
    assert log.iloc[0]["balance_after"] == 31


def test_bad_inputs_are_rejected(conn, item):
    for bad in [0, 2.5, -1]:
        with pytest.raises(db.StockError):
            db.issue(conn, item, bad, "ICU")
    with pytest.raises(db.StockError):
        db.issue(conn, "NOPE", 1, "ICU")
    with pytest.raises(db.StockError):
        db.issue(conn, item, 1, "ICU", TODAY + timedelta(days=1))


# --- Purchase orders and receiving -----------------------------------------

def test_po_then_receive_creates_lot_and_records_lead_time(conn):
    n_deliveries = conn.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0]
    before = db.on_hand(conn, "MED005")
    po_id = db.create_po(conn, "MED005", 100, TODAY - timedelta(days=12))
    assert db.on_hand(conn, "MED005") == before        # ordering does not change stock

    lead_time = db.receive(conn, po_id, 90, "NEWLOT", TODAY + timedelta(days=700))   # short delivery: 90 of 100
    assert lead_time == 12
    assert db.on_hand(conn, "MED005") == before + 90
    assert lot_qty(conn, "NEWLOT") == 90
    assert conn.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0] == n_deliveries + 1
    row = conn.execute("SELECT status, received_qty FROM purchase_orders WHERE po_id = ?", (po_id,)).fetchone()
    assert row["status"] == "OPEN" and row["received_qty"] == 90     # a short receipt stays OPEN
    db.receive(conn, po_id, 10, "REST", TODAY + timedelta(days=700)) # completing is allowed
    assert db.on_hand(conn, "MED005") == before + 100
    assert conn.execute("SELECT status FROM purchase_orders WHERE po_id = ?",
                        (po_id,)).fetchone()[0] == "RECEIVED"
    with pytest.raises(db.StockError):                 # cannot receive above what was ordered
        db.receive(conn, po_id, 1, "X", TODAY + timedelta(days=700))


def test_receive_rejects_expired_lot_or_missing_lot_number(conn):
    po_id = db.create_po(conn, "MED005", 10, TODAY - timedelta(days=5))
    with pytest.raises(db.StockError, match="expired"):
        db.receive(conn, po_id, 10, "BAD", TODAY)
    with pytest.raises(db.StockError, match="Lot number"):
        db.receive(conn, po_id, 10, "  ", TODAY + timedelta(days=100))


def test_open_po_counts_in_inventory_position(conn):
    items, usage, deliveries, open_pos, _ = db.load_frames(conn)
    plan = planning.build_plan(items, usage, deliveries, open_pos=open_pos)
    red = plan[plan["status"].str.startswith("🔴")].iloc[0]

    db.create_po(conn, red["item_id"], int(red["order_qty"]))
    items, usage, deliveries, open_pos, _ = db.load_frames(conn)
    plan = planning.build_plan(items, usage, deliveries, open_pos=open_pos)
    after = plan[plan["item_id"] == red["item_id"]].iloc[0]
    assert after["on_order"] == red["order_qty"]
    assert not after["status"].startswith("🔴")        # no longer asks to order again


def test_expired_stock_does_not_count_as_usable(conn, item):
    items, *_ = db.load_frames(conn)
    row = items[items["item_id"] == item].iloc[0]
    assert row["on_hand"] == 35 and row["usable"] == 25


# --- Write-offs, counts, recalls ---------------------------------------------

def test_write_off_is_not_demand(conn, item):
    usage_rows = conn.execute("SELECT COUNT(*) FROM usage").fetchone()[0]
    old = conn.execute("SELECT lot_id FROM lots WHERE lot_no = 'OLD'").fetchone()[0]
    db.write_off(conn, old, 10, "Expired")
    assert lot_qty(conn, "OLD") == 0
    assert conn.execute("SELECT COUNT(*) FROM usage").fetchone()[0] == usage_rows
    with pytest.raises(db.StockError):
        db.write_off(conn, old, 1, "Expired")          # lot is empty now


def test_write_off_all_expired(conn, item):
    n, value = db.write_off_all_expired(conn)
    assert n >= 1 and value > 0
    assert lot_qty(conn, "OLD") == 0 and lot_qty(conn, "SOON") == 5


def test_cycle_count_per_lot_tracks_accuracy(conn, item):
    late = conn.execute("SELECT lot_id FROM lots WHERE lot_no = 'LATE'").fetchone()[0]
    assert db.cycle_count(conn, late, 20) == 0                  # match
    assert db.cycle_count(conn, late, 17) == -3                 # 3 missing
    assert lot_qty(conn, "LATE") == 17
    accuracy, n = db.record_accuracy(conn)
    assert n == 2 and accuracy == 0.5


def test_lot_trace_shows_which_ward_got_the_lot(conn, item):
    db.issue(conn, item, 3, "ICU")
    db.issue(conn, item, 4, "Pediatrics")             # 2 from SOON, then 2 from LATE
    trace = db.lot_trace(conn, "SOON")
    assert list(trace["ward_or_reference"]) == ["ICU", "Pediatrics"]
    assert list(trace["qty"]) == [-3, -2]


# --- Expiry projection -------------------------------------------------------

def test_project_expiry_fefo_waste():
    today = pd.Timestamp("2026-01-01")
    lots = pd.DataFrame({
        "lot_id": [1, 2, 3],
        "item_id": ["X", "X", "X"],
        "lot_no": ["A", "B", "C"],
        "expiry_date": pd.to_datetime(["2025-12-25", "2026-01-11", "2026-03-02"]),
        "qty": [7, 100, 100],
    })
    out = planning.project_expiry(lots, {"X": 5}, today).set_index("lot_no")
    # A: already expired -> all of it is waste
    assert out.loc["A", "projected_waste"] == 7
    # B: 10 days left at 5/day -> use 50, waste 50
    assert out.loc["B", "projected_use"] == 50 and out.loc["B", "projected_waste"] == 50
    # C: 60 days left, but the first 10 days go to lot B -> 50 days x 5 = 250 >= 100, no waste
    assert out.loc["C", "projected_waste"] == 0
    assert list(out["expiry_band"]) == ["Expired", "≤ 30 days", "31-90 days"]
