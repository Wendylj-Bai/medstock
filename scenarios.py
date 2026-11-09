"""
scenarios.py: Run the same simulated period under two inventory policies and compare the results.

Policy A is the default service levels (Vital 99%, Essential 95%, Desirable 90%). Policy B changes the
Vital service level only. Both runs start from the same frozen baseline and meet the same conditions:

  baseline   the project's synthetic sample data (data/*.csv), loaded into an in-memory database with the
             clock set to the day after the last sample usage date. It never opens data/medstock.db or
             any other database file, so it cannot change your data or the live demo.
  demand     one seed drives the daily demand and the ward of each request (simulation.advance). With
             random events off, both runs get exactly the same requests.
  vendors    purchasing.PairedVendorDraws: lead time is keyed by vendor and sent date, backorders, expiry
             and lots by vendor, item and sent date. Same vendor, same item, same day: same outcome.
  events     random recalls and vendor outages are off.

Every pair is checked: if the demand or the shared vendor outcomes differ, the pair is marked not
comparable and its differences are withheld. Differences are B minus A. With several runs (seeds seed,
seed+1, ...) the summary gives the mean, minimum and maximum difference and whether every run moved in the
same direction. The engine never ranks the policies: a simulated result is not proof that one is superior.
"""

import hashlib
import sqlite3
import time
from datetime import timedelta

import pandas as pd

import db
import forecasting as fc
import kpis
import purchasing as pu
import simulation as sim

POLICY_A = {"V": 0.99, "E": 0.95, "D": 0.90}
VITAL_MIN, VITAL_MAX = 0.80, 0.999
DAYS_MIN, DAYS_MAX, DEFAULT_DAYS = 7, 60, 60
DEFAULT_VITAL_B = 0.95
MAX_REPLICATIONS = 5
EARLY_DAYS = 14                    # stockouts are also reported for days 1-14 and day 15 to the end
SEED_MAX = 2**32 - 1
FORECAST_METHOD = "Auto"
AUTO_MODE = sim.AUTO_MODES[2]      # policy only acts through automatic reordering, so orders are sent
BASELINE_TABLES = ["items", "usage", "deliveries", "lots"]
NUMBER_WORDS = {2: "two", 3: "three", 4: "four", 5: "five"}

# (key, label, unit). Differences use the same unit.
METRICS = [
    ("fill_rate", "Fill rate, all items", "fraction of units"),
    ("vital_fill_rate", "Fill rate, Vital items", "fraction of units"),
    ("vital_stockout_days", "Vital stockout item-days", "item-days"),
    ("vital_stockout_days_early", f"Vital stockout item-days, days 1-{EARLY_DAYS}", "item-days"),
    ("vital_stockout_days_late", f"Vital stockout item-days, day {EARLY_DAYS + 1} to end", "item-days"),
    ("vital_units_short", "Vital units short", "units"),
    ("vital_units_short_early", f"Vital units short, days 1-{EARLY_DAYS}", "units"),
    ("vital_units_short_late", f"Vital units short, day {EARLY_DAYS + 1} to end", "units"),
    ("average_book_inventory", "Average book inventory value", "USD"),
    ("usable_ending_inventory", "Usable ending inventory value", "USD"),
    ("book_ending_inventory", "Total ending book inventory value", "USD"),
    ("newly_expired_on_hand", "Stock that expired during the period, still on hand", "USD"),
    ("newly_expired_baseline", "  of which was on hand at the start", "USD"),
    ("newly_expired_received", "  of which was received during the period", "USD"),
    ("expired_before_on_hand", "Stock already expired at the start, still on hand", "USD"),
    ("recorded_losses", "Recorded write-off and recall value", "USD"),
    ("purchases_received", "Purchases received (PO line price)", "USD"),
    ("committed_not_received", "Ordered, not yet received", "USD"),
    ("freight_on_orders_sent", "Freight on orders sent", "USD"),
    ("orders_sent", "Purchase orders sent", "orders"),
]


# ---------------------------------------------------------------------------
# The frozen baseline
# ---------------------------------------------------------------------------

def baseline_fingerprint(folder=db.DATA):
    """sha256 of the sample CSVs the baseline is built from (recorded with every result)."""
    h = hashlib.sha256()
    for t in BASELINE_TABLES:
        h.update((folder / f"{t}.csv").read_bytes())
    return h.hexdigest()


def _memory_db():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def build_baseline(folder=db.DATA):
    """The synthetic sample data in a new in-memory database, clock set to the day after the last
    usage date. Reads the CSVs only."""
    conn = _memory_db()
    conn.executescript(db.SCHEMA)
    db._migrate(conn)
    db.import_csvs(conn, folder)
    last = conn.execute("SELECT MAX(date) FROM usage").fetchone()[0]
    db.set_today(conn, pd.Timestamp(last).date() + timedelta(days=1))
    _check_no_drafts(conn, "The scenario baseline")
    return conn


def _check_no_drafts(conn, where):
    n = conn.execute("SELECT COUNT(*) FROM purchase_orders WHERE status = 'DRAFT'").fetchone()[0]
    if n:
        raise db.StockError(f"{where} has {n} draft purchase order lines; drafts would block replenishment")


def _copy(conn):
    out = _memory_db()
    conn.backup(out)
    return out


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

def _is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def validate(vital_b, days, seed, replications):
    if isinstance(vital_b, bool) or not isinstance(vital_b, (int, float)):
        raise db.StockError("The Vital service level for policy B must be a number")
    if not VITAL_MIN <= vital_b <= VITAL_MAX:
        raise db.StockError(f"The Vital service level for policy B must be between {VITAL_MIN:.0%} and {VITAL_MAX:.1%}")
    if abs(vital_b - POLICY_A["V"]) < 1e-9:
        raise db.StockError("Policy B must use a different Vital service level from policy A (99%)")
    if not _is_int(days) or not DAYS_MIN <= days <= DAYS_MAX:
        raise db.StockError(f"The period must be a whole number of days from {DAYS_MIN} to {DAYS_MAX}")
    if not _is_int(replications) or not 1 <= replications <= MAX_REPLICATIONS:
        raise db.StockError(f"Runs must be a whole number from 1 to {MAX_REPLICATIONS}")
    if not _is_int(seed) or seed < 0 or seed + replications - 1 > SEED_MAX:
        raise db.StockError(f"The seed must be a whole number from 0 to {SEED_MAX - replications + 1}")


# ---------------------------------------------------------------------------
# One run and its measures
# ---------------------------------------------------------------------------

def measures(conn, start, end):
    """Every measure in METRICS for the period after `start` up to and including `end`."""
    first = start + timedelta(days=1)
    k = kpis.compute(conn, first, end)
    so = pd.read_sql("SELECT s.date, s.item_id, s.qty_short FROM stockouts s JOIN items i USING (item_id) "
                     "WHERE i.ved = 'V' AND s.date BETWEEN ? AND ?", conn,
                     params=(first.isoformat(), end.isoformat()), parse_dates=["date"])
    day_no = (so["date"] - pd.Timestamp(start)).dt.days
    early = so[day_no <= EARLY_DAYS]
    late = so[day_no > EARLY_DAYS]
    item_days = lambda df: int(df[["date", "item_id"]].drop_duplicates().shape[0])
    inv = kpis.ending_inventory(conn, first, end)
    return {
        "fill_rate": k["fill_rate"],
        "vital_fill_rate": k["fill_by_ved"]["V"],
        "vital_stockout_days": item_days(so),
        "vital_stockout_days_early": item_days(early),
        "vital_stockout_days_late": item_days(late),
        "vital_units_short": int(so["qty_short"].sum()),
        "vital_units_short_early": int(early["qty_short"].sum()),
        "vital_units_short_late": int(late["qty_short"].sum()),
        "average_book_inventory": k["avg_inventory"],
        "usable_ending_inventory": inv["usable"],
        "book_ending_inventory": inv["book"],
        "newly_expired_on_hand": inv["newly_expired"],
        "newly_expired_baseline": inv["newly_expired_baseline"],
        "newly_expired_received": inv["newly_expired_received"],
        "expired_before_on_hand": inv["expired_before"],
        "recorded_losses": kpis.recorded_losses(conn, first, end)["total"],
        "purchases_received": kpis.purchases_received(conn, first, end)["value"],
        "committed_not_received": kpis.committed_open(conn, end),
        "freight_on_orders_sent": kpis.freight_on_orders_sent(conn, first, end),
        "orders_sent": int(conn.execute("SELECT COUNT(*) FROM po_headers WHERE sent_date BETWEEN ? AND ?",
                                        (first.isoformat(), end.isoformat())).fetchone()[0]),
    }


def _evidence(conn, start):
    """What the pairing check compares: the demand requests and the vendor outcomes of every order."""
    s = start.isoformat()
    requests = pd.read_sql("SELECT date, item_id, ward, requested FROM demand_requests WHERE date > ? "
                           "ORDER BY date, item_id, ward, requested", conn, params=(s,))
    headers = pd.read_sql("SELECT supplier, sent_date, ack_date, ship_date, arrive_date, tracking_no FROM po_headers "
                          "WHERE sent_date > ? ORDER BY supplier, sent_date", conn, params=(s,))
    lines = pd.read_sql("SELECT p.po_id, h.supplier, p.item_id, h.sent_date, p.qty, p.confirmed_qty FROM purchase_orders p "
                        "JOIN po_headers h USING (order_no) WHERE h.sent_date > ?", conn, params=(s,))
    asn = pd.read_sql("SELECT po_id, seq, lot_no, expiry_date, qty FROM asn_lots ORDER BY po_id, seq", conn)
    lots = {p: tuple(zip(g["lot_no"], g["expiry_date"], g["qty"])) for p, g in asn.groupby("po_id")}
    lines["lots"] = [lots.get(p, ()) for p in lines["po_id"]]
    return {"requests": requests, "headers": headers, "lines": lines.drop(columns="po_id")}


OPERATIONAL_TABLES = ["po_headers", "purchase_orders", "asn_lots", "lots", "deliveries", "transactions",
                      "transaction_lots", "usage", "stockouts", "demand_requests"]


def operational_fingerprint(conn, tables=OPERATIONAL_TABLES):
    """sha256 of every row of the tables a run writes. transactions.created_at (the wall-clock time a row
    was written) is left out, so two identical runs give the same fingerprint."""
    h = hashlib.sha256()
    for t in tables:
        cols = ", ".join(r[1] for r in conn.execute(f"PRAGMA table_info({t})") if r[1] != "created_at")
        h.update(t.encode())
        for row in sorted(repr(tuple(r)) for r in conn.execute(f"SELECT {cols} FROM {t}")):
            h.update(row.encode())
    return h.hexdigest()


def run_one(baseline, service_levels, days, seed):
    """Simulate one policy on a private copy of the baseline. Returns measures, evidence and timing."""
    conn = _copy(baseline)
    try:
        _check_no_drafts(conn, "The scenario baseline")
        start = db.today(conn)
        draws = pu.PairedVendorDraws(seed)
        t0 = time.perf_counter()
        report = sim.advance(conn, days, dict(service_levels), FORECAST_METHOD, dict(fc.DEFAULT_PARAMS),
                             AUTO_MODE, auto_receive=True, seed=seed, random_events=False, vendor_draws=draws)
        seconds = time.perf_counter() - t0
        _check_no_drafts(conn, "A scenario run")
        end = report["end"]
        return {"start": start, "end": end, "seed": seed, "seconds": seconds,
                "measures": measures(conn, start, end), "evidence": _evidence(conn, start),
                "draw_keys": list(draws.keys), "fingerprint": operational_fingerprint(conn)}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Pairing check
# ---------------------------------------------------------------------------

def pairing_report(a, b):
    """Proof that A and B met the same demand and, wherever they ordered alike, the same vendor outcomes.

    header pairs: orders to the same vendor on the same day; lead time, ship dates and tracking number
                  must be identical
    line pairs:   the same item from the same vendor on the same day; the vendor's first lot (lot number
                  and expiry) must appear in both, and when both ordered the same quantity the whole line
                  (confirmed quantity and every lot) must be identical
    coverage:     share of B's order lines that have a matching line in A (orders placed on different days
                  get independent draws, which is a real consequence of the policy)
    """
    ea, eb = a["evidence"], b["evidence"]
    demand_identical = ea["requests"].equals(eb["requests"])

    hk = ["supplier", "sent_date"]
    h = ea["headers"].merge(eb["headers"], on=hk, suffixes=("_a", "_b"))
    cols = ["ack_date", "ship_date", "arrive_date", "tracking_no"]
    header_same = int((h[[f"{c}_a" for c in cols]].to_numpy() == h[[f"{c}_b" for c in cols]].to_numpy())
                      .all(axis=1).sum()) if len(h) else 0

    lk = ["supplier", "item_id", "sent_date"]
    m = ea["lines"].merge(eb["lines"], on=lk, suffixes=("_a", "_b"))
    lot_ids = lambda lots: {(lot_no, expiry) for lot_no, expiry, _ in lots}      # quantities may differ
    shared_lot = sum(bool(lot_ids(x) & lot_ids(y)) or (not x and not y) for x, y in zip(m["lots_a"], m["lots_b"]))
    same_qty = m[m["qty_a"] == m["qty_b"]]
    same_qty_identical = int(((same_qty["confirmed_qty_a"] == same_qty["confirmed_qty_b"])
                              & (same_qty["lots_a"] == same_qty["lots_b"])).sum())
    vendor_paired = header_same == len(h) and shared_lot == len(m) and same_qty_identical == len(same_qty)
    return {
        "demand_identical": demand_identical,
        "header_pairs": len(h), "header_pairs_identical": header_same,
        "line_pairs": len(m), "line_pairs_sharing_first_lot": shared_lot,
        "line_pairs_same_qty": len(same_qty), "line_pairs_same_qty_identical": same_qty_identical,
        "line_coverage": len(m) / len(eb["lines"]) if len(eb["lines"]) else None,
        "vendor_paired": vendor_paired,
        "comparable": demand_identical and vendor_paired,
    }


# ---------------------------------------------------------------------------
# Comparison and summary
# ---------------------------------------------------------------------------

def _diff(a, b):
    return None if a is None or b is None else b - a


def direction_label(diffs):
    """Neutral wording for several runs. Never ranks the policies."""
    n = len(diffs)
    if n < 2:
        return "single run: direction not assessed"
    if any(d is None for d in diffs):
        return "not assessed: a run was not comparable"
    words = NUMBER_WORDS.get(n, str(n))
    if all(d > 0 for d in diffs):
        return f"same direction in all {words} runs: B higher than A"
    if all(d < 0 for d in diffs):
        return f"same direction in all {words} runs: B lower than A"
    if all(d == 0 for d in diffs):
        return f"no difference in all {words} runs"
    return "mixed direction across runs"


def summarize(pairs):
    """Per measure: mean, minimum and maximum of B minus A over the comparable runs, and the direction label."""
    rows = []
    for key, label, unit in METRICS:
        diffs = [p["diff"][key] if p["pairing"]["comparable"] else None for p in pairs]
        vals = [d for d in diffs if d is not None]
        rows.append({"measure": key, "label": label, "unit": unit, "runs": len(pairs), "comparable_runs": len(vals),
                     "mean_diff": sum(vals) / len(vals) if vals else None,
                     "min_diff": min(vals) if vals else None, "max_diff": max(vals) if vals else None,
                     "direction": direction_label(diffs)})
    return pd.DataFrame(rows)


NOTE = ("Differences are policy B minus policy A in simulated runs on synthetic data. They describe what "
        "happened in these runs and do not show that either policy is superior.")


def compare(vital_b=DEFAULT_VITAL_B, days=DEFAULT_DAYS, seed=None, replications=1):
    """Run policy A and policy B on the frozen baseline, `replications` times (seeds seed, seed+1, ...).

    Returns {"inputs", "pairs", "summary", "note"}. Each pair holds the A and B measures, the
    differences (None when the pair is not comparable), the pairing report and the run times.
    Nothing is saved anywhere: every database used here lives in memory and is closed before returning.
    """
    baseline = build_baseline()
    try:
        start = db.today(baseline)
        seed = start.toordinal() if seed is None else seed
        validate(vital_b, days, seed, replications)
        policy_b = {**POLICY_A, "V": float(vital_b)}
        pairs = []
        for k in range(replications):
            s = seed + k
            a = run_one(baseline, POLICY_A, days, s)
            b = run_one(baseline, policy_b, days, s)
            pairing = pairing_report(a, b)
            diff = {key: _diff(a["measures"][key], b["measures"][key]) if pairing["comparable"] else None
                    for key, _, _ in METRICS}
            pairs.append({"seed": s, "a": a["measures"], "b": b["measures"], "diff": diff, "pairing": pairing,
                          "seconds": {"a": a["seconds"], "b": b["seconds"]}, "end": a["end"],
                          "fingerprints": {"a": a["fingerprint"], "b": b["fingerprint"]}})
    finally:
        baseline.close()
    inputs = {"policy_a": dict(POLICY_A), "policy_b": policy_b, "days": days, "seeds": [p["seed"] for p in pairs],
              "baseline_start": start, "baseline_fingerprint": baseline_fingerprint(),
              "forecast_method": FORECAST_METHOD, "forecast_params": dict(fc.DEFAULT_PARAMS),
              "auto_mode": AUTO_MODE, "random_events": False}
    return {"inputs": inputs, "pairs": pairs, "summary": summarize(pairs), "note": NOTE}
