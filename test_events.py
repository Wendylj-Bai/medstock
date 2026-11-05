"""
Tests for recalls, vendor disruptions with backup vendors (events.py) and KPIs (kpis.py).
Each test uses a fresh temporary database.
"""

from datetime import timedelta

import pytest

import db
import events
import kpis
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


def test_every_item_has_a_different_backup_vendor(conn):
    rows = conn.execute("SELECT supplier, backup_supplier FROM items").fetchall()
    assert rows and all(r["backup_supplier"] in pu.VENDORS and r["backup_supplier"] != r["supplier"] for r in rows)


def test_recall_pulls_the_lot_and_is_not_demand(conn):
    lot = conn.execute("SELECT * FROM lots WHERE qty > 0 AND expiry_date > ? LIMIT 1",
                       (db.today(conn).isoformat(),)).fetchone()
    db.issue(conn, lot["item_id"], 1, "ICU")                       # FEFO may or may not take this lot
    usage_before = conn.execute("SELECT SUM(qty_used) FROM usage").fetchone()[0]
    left = conn.execute("SELECT qty FROM lots WHERE lot_id = ?", (lot["lot_id"],)).fetchone()[0]
    res = events.recall_lot(conn, lot["lot_no"], "I", "test")
    assert res["removed"] == left
    assert conn.execute("SELECT qty FROM lots WHERE lot_id = ?", (lot["lot_id"],)).fetchone()[0] == 0
    assert conn.execute("SELECT SUM(qty_used) FROM usage").fetchone()[0] == usage_before   # not demand
    assert conn.execute("SELECT COUNT(*) FROM transactions WHERE type = 'RECALL'").fetchone()[0] == 1
    with pytest.raises(db.StockError):
        events.recall_lot(conn, lot["lot_no"], "I", "again")          # only once


def test_recalled_lot_on_its_way_is_refused_at_the_dock(conn):
    order_no = pu.create_order(conn, "Overseas Medical Imports", [("CON004", 50), ("CON006", 10)])
    pu.send_order(conn, order_no)
    lines = pu.order_lines(conn, order_no)
    bad = lines.iloc[0]
    events.recall_lot(conn, bad["asn_lot_no"], "II", "test")
    db.set_today(conn, pu._d(pu.order_header(conn, order_no)["arrive_date"]))
    got = pu.receive_order(conn, order_no)
    assert [g[2] for g in got] == [lines.iloc[1]["asn_lot_no"]]       # only the good line was received
    assert conn.execute("SELECT COUNT(*) FROM lots WHERE lot_no = ?", (bad["asn_lot_no"],)).fetchone()[0] == 0
    assert pu.order_header(conn, order_no)["status"] == "RECEIVED"


def test_disrupted_vendor_rejects_orders_and_backup_takes_over(conn):
    today = db.today(conn)
    events.start_outage(conn, "Pacific Pharma Supply", 14, "test")
    order_no = pu.create_order(conn, "Pacific Pharma Supply", [("MED001", 10)])
    pu.send_order(conn, order_no)
    ack = pu._d(pu.order_header(conn, order_no)["ack_date"])
    db.set_today(conn, ack)
    assert pu.process_vendor_responses(conn, ack) == [order_no]
    assert pu.order_header(conn, order_no)["status"] == "CANCELLED"
    _, open_pos = db.load_stock(conn)
    assert open_pos.empty                                             # nothing on order any more
    # the reorder plan now sends Pacific Pharma's items to their backup, at a premium
    plan = plan_for(conn)
    made = pu.draft_suggested_orders(conn, plan, on_date=ack)
    suppliers = {pu.order_header(conn, o)["supplier"] for o in made}
    assert "Pacific Pharma Supply" not in suppliers
    pps_items = set(plan.loc[plan["supplier"] == "Pacific Pharma Supply", "item_id"])
    backup_lines = conn.execute("SELECT p.item_id, p.unit_cost, i.unit_cost FROM purchase_orders p JOIN items i "
                                "USING (item_id) WHERE p.status = 'DRAFT'").fetchall()
    for item_id, price, contract in backup_lines:
        if item_id in pps_items:
            assert price == pytest.approx(round(contract * (1 + pu.BACKUP_PREMIUM), 2))
    # when the vendor is back, ordering returns to it
    events.end_outage(conn, "Pacific Pharma Supply", ack)
    assert pu.active_outage(conn, "Pacific Pharma Supply", ack) is None
    assert today <= ack


def test_random_events_happen_in_the_simulation(conn, monkeypatch):
    monkeypatch.setattr(sim, "OUTAGE_PER_DAY", 1.0)
    monkeypatch.setattr(sim, "RECALL_PER_DAY", 1.0)
    rep = sim.advance(conn, 2, seed=1, random_events=True)
    kinds = " ".join(e["event"] for e in rep["events"])
    assert "cannot supply" in kinds and "Recall" in kinds
    assert conn.execute("SELECT COUNT(*) FROM recalls").fetchone()[0] == 2


def test_kpis_add_up(conn):
    start = db.today(conn)
    sim.advance(conn, 14, auto_mode=sim.AUTO_MODES[2], seed=2)
    end = db.today(conn)
    k = kpis.compute(conn, start + timedelta(days=1), end)
    demand = conn.execute("SELECT SUM(qty_used) FROM usage WHERE date > ?", (start.isoformat(),)).fetchone()[0]
    short = conn.execute("SELECT COALESCE(SUM(qty_short), 0) FROM stockouts").fetchone()[0]
    assert k["demand"] == demand and k["short"] == short
    assert k["fill_rate"] == pytest.approx(1 - short / demand)
    # inventory rebuilt from the ledger ends at today's real shelf value
    shelf = conn.execute("SELECT SUM(l.qty * i.unit_cost) FROM lots l JOIN items i USING (item_id)").fetchone()[0]
    assert k["inventory_series"].iloc[-1] == pytest.approx(shelf)
    assert k["turns"] > 0 and k["days_on_hand"] > 0
    assert not kpis.weekly(conn, start, end).empty


def test_recall_of_one_lot_in_a_split_delivery_refuses_only_that_lot(conn, monkeypatch):
    monkeypatch.setattr(pu, "SPLIT_LOT_CHANCE", 1.0)
    order_no = pu.create_order(conn, "Overseas Medical Imports", [("CON004", 80)])
    pu.send_order(conn, order_no)
    line = pu.order_lines(conn, order_no).iloc[0]
    asn = db.asn_lots(conn, line["po_id"])
    bad, good = asn[-1], asn[:-1]
    events.recall_lot(conn, bad[0], "II", "test")                    # found although it is not the first lot
    db.set_today(conn, pu._d(pu.order_header(conn, order_no)["arrive_date"]))
    got = pu.receive_order(conn, order_no)
    assert sorted(g[2] for g in got) == sorted(l for l, _, _ in good)
    assert conn.execute("SELECT COUNT(*) FROM lots WHERE lot_no = ?", (bad[0],)).fetchone()[0] == 0
    row = conn.execute("SELECT status, received_qty FROM purchase_orders WHERE po_id = ?", (line["po_id"],)).fetchone()
    assert row["status"] == "RECEIVED" and row["received_qty"] == sum(q for _, _, q in good)   # closed short
    assert pu.order_header(conn, order_no)["status"] == "RECEIVED"


def test_random_picks_match_the_events_they_start(tmp_path):
    """The confirmation shows a random event chosen in advance. Choosing it must use the same random
    draws as before, so seeded simulations give the same results."""
    import numpy as np
    a, b = db.connect(tmp_path / "a.db"), db.connect(tmp_path / "b.db")
    pick = events.pick_random_recall(a, np.random.default_rng(7))
    res = events.random_recall(b, np.random.default_rng(7))
    assert pick["lot_no"] == res["lot_no"]
    assert tuple(b.execute("SELECT recall_class, reason FROM recalls").fetchone()) == (pick["recall_class"], pick["reason"])
    assert a.execute("SELECT COUNT(*) FROM recalls").fetchone()[0] == 0          # picking changes nothing
    o_pick = events.pick_random_outage(a, np.random.default_rng(11))
    o_res = events.random_outage(b, np.random.default_rng(11))
    assert (o_pick["supplier"], o_pick["days"]) == (o_res["supplier"], o_res["days"])
    assert a.execute("SELECT COUNT(*) FROM vendor_outages").fetchone()[0] == 0
    a.close(); b.close()


def test_recall_preview_matches_what_the_recall_removes(conn):
    lot = conn.execute("SELECT lot_no FROM lots WHERE qty > 0 ORDER BY lot_id LIMIT 1").fetchone()[0]
    pv = events.recall_preview(conn, lot)
    res = events.recall_lot(conn, lot, "II", "test")
    assert pv["qty"] == res["removed"] and abs(pv["value"] - res["value"]) < 1e-9
    assert pv["item_id"] == res["item_id"]
