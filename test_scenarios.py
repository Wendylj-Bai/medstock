"""
Tests for scenario comparison (scenarios.py) and its money measures (kpis.py).

Scenario runs use the frozen in-memory baseline built from the sample CSVs. The hand-made metric test uses
a temporary database (tmp_path). Nothing here opens data/medstock.db.
"""

import hashlib
import inspect
import sqlite3
from datetime import date, timedelta

import pytest

import db
import events
import forecasting as fc
import kpis
import purchasing as pu
import scenarios as sc
import simulation as sim

DAYS = 14                       # short runs keep the suite fast; the engine allows 7 to 60
BANNED = ["better", "worse", "winner", "recommended policy", "recommend"]


@pytest.fixture(scope="module")
def result():
    return sc.compare(0.95, DAYS, seed=5)


@pytest.fixture
def baseline():
    c = sc.build_baseline()
    yield c
    c.close()


# ---------------------------------------------------------------------------
# Baseline
# ---------------------------------------------------------------------------

def test_baseline_is_the_frozen_sample_data(baseline):
    last = baseline.execute("SELECT MAX(date) FROM usage").fetchone()[0]
    assert db.today(baseline) == date.fromisoformat(last) + timedelta(days=1) == date(2026, 11, 1)
    assert baseline.execute("SELECT COUNT(*) FROM purchase_orders").fetchone()[0] == 0     # no orders, no drafts
    assert baseline.execute("SELECT COUNT(*) FROM po_headers").fetchone()[0] == 0
    other = sc.build_baseline()
    assert sc.operational_fingerprint(other) == sc.operational_fingerprint(baseline)        # rebuilt identically
    other.close()
    assert sc.baseline_fingerprint() == hashlib.sha256(
        b"".join((db.DATA / f"{t}.csv").read_bytes() for t in sc.BASELINE_TABLES)).hexdigest()


def test_drafts_in_the_baseline_stop_the_run(baseline):
    item = baseline.execute("SELECT item_id, supplier FROM items ORDER BY item_id LIMIT 1").fetchone()
    pu.create_order(baseline, item["supplier"], [(item["item_id"], 5)])
    with pytest.raises(db.StockError, match="draft"):
        sc.run_one(baseline, sc.POLICY_A, sc.DAYS_MIN, 1)


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

def test_scope_and_defaults(result):
    assert sc.POLICY_A == {"V": 0.99, "E": 0.95, "D": 0.90}
    assert (sc.DAYS_MIN, sc.DAYS_MAX, sc.DEFAULT_DAYS, sc.MAX_REPLICATIONS) == (7, 60, 60, 5)
    params = inspect.signature(sc.compare).parameters
    assert params["days"].default == 60 and params["replications"].default == 1
    i = result["inputs"]
    assert i["policy_a"] == {"V": 0.99, "E": 0.95, "D": 0.90}
    assert i["policy_b"] == {"V": 0.95, "E": 0.95, "D": 0.90}                  # only Vital changes
    assert i["random_events"] is False and i["auto_mode"] == sim.AUTO_MODES[2]
    assert i["days"] == DAYS and i["seeds"] == [5] and i["baseline_start"] == date(2026, 11, 1)
    assert i["forecast_method"] == "Auto" and i["forecast_params"] == fc.DEFAULT_PARAMS
    assert i["baseline_fingerprint"] == sc.baseline_fingerprint()


@pytest.mark.parametrize("vital_b, days, seed, runs", [
    (0.79, 60, 1, 1), (1.0, 60, 1, 1), (0.99, 60, 1, 1), (True, 60, 1, 1), ("0.95", 60, 1, 1),
    (0.95, 6, 1, 1), (0.95, 61, 1, 1), (0.95, 30.0, 1, 1), (0.95, True, 1, 1),
    (0.95, 60, -1, 1), (0.95, 60, 2**32, 1), (0.95, 60, 1.5, 1), (0.95, 60, 2**32 - 1, 2),
    (0.95, 60, 1, 0), (0.95, 60, 1, 6),
])
def test_bad_inputs_are_rejected(vital_b, days, seed, runs):
    with pytest.raises(db.StockError):
        sc.validate(vital_b, days, seed, runs)


def test_boundary_inputs_are_accepted():
    sc.validate(0.80, 7, 0, 1)
    sc.validate(0.999, 60, 2**32 - 1, 1)
    sc.validate(0.95, 60, 2**32 - 5, 5)


# ---------------------------------------------------------------------------
# Pairing: demand and vendor conditions
# ---------------------------------------------------------------------------

def test_paired_vendor_draws_depend_only_on_their_key():
    d = date(2026, 11, 5)
    a, b = pu.PairedVendorDraws(3), pu.PairedVendorDraws(3)
    b.line("Pacific Pharma Supply", "MED001", d)                      # b draws other keys first
    b.header("Cascade Surgical Supply", d)
    assert (a.header("Pacific Pharma Supply", d).random(4) == b.header("Pacific Pharma Supply", d).random(4)).all()
    assert (a.line("Cascade Surgical Supply", "CON004", d).random(4)
            == b.line("Cascade Surgical Supply", "CON004", d).random(4)).all()
    c = pu.PairedVendorDraws(4)
    assert (c.header("Pacific Pharma Supply", d).random(4) != pu.PairedVendorDraws(3).header(
        "Pacific Pharma Supply", d).random(4)).any()                                   # the seed matters
    with pytest.raises(db.StockError, match="twice"):
        a.header("Pacific Pharma Supply", d)                                           # a key is used once
    assert len(a.keys) == 2


def test_paired_vendor_outcome_does_not_depend_on_the_order_number(baseline):
    item = baseline.execute("SELECT item_id FROM items WHERE supplier = 'Overseas Medical Imports' "
                            "ORDER BY item_id LIMIT 2").fetchall()
    first, other = item[0][0], item[1][0]
    day = db.today(baseline)
    stories = []
    for extra_orders in (0, 2):                                     # shifts the PO number of the real order
        c = sc._copy(baseline)
        for _ in range(extra_orders):
            pu.create_order(c, "Overseas Medical Imports", [(other, 5)])
        o = pu.create_order(c, "Overseas Medical Imports", [(first, 80)])
        pu.send_order(c, o, day, draws=pu.PairedVendorDraws(9))
        h = pu.order_header(c, o)
        line = pu.order_lines(c, o).iloc[0]
        stories.append((o, (h["ack_date"], h["ship_date"], h["arrive_date"], h["tracking_no"]),
                        (int(line["confirmed_qty"]), tuple(db.asn_lots(c, line["po_id"])))))
        c.close()
    assert stories[0][0] != stories[1][0]                           # different PO numbers ...
    assert stories[0][1:] == stories[1][1:]                         # ... same vendor story


def test_two_policies_meet_the_same_demand_and_vendor_conditions(result):
    p = result["pairs"][0]["pairing"]
    assert p["demand_identical"] and p["vendor_paired"] and p["comparable"]
    assert p["header_pairs"] > 0 and p["header_pairs_identical"] == p["header_pairs"]
    assert p["line_pairs"] > 0 and p["line_pairs_sharing_first_lot"] == p["line_pairs"]
    assert p["line_pairs_same_qty"] > 0 and p["line_pairs_same_qty_identical"] == p["line_pairs_same_qty"]
    assert p["line_pairs"] > p["line_pairs_same_qty"]          # the policies did order differently ...
    fp = result["pairs"][0]["fingerprints"]
    assert fp["a"] != fp["b"]                                   # ... and the runs did differ
    assert 0 < p["line_coverage"] <= 1


def test_without_paired_draws_vendor_conditions_are_not_paired(baseline):
    """The reason PairedVendorDraws exists: with the live PO-number seeding, the same seed gives the two
    policies the same demand but different vendor stories."""
    runs = []
    for sl in (sc.POLICY_A, {**sc.POLICY_A, "V": 0.95}):
        c = sc._copy(baseline)
        start = db.today(c)
        sim.advance(c, DAYS, sl, "Auto", dict(fc.DEFAULT_PARAMS), sim.AUTO_MODES[2], seed=5)
        runs.append({"evidence": sc._evidence(c, start)})
        c.close()
    p = sc.pairing_report(*runs)
    assert p["demand_identical"] and not p["vendor_paired"]


# ---------------------------------------------------------------------------
# Identical and repeated runs
# ---------------------------------------------------------------------------

def test_identical_policies_give_identical_operational_results(baseline):
    a1 = sc.run_one(baseline, sc.POLICY_A, DAYS, 5)
    a2 = sc.run_one(baseline, sc.POLICY_A, DAYS, 5)
    assert a1["fingerprint"] == a2["fingerprint"]
    assert a1["measures"] == a2["measures"]
    assert a1["draw_keys"] == a2["draw_keys"]
    p = sc.pairing_report(a1, a2)
    assert p["comparable"] and p["line_coverage"] == 1 and p["line_pairs_same_qty"] == p["line_pairs"]


def test_repeated_comparisons_are_identical(result):
    again = sc.compare(0.95, DAYS, seed=5)
    for x, y in zip(result["pairs"], again["pairs"]):
        assert (x["a"], x["b"], x["diff"], x["pairing"], x["fingerprints"]) == \
               (y["a"], y["b"], y["diff"], y["pairing"], y["fingerprints"])
    assert result["summary"].equals(again["summary"])


def test_several_runs_use_consecutive_seeds_and_are_each_checked():
    r = sc.compare(0.95, sc.DAYS_MIN, seed=20, replications=2)
    assert r["inputs"]["seeds"] == [20, 21] and len(r["pairs"]) == 2
    assert all(p["pairing"]["comparable"] for p in r["pairs"])
    assert r["pairs"][0]["fingerprints"]["a"] != r["pairs"][1]["fingerprints"]["a"]   # different demand
    assert not r["summary"]["direction"].str.startswith("single run").any()


# ---------------------------------------------------------------------------
# Isolation: no file is opened or changed
# ---------------------------------------------------------------------------

def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_comparison_never_opens_or_changes_a_database_file(tmp_path, monkeypatch):
    live_path = tmp_path / "live.db"
    db.connect(live_path).close()                                    # stands in for the app's database
    before_live = _sha(live_path)
    csvs = {t: _sha(db.DATA / f"{t}.csv") for t in sc.BASELINE_TABLES}
    real = db.DEFAULT_DB
    real_stat = (real.stat().st_size, real.stat().st_mtime_ns) if real.exists() else None   # stat only

    def no_connect(*_a, **_k):
        raise RuntimeError("scenario comparison must not call db.connect")
    monkeypatch.setattr(db, "connect", no_connect)
    opened, original = [], sqlite3.connect
    monkeypatch.setattr(sqlite3, "connect", lambda target, *a, **k: opened.append(target) or original(target, *a, **k))
    conns, make = [], sc._memory_db
    monkeypatch.setattr(sc, "_memory_db", lambda: conns.append(make()) or conns[-1])

    r = sc.compare(0.95, sc.DAYS_MIN, seed=11)

    assert r["pairs"][0]["pairing"]["comparable"]
    assert opened and all(t == ":memory:" for t in opened)
    assert len(conns) == 3                                          # baseline, run A, run B
    for c in conns:
        with pytest.raises(sqlite3.ProgrammingError):              # every in-memory database was closed
            c.execute("SELECT 1")
    assert _sha(live_path) == before_live
    assert {t: _sha(db.DATA / f"{t}.csv") for t in sc.BASELINE_TABLES} == csvs
    if real_stat:
        assert (real.stat().st_size, real.stat().st_mtime_ns) == real_stat


# ---------------------------------------------------------------------------
# Measures: arithmetic and units
# ---------------------------------------------------------------------------

def test_measures_on_a_hand_made_database(tmp_path):
    conn = db.connect(tmp_path / "kpi.db")
    conn.execute("DELETE FROM lots")
    conn.commit()
    start, end = date(2026, 11, 1), date(2026, 11, 30)
    first = start + timedelta(days=1)
    db.set_today(conn, end)
    cost = lambda i: conn.execute("SELECT unit_cost FROM items WHERE item_id = ?", (i,)).fetchone()[0]
    vital = conn.execute("SELECT item_id FROM items WHERE ved = 'V' ORDER BY item_id LIMIT 1").fetchone()[0]
    other = conn.execute("SELECT item_id FROM items WHERE ved = 'E' ORDER BY item_id LIMIT 1").fetchone()[0]
    p_row = conn.execute("SELECT item_id, supplier, backup_supplier FROM items WHERE backup_supplier IS NOT NULL "
                         "AND item_id NOT IN (?, ?) ORDER BY item_id LIMIT 1", (vital, other)).fetchone()
    p_item = p_row["item_id"]
    cx, cp = cost(vital), cost(p_item)

    lots = [("EXPIRED_BEFORE", "2026-10-30", 5, "2026-10-01"), ("EXP_FIRST_DAY", "2026-11-02", 4, "2026-10-01"),
            ("EXP_LAST_DAY", "2026-11-30", 2, "2026-10-01"), ("EXP_RECEIVED", "2026-11-20", 3, "2026-11-05"),
            ("USABLE", "2027-06-01", 10, "2026-10-01"), ("RECALLED", "2027-06-01", 1, "2026-10-01")]
    for lot_no, expiry, qty, received in lots:
        conn.execute("INSERT INTO lots (item_id, lot_no, expiry_date, qty, received_date) VALUES (?, ?, ?, ?, ?)",
                     (vital, lot_no, expiry, qty, received))
    conn.commit()
    usable_id = conn.execute("SELECT lot_id FROM lots WHERE lot_no = 'USABLE'").fetchone()[0]
    db.write_off(conn, usable_id, 1, "Damaged", date(2026, 11, 1))           # the start day: outside the period
    db.write_off(conn, usable_id, 2, "Damaged", date(2026, 11, 3))
    events.recall_lot(conn, "RECALLED", "II", "test", date(2026, 11, 4))

    # a backup-vendor order (+12%): confirmed 8 of 10, 3 received; and an order not yet acknowledged
    o1 = pu.create_order(conn, p_row["backup_supplier"], [(p_item, 10)], on_date=date(2026, 11, 5))
    o2 = pu.create_order(conn, p_row["supplier"], [(p_item, 7)], on_date=date(2026, 11, 5))
    for o in (o1, o2):
        pu.send_order(conn, o, date(2026, 11, 5))
    with conn:
        conn.execute("UPDATE purchase_orders SET confirmed_qty = 8 WHERE order_no = ?", (o1,))
        conn.execute("UPDATE po_headers SET ack_date = '2026-11-05', ship_date = '2026-11-06', "
                     "arrive_date = '2026-11-06', vendor_note = NULL WHERE order_no = ?", (o1,))
        conn.execute("UPDATE purchase_orders SET confirmed_qty = 5 WHERE order_no = ?", (o2,))
        conn.execute("UPDATE po_headers SET ack_date = '2026-12-31', vendor_note = NULL WHERE order_no = ?", (o2,))
    po1 = pu.order_lines(conn, o1).iloc[0]
    po2 = pu.order_lines(conn, o2).iloc[0]
    price1, price2 = float(po1["unit_cost"]), float(po2["unit_cost"])
    assert price1 == round(cp * (1 + pu.BACKUP_PREMIUM), 2) != cp
    db.receive(conn, po1["po_id"], 3, "TESTP", date(2027, 5, 1), date(2026, 11, 6))

    # demand: a Vital item short on day 2 and day 19, an Essential item fully served
    conn.executemany("INSERT INTO usage VALUES (?, ?, ?)", [("2026-11-03", vital, 10), ("2026-11-20", vital, 5),
                                                            ("2026-11-03", other, 20)])
    conn.executemany("INSERT INTO stockouts VALUES (?, ?, ?)", [("2026-11-03", vital, 2), ("2026-11-20", vital, 5)])
    conn.commit()

    inv = kpis.ending_inventory(conn, first, end)
    assert inv["expired_before"] == pytest.approx(5 * cx)
    assert inv["newly_expired_baseline"] == pytest.approx((4 + 2) * cx)       # both edge days count
    assert inv["newly_expired_received"] == pytest.approx(3 * cx)
    assert inv["usable"] == pytest.approx(7 * cx + 3 * cp)                  # standard cost, not the PO price
    assert inv["book"] == pytest.approx(inv["usable"] + inv["newly_expired"] + inv["expired_before"])
    losses = kpis.recorded_losses(conn, first, end)
    assert losses == pytest.approx({"write_off_value": 2 * cx, "recall_value": 1 * cx, "total": 3 * cx})
    assert kpis.purchases_received(conn, first, end) == pytest.approx({"value": 3 * price1, "units": 3})
    assert kpis.committed_open(conn, end) == pytest.approx((8 - 3) * price1 + 7 * price2)   # unacknowledged: ordered qty
    freight = sum(pu.order_header(conn, o)["freight"] for o in (o1, o2))
    assert kpis.freight_on_orders_sent(conn, first, end) == pytest.approx(freight)

    m = sc.measures(conn, start, end)
    assert m["fill_rate"] == pytest.approx(1 - 7 / 35)
    assert m["vital_fill_rate"] == pytest.approx(1 - 7 / 15)
    assert (m["vital_stockout_days"], m["vital_stockout_days_early"], m["vital_stockout_days_late"]) == (2, 1, 1)
    assert (m["vital_units_short"], m["vital_units_short_early"], m["vital_units_short_late"]) == (7, 2, 5)
    assert m["recorded_losses"] == pytest.approx(3 * cx) and m["orders_sent"] == 2
    assert 0 <= m["fill_rate"] <= 1 and isinstance(m["book_ending_inventory"], float)
    conn.close()


def test_money_identities_hold_on_a_real_run(baseline):
    c = sc._copy(baseline)
    start = db.today(c)
    rep = sim.advance(c, DAYS, sc.POLICY_A, "Auto", dict(fc.DEFAULT_PARAMS), sim.AUTO_MODES[2], seed=5,
                      vendor_draws=pu.PairedVendorDraws(5))
    end = rep["end"]
    m = sc.measures(c, start, end)
    assert m["book_ending_inventory"] == pytest.approx(
        m["usable_ending_inventory"] + m["newly_expired_on_hand"] + m["expired_before_on_hand"])
    assert m["newly_expired_on_hand"] == pytest.approx(m["newly_expired_baseline"] + m["newly_expired_received"])
    assert m["recorded_losses"] == 0                                # nothing is written off; recalls are off
    # every order line placed in the run is either received or still committed (no cancellations)
    effective = c.execute(
        "SELECT SUM(CASE WHEN h.ack_date <= ? THEN p.confirmed_qty ELSE p.qty END * p.unit_cost) "
        "FROM purchase_orders p JOIN po_headers h USING (order_no)", (end.isoformat(),)).fetchone()[0]
    assert m["purchases_received"] + m["committed_not_received"] == pytest.approx(effective)
    assert c.execute("SELECT COUNT(*) FROM purchase_orders WHERE status IN ('DRAFT', 'CANCELLED')").fetchone()[0] == 0
    assert c.execute("SELECT COUNT(*) FROM (SELECT order_no, item_id FROM purchase_orders "
                     "GROUP BY 1, 2 HAVING COUNT(*) > 1)").fetchone()[0] == 0     # the receipt join is one-to-one
    c.close()


# ---------------------------------------------------------------------------
# No conclusions from the engine
# ---------------------------------------------------------------------------

def _pairs(values, comparable=True):
    return [{"diff": {k: v for k, _, _ in sc.METRICS}, "pairing": {"comparable": comparable}} for v in values]


@pytest.mark.parametrize("values, label", [
    ([3.0], "single run: direction not assessed"),
    ([1.0, 2.0, 0.5, 4.0, 1.5], "same direction in all five runs: B higher than A"),
    ([-1.0, -2.0, -0.5, -4.0, -1.5], "same direction in all five runs: B lower than A"),
    ([-1.0, -2.0], "same direction in all two runs: B lower than A"),
    ([1.0, -2.0, 0.5, 4.0, 1.5], "mixed direction across runs"),
    ([1.0, 0.0, 2.0], "mixed direction across runs"),
    ([0.0, 0.0], "no difference in all two runs"),
])
def test_direction_is_described_not_judged(values, label):
    s = sc.summarize(_pairs(values))
    assert (s["direction"] == label).all()
    row = s.iloc[0]
    assert row["mean_diff"] == pytest.approx(sum(values) / len(values))
    assert (row["min_diff"], row["max_diff"]) == (min(values), max(values))


def test_runs_that_are_not_comparable_are_not_summarized():
    s = sc.summarize(_pairs([1.0, 2.0], comparable=False))
    assert (s["comparable_runs"] == 0).all() and s["mean_diff"].isna().all()
    assert (s["direction"] == "not assessed: a run was not comparable").all()


def test_engine_output_never_ranks_the_policies(result):
    texts = [sc.NOTE, result["note"], *(label for _, label, _ in sc.METRICS),
             *result["summary"]["direction"], *result["summary"]["label"]]
    for values in ([1.0], [1.0] * 5, [-1.0] * 5, [1.0, -1.0], [0.0, 0.0]):
        texts += list(sc.summarize(_pairs(values))["direction"])
    texts.append(inspect.getsource(sc))
    for text in texts:
        for word in BANNED:
            assert word not in text.lower(), (word, text[:80])
    assert "do not show that either policy is superior" in result["note"]
    assert result["summary"]["direction"].eq("single run: direction not assessed").all()
