"""
purchasing.py: Purchase orders sent to vendors, and how (simulated) vendors respond.

How it works in a real hospital (and here):
  1. The system finds what to order (the reorder plan) and pre-fills a DRAFT purchase order
     for each vendor: one PO per vendor, one LINE per item, quantities and prices filled in.
  2. A buyer reviews the draft and approves it. It is then SENT to the vendor
     (in real life usually electronically: an "EDI 850" message).
  3. The vendor ACKNOWLEDGES it (EDI 855) and confirms what it can supply.
     Sometimes it cannot supply everything (a vendor backorder).
  4. The vendor SHIPS it and sends an advance ship notice, ASN (EDI 856), with the carrier,
     tracking number, and the lot numbers and expiry dates in the boxes.
  5. The truck ARRIVES at the receiving dock and the storeroom RECEIVES it. The real lead
     time is saved, so future reorder points use it.

All vendors and their behaviour are FICTIONAL. Each vendor's real lead time is random:
on average L days with standard deviation σL, exactly the kind of lead-time uncertainty
that the safety stock formula (slides 197-204) protects against.
"""

import html
import zlib
from datetime import date, timedelta

import numpy as np
import pandas as pd

import db

# Fictional ship-to address of the fictional hospital
HOSPITAL = {
    "name": "MedStock Demo Hospital (fictional)",
    "dept": "Central Supply / Materials Management",
    "address": "1200 Example Avenue, Receiving Dock B, Portland, OR 97203",
}

# Vendor master (all fictional). L / sL = real lead time in days (mean, std. dev.), the same
# values used to create the sample history. quoted_days = what the vendor promises.
VENDORS = {
    "Northwest Medical Distributors": {
        "code": "NWMD", "account_no": "MS-10442", "contact": "Dana Reyes (fictional)",
        "email": "orders@nwmd.example", "phone": "(503) 555-0142",
        "address": "8800 Example Industrial Way, Portland, OR 97230",
        "method": "EDI", "terms": "Net 30", "ship_via": "Vendor truck (next-day route)",
        "min_order": 100, "free_freight_over": 250, "freight_fee": 15,
        "quoted_days": 2, "L": 2, "sL": 0.6, "ack_days": 0, "transit_days": 1, "short_prob": 0.03,
    },
    "Pacific Pharma Supply": {
        "code": "PPS", "account_no": "PPS-883120", "contact": "Sam Okafor (fictional)",
        "email": "customerservice@pacificpharma.example", "phone": "(206) 555-0187",
        "address": "410 Example Harbor Rd, Kent, WA 98032",
        "method": "EDI", "terms": "Net 30", "ship_via": "Ground parcel, temperature-controlled",
        "min_order": 200, "free_freight_over": 500, "freight_fee": 25,
        "quoted_days": 4, "L": 4, "sL": 1.2, "ack_days": 0, "transit_days": 2, "short_prob": 0.06,
    },
    "Cascade Surgical Supply": {
        "code": "CSS", "account_no": "C-55219", "contact": "Jordan Lee (fictional)",
        "email": "po@cascadesurgical.example", "phone": "(541) 555-0123",
        "address": "77 Example Commerce Dr, Eugene, OR 97402",
        "method": "Email", "terms": "2/10 Net 30", "ship_via": "LTL freight",
        "min_order": 150, "free_freight_over": 1000, "freight_fee": 40,
        "quoted_days": 7, "L": 7, "sL": 2.5, "ack_days": 1, "transit_days": 3, "short_prob": 0.08,
    },
    "Overseas Medical Imports": {
        "code": "OMI", "account_no": "OMI-2207", "contact": "Alex Chen (fictional)",
        "email": "export-orders@omi.example", "phone": "(562) 555-0199",
        "address": "3000 Example Port Blvd, Long Beach, CA 90802",
        "method": "Web portal", "terms": "Net 45", "ship_via": "Ocean freight + truck",
        "min_order": 500, "free_freight_over": 5000, "freight_fee": 150,
        "quoted_days": 21, "L": 21, "sL": 7.0, "ack_days": 2, "transit_days": 14, "short_prob": 0.12,
    },
}

# A backup (second-source) vendor charges more than the contract price of the primary vendor
BACKUP_PREMIUM = 0.12

STAGES = ["DRAFT", "SENT", "CONFIRMED", "SHIPPED", "ARRIVED", "RECEIVED"]
STAGE_LABELS = {
    "DRAFT": "Draft (awaiting approval)", "SENT": "Sent to vendor", "CONFIRMED": "Confirmed by vendor",
    "SHIPPED": "Shipped", "ARRIVED": "Arrived at dock", "RECEIVED": "Received",
    "CANCELLED": "Cancelled",
}


def _d(value):
    """ISO text from the database -> date (or None)."""
    return date.fromisoformat(value) if value else None


def _rng(order_no):
    """Each order gets its own fixed random numbers, so its story never changes after a reload."""
    return np.random.default_rng(zlib.crc32(order_no.encode()))


SPLIT_LOT_CHANCE = 0.3     # share of shipped lines that arrive as 2-3 lots from different production runs


def _lot_split_rng(order_no, line_no):
    return np.random.default_rng(zlib.crc32(f"{order_no}/{line_no}/lots".encode()))


class OrderNumberDraws:
    """The normal vendor behavior: every random choice for an order comes from one generator seeded by
    the order number (header first, then each line in order), and each line's lot split from its own
    generator. send_order uses this unless it is given other draws."""

    def __init__(self, order_no):
        self.order_no = order_no
        self.rng = _rng(order_no)

    def header(self, supplier, on_date):
        return self.rng

    def line(self, supplier, item_id, on_date):
        return self.rng                      # the same stream, so the draws keep their original order

    def lots(self, supplier, item_id, on_date, line_no):
        return _lot_split_rng(self.order_no, line_no)


class PairedVendorDraws:
    """Vendor behavior for scenario comparison only (scenarios.py). Each draw is keyed by business facts
    instead of the order number:
        header (lead time, tracking number)          seed, vendor, sent date
        line (backorder, expiry, lot number)         seed, vendor, item, sent date
        lot split                                    seed, vendor, item, sent date
    So when two policies send the same vendor an order on the same day, the truck arrives on the same day,
    and the same item from that vendor that day gets the same backorder and expiry draws. A key used twice
    in one run raises an error, so that guarantee can never break silently. `keys` lists every key used."""

    HEADER, LINE, LOTS = 0, 1, 2

    def __init__(self, seed):
        self.seed = int(seed)
        self.keys = []
        self._used = set()

    def _rng(self, purpose, supplier, on_date, item_id=""):
        key = (purpose, supplier, on_date.isoformat(), item_id)
        if key in self._used:
            raise db.StockError(f"Scenario vendor draw used twice: {key}")
        self._used.add(key)
        self.keys.append(key)
        return np.random.default_rng([self.seed, zlib.crc32(supplier.encode()), on_date.toordinal(),
                                      zlib.crc32(item_id.encode()), purpose])

    def header(self, supplier, on_date):
        return self._rng(self.HEADER, supplier, on_date)

    def line(self, supplier, item_id, on_date):
        return self._rng(self.LINE, supplier, on_date, item_id)

    def lots(self, supplier, item_id, on_date, line_no):
        return self._rng(self.LOTS, supplier, on_date, item_id)


def _split_lots(order_no, line_no, qty, lot_no, expiry, arrive, vendor_code, rng=None):
    """How a shipped line is packed: usually one lot, sometimes two or three with different
    expiry dates. Uses its own random stream, so it never changes the vendor's other choices."""
    rng = rng if rng is not None else _lot_split_rng(order_no, line_no)
    if qty < 10 or rng.random() >= SPLIT_LOT_CHANCE:
        return [(lot_no, expiry, int(qty))]
    k = 2 if qty < 40 or rng.random() < 0.7 else 3
    shares = rng.dirichlet(np.ones(k) * 4)
    parts = np.maximum(1, np.floor(shares * qty)).astype(int)
    parts[0] += int(qty) - int(parts.sum())                   # make the parts add up exactly
    lots = [(lot_no, expiry, int(parts[0]))]
    for q in parts[1:]:
        older = expiry - timedelta(days=int(rng.integers(20, 120)))  # an older production run
        lots.append((f"{vendor_code[:2]}{arrive:%y}{rng.integers(10000, 99999)}",
                     max(older, arrive + timedelta(days=14)), int(q)))
    return sorted(lots, key=lambda l: l[1])                    # earliest expiry first


def _next_order_no(conn, on_date):
    prefix = f"P{on_date:%y}-"
    nums = [int(r[0][len(prefix):]) for r in conn.execute(
        "SELECT order_no FROM po_headers WHERE order_no LIKE ?", (prefix + "%",)) if r[0][len(prefix):].isdigit()]
    return f"{prefix}{max(nums, default=0) + 1:04d}"


def freight(supplier, subtotal):
    v = VENDORS.get(supplier)
    if v is None or subtotal >= v["free_freight_over"]:
        return 0.0
    return float(v["freight_fee"])


# ---------------------------------------------------------------------------
# Vendor disruptions and backup vendors
# ---------------------------------------------------------------------------

def active_outage(conn, supplier, on_date):
    """The vendor's current supply disruption (dict), or None if it can supply on that date."""
    row = conn.execute("SELECT * FROM vendor_outages WHERE supplier = ? AND start_date <= ? AND end_date >= ? "
                       "ORDER BY start_date DESC LIMIT 1", (supplier, on_date.isoformat(), on_date.isoformat())
                       ).fetchone()
    return dict(row) if row else None


def unit_price(item, supplier):
    """Contract price from the primary vendor; the backup vendor charges a premium."""
    price = float(item["unit_cost"])
    return round(price * (1 + BACKUP_PREMIUM), 2) if supplier != item["supplier"] else price


def order_vendors(conn, plan, on_date=None):
    """Which vendor to order each item from today: the primary, unless it is disrupted and the backup is not.
    Returns a DataFrame indexed like plan with columns order_vendor and vendor_reason."""
    on_date = on_date or db.today(conn)
    down = {v for v in VENDORS if active_outage(conn, v, on_date)}
    rows = []
    for r in plan.itertuples():
        backup = getattr(r, "backup_supplier", None)
        if r.supplier in down and backup and backup not in down:
            rows.append((backup, f"{r.supplier} cannot supply; using backup vendor (+{BACKUP_PREMIUM:.0%} price)"))
        elif r.supplier in down:
            rows.append((r.supplier, f"{r.supplier} cannot supply and the backup is also disrupted"))
        else:
            rows.append((r.supplier, ""))
    return pd.DataFrame(rows, index=plan.index, columns=["order_vendor", "vendor_reason"])


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def stage(header, today):
    """Where the order is today. Vendor events happen on their dates, so the status follows the clock."""
    status = header["status"]
    if status in ("DRAFT", "RECEIVED", "CANCELLED"):
        return status
    today = today.isoformat()
    if today < header["ack_date"]:
        return "SENT"
    if header.get("vendor_note"):          # vendor rejected the whole order (supply disruption)
        return "CANCELLED"
    if today < header["ship_date"]:
        return "CONFIRMED"
    if today < header["arrive_date"]:
        return "SHIPPED"
    return "ARRIVED"


def orders(conn, today):
    """All purchase orders with their current stage, value and dates."""
    h = pd.read_sql("SELECT * FROM po_headers ORDER BY order_no DESC", conn)
    lines = pd.read_sql("SELECT order_no, COUNT(*) AS lines, SUM(qty * unit_cost) AS subtotal "
                        "FROM purchase_orders WHERE order_no IS NOT NULL GROUP BY order_no", conn)
    h = h.merge(lines, on="order_no", how="left").fillna({"lines": 0, "subtotal": 0.0})
    h["stage"] = [stage(r, today) for r in h.to_dict("records")]
    h["total"] = h["subtotal"] + h["freight"].fillna(0)
    # Late = past the promised date and not yet at the dock
    h["late"] = (h["stage"].isin(["SENT", "CONFIRMED", "SHIPPED"])
                 & (h["promised_date"].fillna("9999") < today.isoformat()))
    return h


def order_header(conn, order_no):
    row = conn.execute("SELECT * FROM po_headers WHERE order_no = ?", (order_no,)).fetchone()
    if row is None:
        raise db.StockError(f"Unknown purchase order {order_no}")
    return dict(row)


def order_lines(conn, order_no):
    return pd.read_sql(
        "SELECT p.line_no, p.po_id, p.item_id, i.name, i.unit, p.qty, p.confirmed_qty, p.unit_cost, "
        "       p.qty * p.unit_cost AS amount, p.status, p.received_qty, p.asn_lot_no, p.asn_expiry "
        "FROM purchase_orders p JOIN items i USING (item_id) WHERE p.order_no = ? ORDER BY p.line_no",
        conn, params=(order_no,))


def items_in_drafts(conn):
    """item_id -> order_no for items already sitting in a draft PO (so we don't draft them twice)."""
    return dict(conn.execute("SELECT item_id, order_no FROM purchase_orders WHERE status = 'DRAFT'").fetchall())


# ---------------------------------------------------------------------------
# Creating and editing drafts
# ---------------------------------------------------------------------------

def _insert_lines(conn, order_no, supplier, lines, on_date, need_by):
    lines = [(i, int(q)) for i, q in lines if q and int(q) > 0]
    if not lines:
        raise db.StockError("A purchase order needs at least one line with a quantity above zero")
    for n, (item_id, qty) in enumerate(lines, start=1):
        item = db._get_item(conn, item_id)
        if supplier not in (item["supplier"], item["backup_supplier"]):
            raise db.StockError(f"{item['name']} is not supplied by {supplier}")
        conn.execute(
            "INSERT INTO purchase_orders (po_id, order_no, line_no, item_id, supplier, qty, unit_cost, "
            "order_date, expected_date, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'DRAFT')",
            (db._next_po_id(conn), order_no, n, item_id, supplier, qty, unit_price(item, supplier),
             on_date.isoformat(), need_by.isoformat() if need_by else None))


def create_order(conn, supplier, lines, need_by=None, notes="", origin="Manual", on_date=None):
    """Create a DRAFT purchase order for one vendor. lines = [(item_id, qty), ...]. Returns the PO number."""
    if supplier not in VENDORS:
        raise db.StockError(f"Unknown vendor {supplier}")
    on_date = on_date or db.today(conn)
    with db.atomic(conn):
        order_no = _next_order_no(conn, on_date)
        conn.execute("INSERT INTO po_headers (order_no, supplier, status, origin, created_date, need_by, notes) "
                     "VALUES (?, ?, 'DRAFT', ?, ?, ?, ?)",
                     (order_no, supplier, origin, on_date.isoformat(),
                      need_by.isoformat() if need_by else None, notes))
        _insert_lines(conn, order_no, supplier, lines, on_date, need_by)
    return order_no


def update_draft(conn, order_no, lines, need_by=None, notes=None):
    """Replace the lines of a draft (quantity 0 removes a line)."""
    with db.atomic(conn):
        h = order_header(conn, order_no)
        if h["status"] != "DRAFT":
            raise db.StockError(f"{order_no} was already sent; it can no longer be edited")
        need_by = need_by or _d(h["need_by"])
        conn.execute("DELETE FROM purchase_orders WHERE order_no = ?", (order_no,))
        _insert_lines(conn, order_no, h["supplier"], lines, _d(h["created_date"]), need_by)
        conn.execute("UPDATE po_headers SET need_by = ?, notes = ? WHERE order_no = ?",
                     (need_by.isoformat() if need_by else None,
                      h["notes"] if notes is None else notes, order_no))


def draft_suggested_orders(conn, plan, origin="Dashboard", on_date=None):
    """One draft PO per vendor for every 🔴 item that is not already ordered or drafted.

    Quantities come from the reorder plan (order up to R + Q). Items whose primary vendor is
    disrupted go to their backup vendor. Returns the new PO numbers. Only creates drafts: nothing is
    approved or sent. The check for items already in a draft and the new drafts are one transaction
    (BEGIN IMMEDIATE), so a repeated click, even from a second tab, finds the first click's drafts and
    adds nothing.
    """
    on_date = on_date or db.today(conn)
    with db.atomic(conn):
        drafted = items_in_drafts(conn)
        todo = plan[plan["status"].str.startswith("🔴") & (plan["order_qty"] > 0) & ~plan["item_id"].isin(drafted)]
        if todo.empty:
            return []
        todo = todo.drop(columns=["order_vendor", "vendor_reason"], errors="ignore").join(
            order_vendors(conn, todo, on_date))
        made = []
        for supplier, group in todo.groupby("order_vendor"):
            if active_outage(conn, supplier, on_date):
                continue                 # primary and backup both down: nothing can be ordered right now
            need_by = on_date + timedelta(days=VENDORS[supplier]["quoted_days"])
            note = "Suggested by the MedStock reorder plan"
            if (group["order_vendor"] != group["supplier"]).any():
                note += ". Backup vendor: the primary vendor cannot supply"
            made.append(create_order(conn, supplier, list(zip(group["item_id"], group["order_qty"])),
                                     need_by, note, origin, on_date))
    return made


# ---------------------------------------------------------------------------
# Sending: from here on the (simulated) vendor takes over
# ---------------------------------------------------------------------------

def send_order(conn, order_no, on_date=None, draws=None):
    """Approve and transmit a draft. The vendor's response is decided now (but revealed day by day):

    ack date      = sent + vendor's acknowledgement time
    confirmed qty = ordered, except a random vendor backorder (probability short_prob)
    arrival date  = sent + random lead time ~ Normal(L, σL), at least 1 day
    ship date     = arrival - transit time
    ASN           = carrier, tracking number, lot number and expiry date per line

    draws: where the random numbers come from. Normally None (OrderNumberDraws: seeded by the order
    number). Scenario comparison passes PairedVendorDraws.
    """
    with db.atomic(conn):
        h = order_header(conn, order_no)
        if h["status"] != "DRAFT":
            raise db.StockError(f"{order_no} was already sent")
        on_date = db._check_date(conn, on_date or db.today(conn))
        v = VENDORS[h["supplier"]]
        draws = draws if draws is not None else OrderNumberDraws(order_no)
        rng = draws.header(h["supplier"], on_date)
        lines = order_lines(conn, order_no)
        if lines.empty:
            raise db.StockError(f"{order_no} has no lines")

        ack = on_date + timedelta(days=v["ack_days"])
        lead = max(1, v["ack_days"], int(round(rng.normal(v["L"], v["sL"]))))
        arrive = on_date + timedelta(days=lead)
        ship = max(ack, arrive - timedelta(days=v["transit_days"]))
        promised = on_date + timedelta(days=v["quoted_days"])
        subtotal = float(lines["amount"].sum())
        outage = active_outage(conn, h["supplier"], ack)          # disrupted when it reads the order?
        vendor_note = None
        if outage:
            ship = arrive = ack                                     # nothing will ship
            vendor_note = (f"Vendor cannot supply until {_d(outage['end_date']):%b %d}: {outage['reason']}. "
                           "All lines rejected; order from the backup vendor.")

        conn.execute(
            "UPDATE po_headers SET status = 'SENT', sent_date = ?, ack_date = ?, ship_date = ?, arrive_date = ?, "
            "promised_date = ?, carrier = ?, tracking_no = ?, freight = ?, vendor_note = ? WHERE order_no = ?",
            (on_date.isoformat(), ack.isoformat(), ship.isoformat(), arrive.isoformat(), promised.isoformat(),
             v["ship_via"], f"{v['code']}{rng.integers(10**9, 10**10)}", freight(h["supplier"], subtotal),
             vendor_note, order_no))
        for line in lines.itertuples():
            item = db._get_item(conn, line.item_id)
            rng = draws.line(h["supplier"], line.item_id, on_date)
            confirmed = line.qty
            if outage:
                confirmed = 0
            elif rng.random() < v["short_prob"]:                     # vendor backorder
                confirmed = max(1, int(line.qty * rng.uniform(0.4, 0.9)))
            life = item["shelf_life_days"]
            share = rng.uniform(0.15, 0.35) if rng.random() < 0.08 else rng.uniform(0.6, 0.95)
            expiry = arrive + timedelta(days=max(14, int(life * share)))
            lot_no = f"{v['code'][:2]}{arrive:%y}{rng.integers(10000, 99999)}"
            lots = (_split_lots(order_no, line.line_no, confirmed, lot_no, expiry, arrive, v["code"],
                                draws.lots(h["supplier"], line.item_id, on_date, line.line_no))
                    if confirmed else [])
            if lots:
                lot_no, expiry = lots[0][0], lots[0][1]             # the single-lot columns hold the first lot
            conn.execute(
                "UPDATE purchase_orders SET status = 'OPEN', order_date = ?, expected_date = ?, confirmed_qty = ?, "
                "asn_lot_no = ?, asn_expiry = ? WHERE po_id = ?",
                (on_date.isoformat(), promised.isoformat(), confirmed, lot_no, expiry.isoformat(), line.po_id))
            conn.execute("DELETE FROM asn_lots WHERE po_id = ?", (line.po_id,))
            conn.executemany("INSERT INTO asn_lots (po_id, seq, lot_no, expiry_date, qty) VALUES (?, ?, ?, ?, ?)",
                             [(line.po_id, i, l, e.isoformat(), q) for i, (l, e, q) in enumerate(lots)])
            db._ledger(conn, on_date, line.item_id, "PO SENT", 0, order_no,
                       f"Line {line.line_no}: {line.qty} ordered from {h['supplier']} via {v['method']}")
    return order_no


def process_vendor_responses(conn, today):
    """Close lines the vendor rejected (confirmed 0) once the vendor's acknowledgement has arrived.
    Returns the order numbers that were rejected completely."""
    rows = conn.execute(
        "SELECT p.po_id, p.item_id, p.order_no, h.vendor_note FROM purchase_orders p JOIN po_headers h USING (order_no) "
        "WHERE p.status = 'OPEN' AND p.confirmed_qty = 0 AND h.ack_date <= ?", (today.isoformat(),)).fetchall()
    if not rows:
        return []
    with db.atomic(conn):
        for r in rows:
            conn.execute("UPDATE purchase_orders SET status = 'CANCELLED' WHERE po_id = ?", (r["po_id"],))
            db._ledger(conn, today, r["item_id"], "PO REJECTED", 0, r["order_no"],
                       r["vendor_note"] or "Vendor could not supply this line")
        orders_hit = sorted({r["order_no"] for r in rows})
        for order_no in orders_hit:
            db.close_order_if_done(conn, order_no, today)
    return [o for o in orders_hit if order_header(conn, o)["status"] == "CANCELLED"]


def cancel_order(conn, order_no, note=""):
    """Cancel a whole order. Possible until the vendor ships it."""
    with db.atomic(conn):
        h = order_header(conn, order_no)
        today = db.today(conn)
        st = stage(h, today)
        if st in ("SHIPPED", "ARRIVED"):
            raise db.StockError(f"{order_no} has already shipped. Refuse or return the delivery instead")
        if st in ("RECEIVED", "CANCELLED"):
            raise db.StockError(f"{order_no} is already {st.lower()}")
        for po_id, item_id in conn.execute("SELECT po_id, item_id FROM purchase_orders "
                                           "WHERE order_no = ? AND status IN ('OPEN', 'DRAFT')", (order_no,)).fetchall():
            conn.execute("UPDATE purchase_orders SET status = 'CANCELLED' WHERE po_id = ?", (po_id,))
            if st != "DRAFT":
                db._ledger(conn, today, item_id, "PO CANCELLED", 0, order_no, note)
        conn.execute("UPDATE po_headers SET status = 'CANCELLED', closed_date = ? WHERE order_no = ?",
                     (today.isoformat(), order_no))


def receive_order(conn, order_no, on_date=None):
    """Receive a whole shipment exactly as the ASN says (quantities, lots, expiry dates).

    Returns a list of (item name, qty, lot_no, lead_time). Partially received
    lines are topped up to the confirmed quantity.
    """
    with db.atomic(conn):
        h = order_header(conn, order_no)
        on_date = on_date or db.today(conn)
        if stage(h, on_date) != "ARRIVED":
            raise db.StockError(f"{order_no} is not at the receiving dock (status: {STAGE_LABELS[stage(h, on_date)]})")
        done = []
        for line in order_lines(conn, order_no).itertuples():
            if line.status != "OPEN":
                continue
            expected = line.confirmed_qty if pd.notna(line.confirmed_qty) else line.qty
            received = int(line.received_qty) if pd.notna(line.received_qty) else 0
            qty = int(max(expected - received, 0))
            if qty <= 0:
                conn.execute("UPDATE purchase_orders SET status = 'RECEIVED', received_date = ?, received_qty = ? "
                             "WHERE po_id = ?", (on_date.isoformat(), int(expected), line.po_id))
                db.close_order_if_done(conn, order_no, on_date)
                continue
            lots = db.asn_lots(conn, line.po_id)
            if received or sum(q for _, _, q in lots) != qty:     # topping up a partial receipt: one lot
                lots = [(lots[0][0], lots[0][1], qty)]
            good = [l for l in lots if not db.is_recalled(conn, l[0])]
            for lot_no, _, q in lots:
                if (lot_no, _, q) not in good:                  # refuse a recalled lot at the dock
                    db._ledger(conn, on_date, line.item_id, "REFUSED", 0, order_no,
                               f"Lot {lot_no} is under recall: {q} refused at the dock")
            if good:
                lead = db.receive_lots(conn, line.po_id, good, on_date, "Received per ASN")
                done.extend((line.name, q, lot_no, lead) for lot_no, _, q in good)
            if len(good) < len(lots):                           # what was refused will not come: close the line
                got = conn.execute("SELECT received_qty FROM purchase_orders WHERE po_id = ?",
                                   (line.po_id,)).fetchone()[0] or 0
                conn.execute("UPDATE purchase_orders SET status = ?, received_date = ? WHERE po_id = ?",
                             ("RECEIVED" if got else "CANCELLED", on_date.isoformat(), line.po_id))
                db.close_order_if_done(conn, order_no, on_date)
    return done


# ---------------------------------------------------------------------------
# What the vendor has told us so far (revealed day by day)
# ---------------------------------------------------------------------------

def vendor_messages(conn, order_no, today):
    """The order's story up to today: [(date, message)]."""
    h = order_header(conn, order_no)
    v = VENDORS.get(h["supplier"], {})
    msgs = [(_d(h["created_date"]), f"Draft created ({h['origin'] or 'Manual'})")]
    if h["status"] == "CANCELLED" and h["closed_date"]:
        today = min(today, _d(h["closed_date"]))       # nothing happens after a cancellation
    if h["sent_date"]:
        msgs.append((_d(h["sent_date"]), f"Approved and sent to {h['supplier']} via {v.get('method', '?')}"
                                         f"{' (EDI 850)' if v.get('method') == 'EDI' else ''}. "
                                         f"Vendor promise: delivery by {_d(h['promised_date']):%b %d}"))
        lines = order_lines(conn, order_no)
        if _d(h["ack_date"]) <= today and h.get("vendor_note"):
            msgs.append((_d(h["ack_date"]), "Rejected: " + h["vendor_note"]))
        elif _d(h["ack_date"]) <= today:
            short = lines[lines["confirmed_qty"] < lines["qty"]]
            text = "Vendor acknowledged the order" + (" (EDI 855)" if v.get("method") == "EDI" else "") + ". "
            if short.empty:
                text += "All lines confirmed in full."
            else:
                text += "Vendor backorder: " + "; ".join(
                    f"{r.name}: only {r.confirmed_qty:,} of {r.qty:,}" for r in short.itertuples()) + \
                    ". The rest will not be delivered; reorder it if still needed."
            msgs.append((_d(h["ack_date"]), text))
        if _d(h["ship_date"]) <= today and not h.get("vendor_note"):
            msgs.append((_d(h["ship_date"]), f"Shipped via {h['carrier']}, tracking {h['tracking_no']}. "
                                             f"Advance ship notice (ASN) received with lot numbers and expiry dates. "
                                             f"Carrier ETA {_d(h['arrive_date']):%b %d}"))
        if _d(h["arrive_date"]) <= today and not h.get("vendor_note"):
            late = (_d(h["arrive_date"]) - _d(h["promised_date"])).days
            when = f"{late} day(s) late" if late > 0 else "on time" if late == 0 else f"{-late} day(s) early"
            msgs.append((_d(h["arrive_date"]), f"Delivered to the receiving dock ({when})"))
    if h["status"] in ("RECEIVED", "CANCELLED") and h["closed_date"]:
        msgs.append((_d(h["closed_date"]), "Received into stock" if h["status"] == "RECEIVED" else "Cancelled"))
    return sorted(msgs, key=lambda m: m[0])


# ---------------------------------------------------------------------------
# Vendor performance
# ---------------------------------------------------------------------------

def vendor_scorecard(conn):
    """Lead time and reliability per vendor, from every delivery ever received."""
    d = pd.read_sql("SELECT supplier, lead_time_days FROM deliveries", conn)
    rows = []
    for name, v in VENDORS.items():
        lt = d.loc[d["supplier"] == name, "lead_time_days"]
        fill = conn.execute(
            "SELECT SUM(received_qty), SUM(qty) FROM purchase_orders WHERE supplier = ? AND status = 'RECEIVED' "
            "AND order_no IS NOT NULL", (name,)).fetchone()
        rows.append({
            "vendor": name, "deliveries": len(lt), "quoted_days": v["quoted_days"],
            "avg_lead_time": lt.mean() if len(lt) else None,
            "sd_lead_time": lt.std() if len(lt) > 1 else None,
            "on_time": (lt <= v["quoted_days"]).mean() if len(lt) else None,
            "fill_rate": (fill[0] / fill[1]) if fill[1] else None,
        })
    return pd.DataFrame(rows)


def po_document_html(conn, order_no):
    """A printable purchase order (HTML), like the one a buyer would send or file."""
    h = order_header(conn, order_no)
    v = VENDORS[h["supplier"]]
    lines = order_lines(conn, order_no)
    subtotal = float(lines["amount"].sum())
    fr = h["freight"] if h["freight"] is not None else freight(h["supplier"], subtotal)
    rows = "".join(
        f"<tr><td>{r.line_no}</td><td>{html.escape(r.item_id)}</td><td>{html.escape(r.name)}</td>"
        f"<td>{html.escape(r.unit)}</td>"
        f"<td class=n>{r.qty:,}</td><td class=n>${r.unit_cost:,.2f}</td><td class=n>${r.amount:,.2f}</td></tr>"
        for r in lines.itertuples())
    sent = _d(h["sent_date"])
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Purchase order {order_no}</title>
<style>body{{font-family:Arial,sans-serif;max-width:800px;margin:24px auto;color:#222}}
table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #bbb;padding:6px;font-size:13px}}
th{{background:#eee;text-align:left}}.n{{text-align:right}}.box{{display:inline-block;vertical-align:top;width:48%}}
h1{{margin-bottom:0}}.muted{{color:#666;font-size:12px}}</style></head><body>
<h1>PURCHASE ORDER {order_no}</h1>
<p class=muted>FICTIONAL. Generated by the MedStock learning app, not a real order.</p>
<p>Date: {(sent or _d(h['created_date'])):%B %d, %Y} · Status: {STAGE_LABELS.get(h['status'], h['status'])}
 · Need by: {_d(h['need_by']).strftime('%B %d, %Y') if h['need_by'] else 'n/a'}</p>
<div class=box><b>Vendor</b><br>{h['supplier']}<br>{v['address']}<br>Attn: {v['contact']}<br>
{v['email']} · {v['phone']}<br>Our account no.: {v['account_no']}</div>
<div class=box><b>Ship to / Bill to</b><br>{HOSPITAL['name']}<br>{HOSPITAL['dept']}<br>{HOSPITAL['address']}</div>
<p>Payment terms: {v['terms']} · Ship via: {v['ship_via']} · FOB destination · Ordering method: {v['method']}</p>
<table><tr><th>Line</th><th>Item no.</th><th>Description</th><th>Unit</th><th class=n>Qty</th>
<th class=n>Unit price</th><th class=n>Amount</th></tr>{rows}
<tr><td colspan=6 class=n>Subtotal</td><td class=n>${subtotal:,.2f}</td></tr>
<tr><td colspan=6 class=n>Freight</td><td class=n>${fr:,.2f}</td></tr>
<tr><td colspan=6 class=n><b>Total (USD)</b></td><td class=n><b>${subtotal + fr:,.2f}</b></td></tr></table>
<p>Notes: {html.escape(h['notes'] or 'n/a')}</p>
<p class=muted>Please include lot numbers and expiry dates on the packing slip / ASN.
Minimum remaining shelf life on delivery: as per contract.</p></body></html>"""


def adopt_old_orders(conn):
    """Older versions created one PO per item with no vendor details. Group those still open
    into proper vendor POs (one per vendor and order date) so they follow the vendor simulation."""
    old = conn.execute("SELECT DISTINCT supplier, order_date FROM purchase_orders "
                       "WHERE status = 'OPEN' AND order_no IS NULL").fetchall()
    for supplier, order_date in old:
        if supplier not in VENDORS:
            continue
        sent = date.fromisoformat(order_date)
        with db.atomic(conn):
            order_no = _next_order_no(conn, sent)
            conn.execute("INSERT INTO po_headers (order_no, supplier, status, origin, created_date, notes) "
                         "VALUES (?, ?, 'DRAFT', 'Earlier version', ?, 'Created before vendor POs existed')",
                         (order_no, supplier, order_date))
            ids = [r[0] for r in conn.execute(
                "SELECT po_id FROM purchase_orders p WHERE status = 'OPEN' AND order_no IS NULL "
                "AND supplier = ? AND order_date = ? ORDER BY po_id", (supplier, order_date))]
            for n, po_id in enumerate(ids, start=1):
                conn.execute("UPDATE purchase_orders SET order_no = ?, line_no = ?, status = 'DRAFT', "
                             "unit_cost = (SELECT unit_cost FROM items i WHERE i.item_id = purchase_orders.item_id) "
                             "WHERE po_id = ?", (order_no, n, po_id))
        send_order(conn, order_no, sent)
