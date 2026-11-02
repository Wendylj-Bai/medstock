"""
events.py: Things that go wrong in a real supply chain: product recalls and vendor disruptions.

RECALL (a manufacturer or the FDA recalls one lot)
  1. Every unit of the lot still on our shelf is pulled (quarantined) and leaves stock.
     It is a loss, NOT demand, so it does not inflate the forecast.
  2. The lot trace shows which wards already received units, so they can check their shelves
     (and, for a Class I recall, patients can be followed up).
  3. Any delivery still on its way with that lot number is refused at the dock.
  4. Usable stock drops at once, so the item may turn 🔴 and get reordered: a recall is a
     sudden, unplanned demand on safety stock.
  FDA recall classes: I = could cause serious harm or death, II = temporary or reversible harm,
  III = unlikely to cause harm (for example a labeling error).

VENDOR DISRUPTION (a vendor cannot supply for a while: plant shutdown, shortage, storm, cyberattack)
  * Orders the vendor receives during the disruption are rejected at acknowledgement.
  * New orders for its items go to each item's BACKUP vendor (higher price, its own lead time).
  * When the disruption ends, ordering goes back to the primary vendor.

All events here are fictional and simulated.
"""

from datetime import timedelta

import numpy as np
import pandas as pd

import db
import purchasing as pu

RECALL_CLASSES = {"I": "Class I: serious harm possible", "II": "Class II: temporary or reversible harm",
                  "III": "Class III: unlikely to cause harm"}
RECALL_REASONS = ["Possible contamination (sterility not assured)", "Wrong concentration on the label",
                  "Particles found in vials", "Packaging seal defect", "Device may fail during use",
                  "Mislabeled expiry date"]
OUTAGE_REASONS = ["Manufacturing plant shutdown", "Raw material shortage", "Severe weather closed the warehouse",
                  "Cyberattack: order system offline", "Port congestion", "FDA inspection hold"]


# ---------------------------------------------------------------------------
# Recalls
# ---------------------------------------------------------------------------

def recall_lot(conn, lot_no, recall_class="II", reason="", on_date=None, origin="Manual"):
    """Pull every unit of lot_no off the shelf. Returns a summary dict."""
    lot_no = (lot_no or "").strip()
    if not lot_no:
        raise db.StockError("Lot number is required")
    if recall_class not in RECALL_CLASSES:
        raise db.StockError(f"Unknown recall class {recall_class}")
    on_date = db._check_date(conn, on_date or db.today(conn))
    with db.atomic(conn):
        if db.is_recalled(conn, lot_no):
            raise db.StockError(f"Lot {lot_no} is already under recall")
        lots = conn.execute("SELECT l.*, i.unit_cost, i.name FROM lots l JOIN items i USING (item_id) "
                            "WHERE l.lot_no = ?", (lot_no,)).fetchall()
        incoming = conn.execute("SELECT item_id FROM purchase_orders WHERE asn_lot_no = ? AND status = 'OPEN'",
                                (lot_no,)).fetchall()
        if not lots and not incoming:
            raise db.StockError(f"Lot {lot_no} is not in stock and not on its way")
        item_id = (lots[0] if lots else incoming[0])["item_id"]
        removed = value = 0
        for lot in lots:
            if lot["qty"] > 0:
                conn.execute("UPDATE lots SET qty = 0 WHERE lot_id = ?", (lot["lot_id"],))
                db._ledger(conn, on_date, lot["item_id"], "RECALL", -lot["qty"], f"Recall class {recall_class}",
                           f"Lot {lot_no} pulled from the shelf: {reason}".strip(), [(lot["lot_id"], -lot["qty"])])
                removed += lot["qty"]
                value += lot["qty"] * lot["unit_cost"]
        conn.execute("INSERT INTO recalls (date, item_id, lot_no, recall_class, reason, origin, qty_removed, "
                     "value_removed) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     (on_date.isoformat(), item_id, lot_no, recall_class, reason, origin, removed, value))
    return {"lot_no": lot_no, "item_id": item_id, "removed": removed, "value": value,
            "incoming_lines": len(incoming), "wards": wards_that_received(conn, lot_no)}


def wards_that_received(conn, lot_no):
    """{ward: units} that were issued from this lot before the recall."""
    trace = db.lot_trace(conn, lot_no)
    issued = trace[trace["type"] == "ISSUE"]
    return issued.groupby("ward_or_reference")["qty"].sum().abs().astype(int).to_dict() if len(issued) else {}


def recalls(conn):
    r = pd.read_sql("SELECT r.*, i.name, i.ved, i.unit FROM recalls r JOIN items i USING (item_id) "
                    "ORDER BY r.recall_id DESC", conn)
    r["wards"] = [", ".join(f"{w} ({q})" for w, q in wards_that_received(conn, lot).items()) or "none"
                  for lot in r["lot_no"]]
    return r


def random_recall(conn, rng=None, on_date=None):
    """A fictional manufacturer notice for a random lot that is on the shelf. Returns the summary or None."""
    rng = rng or np.random.default_rng()
    on_date = on_date or db.today(conn)
    candidates = conn.execute(
        "SELECT DISTINCT lot_no FROM lots WHERE qty > 0 AND received_date <= ? AND expiry_date > ? "
        "AND lot_no NOT IN (SELECT lot_no FROM recalls)", (on_date.isoformat(), on_date.isoformat())).fetchall()
    if not candidates:
        return None
    lot_no = candidates[rng.integers(len(candidates))][0]
    cls = str(rng.choice(list(RECALL_CLASSES), p=[0.2, 0.65, 0.15]))
    return recall_lot(conn, lot_no, cls, str(rng.choice(RECALL_REASONS)), on_date, origin="Simulated notice")


# ---------------------------------------------------------------------------
# Vendor disruptions
# ---------------------------------------------------------------------------

def start_outage(conn, supplier, days, reason="", on_date=None, origin="Manual"):
    if supplier not in pu.VENDORS:
        raise db.StockError(f"Unknown vendor {supplier}")
    if int(days) != days or days < 1:
        raise db.StockError("The disruption must last at least one day")
    on_date = on_date or db.today(conn)
    if pu.active_outage(conn, supplier, on_date):
        raise db.StockError(f"{supplier} is already disrupted")
    end = on_date + timedelta(days=int(days) - 1)
    with db.atomic(conn):
        conn.execute("INSERT INTO vendor_outages (supplier, start_date, end_date, reason, origin) VALUES (?, ?, ?, ?, ?)",
                     (supplier, on_date.isoformat(), end.isoformat(), reason, origin))
    return end


def end_outage(conn, supplier, on_date=None):
    """The vendor is back: the disruption ends yesterday, so it can supply from today."""
    on_date = on_date or db.today(conn)
    o = pu.active_outage(conn, supplier, on_date)
    if not o:
        raise db.StockError(f"{supplier} is not disrupted")
    with db.atomic(conn):
        conn.execute("UPDATE vendor_outages SET end_date = ? WHERE outage_id = ?",
                     ((on_date - timedelta(days=1)).isoformat(), o["outage_id"]))


def outages(conn, today):
    o = pd.read_sql("SELECT * FROM vendor_outages ORDER BY start_date DESC", conn)
    t = today.isoformat()
    o["state"] = np.where(o["start_date"] > t, "Planned", np.where(o["end_date"] >= t, "🔴 Active", "Ended"))
    o["days"] = (pd.to_datetime(o["end_date"]) - pd.to_datetime(o["start_date"])).dt.days + 1
    return o


def random_outage(conn, rng=None, on_date=None):
    """A random vendor that is not disrupted becomes unable to supply for 1 to 4 weeks."""
    rng = rng or np.random.default_rng()
    on_date = on_date or db.today(conn)
    up = [v for v in pu.VENDORS if not pu.active_outage(conn, v, on_date)]
    if not up:
        return None
    supplier = str(rng.choice(up))
    days = int(rng.integers(7, 29))
    start_outage(conn, supplier, days, str(rng.choice(OUTAGE_REASONS)), on_date, origin="Simulated")
    return {"supplier": supplier, "days": days}
