"""
db.py: Saves everything in one SQLite file (data/medstock.db).

SQLite is a full database stored as a single file. No server, nothing to install.

Tables
  items             item master (cost, VED, supplier, shelf life)
  lots              the stock itself: every batch with lot number, expiry and quantity left
  usage             daily usage history (feeds the demand estimate)
  deliveries        completed orders with their real lead time (feeds σL)
  po_headers        purchase orders as sent to a vendor (one per vendor, many lines)
  purchase_orders   PO LINES: one item each (DRAFT, OPEN, RECEIVED or CANCELLED)
  transactions      the ledger: every single stock movement, never deleted
  transaction_lots  which lots each movement touched (for recalls: "who got lot X?")
  cycle_counts      physical counts vs. what the system said (record accuracy)
  stockouts         demand we could not fill (from the simulation)
  settings          the simulation clock ("today")
  recalls           manufacturer recalls of a lot (stock pulled from the shelf, deliveries refused)
  vendor_outages    periods when a vendor cannot supply (orders are rejected; the backup vendor is used)

Key ideas
  * On hand is never stored separately. It is always SUM(lots.qty), so the
    total and the lots can never disagree.
  * Issues use FEFO (First Expired, First Out) and NEVER pick an expired lot.
  * Every function that changes stock runs inside one database transaction
    (db.atomic, BEGIN IMMEDIATE with SAVEPOINTs for nesting):
    either everything is saved or nothing is.
"""

import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

DATA = Path(__file__).parent / "data"
DEFAULT_DB = DATA / "medstock.db"

WARDS = ["Emergency Department", "ICU", "Operating Room", "Med-Surg Unit", "Pediatrics",
         "Labor & Delivery", "Outpatient Clinic", "Laboratory"]
WRITE_OFF_REASONS = ["Expired", "Damaged", "Recalled", "Lost / missing"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    item_id TEXT PRIMARY KEY, name TEXT, category TEXT, unit TEXT,
    unit_cost REAL, ordering_cost REAL, holding_rate REAL, ved TEXT,
    shelf_life_days INTEGER, supplier TEXT
);
CREATE TABLE IF NOT EXISTS lots (
    lot_id INTEGER PRIMARY KEY AUTOINCREMENT, item_id TEXT, lot_no TEXT,
    expiry_date TEXT, qty INTEGER NOT NULL CHECK (qty >= 0),
    received_date TEXT, po_id TEXT
);
CREATE TABLE IF NOT EXISTS usage (date TEXT, item_id TEXT, qty_used INTEGER);
CREATE TABLE IF NOT EXISTS deliveries (
    po_id TEXT, item_id TEXT, supplier TEXT, order_date TEXT,
    received_date TEXT, lead_time_days INTEGER
);
CREATE TABLE IF NOT EXISTS purchase_orders (
    po_id TEXT PRIMARY KEY, item_id TEXT, supplier TEXT, qty INTEGER,
    order_date TEXT, expected_date TEXT, status TEXT,
    received_date TEXT, received_qty INTEGER
);
CREATE TABLE IF NOT EXISTS po_headers (
    order_no TEXT PRIMARY KEY, supplier TEXT, status TEXT, origin TEXT,
    created_date TEXT, need_by TEXT, notes TEXT,
    sent_date TEXT, ack_date TEXT, ship_date TEXT, arrive_date TEXT, promised_date TEXT,
    carrier TEXT, tracking_no TEXT, freight REAL, closed_date TEXT
);
CREATE TABLE IF NOT EXISTS stockouts (date TEXT, item_id TEXT, qty_short INTEGER);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS transactions (
    txn_id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, date TEXT,
    item_id TEXT, type TEXT, qty INTEGER, balance_after INTEGER,
    reference TEXT, note TEXT
);
CREATE TABLE IF NOT EXISTS transaction_lots (txn_id INTEGER, lot_id INTEGER, qty INTEGER);
CREATE TABLE IF NOT EXISTS cycle_counts (
    date TEXT, item_id TEXT, lot_id INTEGER, system_qty INTEGER, counted_qty INTEGER, note TEXT
);
CREATE TABLE IF NOT EXISTS recalls (
    recall_id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, item_id TEXT, lot_no TEXT,
    recall_class TEXT, reason TEXT, origin TEXT, qty_removed INTEGER, value_removed REAL
);
CREATE TABLE IF NOT EXISTS vendor_outages (
    outage_id INTEGER PRIMARY KEY AUTOINCREMENT, supplier TEXT, start_date TEXT, end_date TEXT,
    reason TEXT, origin TEXT
);
CREATE TABLE IF NOT EXISTS asn_lots (
    po_id TEXT NOT NULL, seq INTEGER NOT NULL, lot_no TEXT NOT NULL, expiry_date TEXT NOT NULL,
    qty INTEGER NOT NULL, PRIMARY KEY (po_id, seq)
);
CREATE TABLE IF NOT EXISTS demand_requests (
    request_id TEXT PRIMARY KEY, item_id TEXT, date TEXT, ward TEXT,
    requested INTEGER, filled INTEGER, short INTEGER, note TEXT
);
"""


class StockError(ValueError):
    """Raised when a movement is not allowed (e.g. issuing more than we have)."""


_ATOMIC_DEPTH = {}


class atomic:
    """BEGIN IMMEDIATE for the outermost block, SAVEPOINTs for nested ones.

    Every change to stock or purchase orders runs inside one of these, so a
    validation failure rolls back anything written before it in the same block.
    """

    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        key = id(self.conn)
        depth = _ATOMIC_DEPTH.get(key, 0)
        if depth == 0:
            self.conn.execute("BEGIN IMMEDIATE")
        else:
            self.conn.execute(f"SAVEPOINT _atomic_{depth}")
        _ATOMIC_DEPTH[key] = depth + 1
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        key = id(self.conn)
        depth = _ATOMIC_DEPTH[key] - 1
        if depth == 0:
            _ATOMIC_DEPTH.pop(key, None)
        else:
            _ATOMIC_DEPTH[key] = depth
        if exc_type is None:
            if depth == 0:
                if self.conn.in_transaction:
                    self.conn.execute("COMMIT")
            else:
                self.conn.execute(f"RELEASE SAVEPOINT _atomic_{depth}")
        else:
            if depth == 0:
                if self.conn.in_transaction:
                    self.conn.execute("ROLLBACK")
            else:
                self.conn.execute(f"ROLLBACK TO SAVEPOINT _atomic_{depth}")
                self.conn.execute(f"RELEASE SAVEPOINT _atomic_{depth}")
        return False


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

def connect(path=DEFAULT_DB):
    """Open the database. If it does not exist yet, create it from the CSV files."""
    path = Path(path)
    is_new = not path.exists()
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")       # faster commits (the simulation makes many)
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.executescript(SCHEMA)
    _migrate(conn)
    if is_new:
        import_csvs(conn)
    return conn


# Columns added to purchase_orders for multi-line purchase orders (older databases lack them)
PO_LINE_COLUMNS = {"order_no": "TEXT", "line_no": "INTEGER", "unit_cost": "REAL",
                   "confirmed_qty": "INTEGER", "asn_lot_no": "TEXT", "asn_expiry": "TEXT"}


def _migrate(conn):
    have = {r["name"] for r in conn.execute("PRAGMA table_info(purchase_orders)")}
    with atomic(conn):
        for col, kind in PO_LINE_COLUMNS.items():
            if col not in have:
                conn.execute(f"ALTER TABLE purchase_orders ADD COLUMN {col} {kind}")
        if "vendor_note" not in {r["name"] for r in conn.execute("PRAGMA table_info(po_headers)")}:
            conn.execute("ALTER TABLE po_headers ADD COLUMN vendor_note TEXT")
        if "backup_supplier" not in {r["name"] for r in conn.execute("PRAGMA table_info(items)")}:
            conn.execute("ALTER TABLE items ADD COLUMN backup_supplier TEXT")
        _fill_backup_suppliers(conn)


def backup_supplier_for(category, primary):
    """Second-source rule (fictional): which other vendor can supply an item when its primary cannot.
    Medicines and lab tests go to the other pharma distributor; supplies to the other med-surg distributor."""
    if category in ("Medicine", "Laboratory"):
        return "Northwest Medical Distributors" if primary == "Pacific Pharma Supply" else "Pacific Pharma Supply"
    return "Northwest Medical Distributors" if primary == "Cascade Surgical Supply" else "Cascade Surgical Supply"


def _fill_backup_suppliers(conn):
    for r in conn.execute("SELECT item_id, category, supplier FROM items WHERE backup_supplier IS NULL").fetchall():
        conn.execute("UPDATE items SET backup_supplier = ? WHERE item_id = ?",
                     (backup_supplier_for(r["category"], r["supplier"]), r["item_id"]))


def reset(conn):
    """Erase everything and reload the sample data (a fresh start for the simulation)."""
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' "
                                         "AND name NOT LIKE 'sqlite_%'")]
    with atomic(conn):
        for t in tables:
            conn.execute(f"DROP TABLE {t}")
    conn.executescript(SCHEMA)
    _migrate(conn)
    import_csvs(conn)


# ---------------------------------------------------------------------------
# The clock. Normally "today" is the real date. The simulation moves it forward
# (see simulation.py), and every screen and rule follows it.
# ---------------------------------------------------------------------------

def today(conn):
    row = conn.execute("SELECT value FROM settings WHERE key = 'today'").fetchone()
    return date.fromisoformat(row[0]) if row else date.today()


def set_today(conn, new_date):
    with atomic(conn):
        conn.execute("INSERT OR REPLACE INTO settings VALUES ('today', ?)", (new_date.isoformat(),))


def import_csvs(conn, folder=DATA):
    """Load the sample CSVs (from generate_sample_data.py) into a fresh database."""
    with atomic(conn):
        for table in ["items", "usage", "deliveries", "lots"]:
            pd.read_csv(folder / f"{table}.csv").to_sql(table, conn, if_exists="append", index=False)
        _fill_backup_suppliers(conn)


def load_stock(conn, as_of=None):
    """Item master with stock columns, and the open purchase order lines.

    items gets two stock columns:
      on_hand  = everything on the shelf
      usable   = only lots that have NOT expired (what we can actually give patients)
    """
    as_of = (as_of or today(conn)).isoformat()
    items = pd.read_sql(
        "SELECT i.*, COALESCE(SUM(l.qty), 0) AS on_hand, "
        "       COALESCE(SUM(CASE WHEN l.expiry_date > ? AND l.received_date <= ? THEN l.qty END), 0) AS usable "
        "FROM items i LEFT JOIN lots l USING (item_id) GROUP BY i.item_id ORDER BY i.item_id",
        conn, params=(as_of, as_of))
    # On order = lines sent to a vendor and not yet received (drafts are NOT orders yet).
    # Once the vendor has confirmed, we count what they confirmed, not what we asked for.
    open_pos = pd.read_sql(
        "SELECT p.po_id, p.order_no, p.line_no, p.item_id, p.supplier, p.qty AS ordered_qty, "
        "       MAX(0, CASE WHEN h.ack_date <= ? THEN COALESCE(p.confirmed_qty, p.qty) ELSE p.qty END "
        "           - COALESCE(p.received_qty, 0)) AS qty, "
        "       p.order_date, p.expected_date, h.arrive_date, h.ship_date, p.asn_lot_no, p.asn_expiry "
        "FROM purchase_orders p LEFT JOIN po_headers h USING (order_no) WHERE p.status = 'OPEN'",
        conn, params=(as_of,), parse_dates=["order_date", "expected_date", "arrive_date", "ship_date"])
    return items, open_pos


def load_frames(conn, as_of=None):
    """Everything planning.build_plan() needs, as pandas DataFrames."""
    items, open_pos = load_stock(conn, as_of)
    usage = pd.read_sql("SELECT * FROM usage", conn, parse_dates=["date"])
    deliveries = pd.read_sql("SELECT * FROM deliveries", conn, parse_dates=["order_date", "received_date"])
    lots = pd.read_sql("SELECT * FROM lots WHERE qty > 0 ORDER BY item_id, expiry_date", conn,
                       parse_dates=["expiry_date", "received_date"])
    return items, usage, deliveries, open_pos, lots


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _get_item(conn, item_id):
    row = conn.execute("SELECT * FROM items WHERE item_id = ?", (item_id,)).fetchone()
    if row is None:
        raise StockError(f"Unknown item {item_id}")
    return row


def _get_lot(conn, lot_id):
    row = conn.execute("SELECT * FROM lots WHERE lot_id = ?", (lot_id,)).fetchone()
    if row is None:
        raise StockError(f"Unknown lot {lot_id}")
    return row


def on_hand(conn, item_id):
    return conn.execute("SELECT COALESCE(SUM(qty), 0) FROM lots WHERE item_id = ?", (item_id,)).fetchone()[0]


def _check_qty(qty):
    if int(qty) != qty or qty <= 0:
        raise StockError("Quantity must be a whole number greater than zero")
    return int(qty)


def _check_date(conn, on_date):
    if on_date > today(conn):
        raise StockError("Date cannot be in the future")
    return on_date


def _latest_stock_movement(conn, item_id):
    return conn.execute("SELECT MAX(date) FROM transactions WHERE item_id = ? AND qty != 0",
                        (item_id,)).fetchone()[0]


def _check_movement_date(conn, item_id, on_date):
    latest = _latest_stock_movement(conn, item_id)
    if latest and on_date.isoformat() < latest:
        raise StockError(f"Stock movement for {item_id} cannot be dated before its latest "
                         f"stock movement on {latest}")


def _ledger(conn, on_date, item_id, kind, qty, reference="", note="", lot_moves=()):
    """Write one ledger row (+ which lots it touched). Returns the transaction id."""
    cur = conn.execute(
        "INSERT INTO transactions (created_at, date, item_id, type, qty, balance_after, reference, note) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (datetime.now().isoformat(timespec="seconds"), on_date.isoformat(), item_id,
         kind, qty, on_hand(conn, item_id), reference, note))
    for lot_id, lot_qty in lot_moves:
        conn.execute("INSERT INTO transaction_lots VALUES (?, ?, ?)", (cur.lastrowid, lot_id, lot_qty))
    return cur.lastrowid


def _next_po_id(conn):
    ids = [r[0] for r in conn.execute("SELECT po_id FROM deliveries UNION SELECT po_id FROM purchase_orders")]
    nums = [int(i[2:]) for i in ids if i and i.startswith("PO") and i[2:].isdigit()]
    return f"PO{max(nums, default=999) + 1}"


# ---------------------------------------------------------------------------
# Stock movements
# ---------------------------------------------------------------------------

def issue(conn, item_id, qty, ward, on_date=None, note=""):
    """Stock leaves the storeroom to a ward, picked FEFO from non-expired lots.

    Returns a list of (lot_no, qty) that were picked, so the user knows
    which physical boxes to take off the shelf.
    """
    qty = _check_qty(qty)
    on_date = _check_date(conn, on_date or today(conn))
    with atomic(conn):
        item = _get_item(conn, item_id)
        _check_movement_date(conn, item_id, on_date)
        lots = conn.execute(
            "SELECT * FROM lots WHERE item_id = ? AND qty > 0 AND expiry_date > ? AND received_date <= ? "
            "ORDER BY expiry_date, lot_id", (item_id, on_date.isoformat(), on_date.isoformat())).fetchall()
        usable = sum(l["qty"] for l in lots)
        if qty > usable:
            expired = on_hand(conn, item_id) - usable
            extra = f" ({expired} more are expired and must be written off)" if expired else ""
            raise StockError(f"Only {usable} usable {item['unit']} on hand{extra}; cannot issue {qty}")

        picks, remaining = [], qty
        for lot in lots:                                  # FEFO: soonest expiry first
            take = min(remaining, lot["qty"])
            conn.execute("UPDATE lots SET qty = qty - ? WHERE lot_id = ?", (take, lot["lot_id"]))
            picks.append((lot["lot_id"], lot["lot_no"], take))
            remaining -= take
            if remaining == 0:
                break

        conn.execute("INSERT INTO usage (date, item_id, qty_used) VALUES (?, ?, ?)",
                     (on_date.isoformat(), item_id, qty))
        picked = ", ".join(f"{no} × {q}" for _, no, q in picks)
        _ledger(conn, on_date, item_id, "ISSUE", -qty, ward, f"FEFO: {picked}. {note}".strip(),
                [(lot_id, -q) for lot_id, _, q in picks])
    return [(no, q) for _, no, q in picks]


def create_po(conn, item_id, qty, on_date=None, note=""):
    """Place a purchase order. Stock does not change yet, but it is now 'on order'."""
    qty = _check_qty(qty)
    on_date = _check_date(conn, on_date or today(conn))
    with atomic(conn):
        item = _get_item(conn, item_id)
        # Expected arrival = order date + this item's average past lead time
        avg = conn.execute("SELECT AVG(lead_time_days) FROM deliveries WHERE item_id = ?",
                           (item_id,)).fetchone()[0] or 7
        po_id = _next_po_id(conn)
        conn.execute(
            "INSERT INTO purchase_orders (po_id, item_id, supplier, qty, order_date, expected_date, status) "
            "VALUES (?, ?, ?, ?, ?, ?, 'OPEN')",
            (po_id, item_id, item["supplier"], qty, on_date.isoformat(),
             (on_date + timedelta(days=round(avg))).isoformat()))
        _ledger(conn, on_date, item_id, "PO CREATED", 0, po_id, f"Ordered {qty}. {note}".strip())
    return po_id


def cancel_po(conn, po_id, note=""):
    with atomic(conn):
        po = conn.execute("SELECT * FROM purchase_orders WHERE po_id = ? AND status = 'OPEN'", (po_id,)).fetchone()
        if po is None:
            raise StockError(f"{po_id} is not an open purchase order")
        conn.execute("UPDATE purchase_orders SET status = 'CANCELLED' WHERE po_id = ?", (po_id,))
        _ledger(conn, today(conn), po["item_id"], "PO CANCELLED", 0, po["order_no"] or po_id, note)
        close_order_if_done(conn, po["order_no"], today(conn))


def close_order_if_done(conn, order_no, on_date):
    """A purchase order is closed when none of its lines is still open."""
    if not order_no:
        return
    left = conn.execute("SELECT COUNT(*) FROM purchase_orders WHERE order_no = ? AND status IN ('OPEN', 'DRAFT')",
                        (order_no,)).fetchone()[0]
    if left == 0:
        got = conn.execute("SELECT COUNT(*) FROM purchase_orders WHERE order_no = ? AND status = 'RECEIVED'",
                           (order_no,)).fetchone()[0]
        conn.execute("UPDATE po_headers SET status = ?, closed_date = ? WHERE order_no = ?",
                     ("RECEIVED" if got else "CANCELLED", on_date.isoformat(), order_no))


def receive(conn, po_id, qty, lot_no, expiry_date, on_date=None, note=""):
    """Goods arrive for an open PO as one lot. See receive_lots for several lots."""
    return receive_lots(conn, po_id, [(lot_no, expiry_date, qty)], on_date, note)


def receive_lots(conn, po_id, lots, on_date=None, note=""):
    """One delivery line arrives as one or more lots: lots = [(lot_no, expiry_date, qty), ...].

    Each lot becomes its own row on the shelf (so FEFO and recalls work per lot), but the receipt
    is ONE delivery: one ledger row and one lead-time sample for σL. Every lot is checked before
    anything is saved: lot number present and not repeated, not expired, not under recall, and the
    total no more than what is still outstanding.
    """
    on_date = _check_date(conn, on_date or today(conn))
    if not lots:
        raise StockError("Enter at least one lot")
    clean, seen = [], set()
    for lot_no, expiry_date, qty in lots:
        qty = _check_qty(qty)
        lot_no = (lot_no or "").strip()
        if not lot_no:
            raise StockError("Lot number is required (it is printed on the box)")
        if lot_no in seen:
            raise StockError(f"Lot {lot_no} is listed twice. Add its quantities together")
        seen.add(lot_no)
        if expiry_date <= on_date:
            raise StockError(f"Lot {lot_no} is already expired. Do not accept it; return it to the supplier")
        if is_recalled(conn, lot_no):
            raise StockError(f"Lot {lot_no} is under recall. Refuse it and ask the vendor for a replacement")
        clean.append((lot_no, expiry_date, qty))
    qty = sum(q for _, _, q in clean)
    with atomic(conn):
        po = conn.execute("SELECT * FROM purchase_orders WHERE po_id = ? AND status = 'OPEN'", (po_id,)).fetchone()
        if po is None:
            raise StockError(f"{po_id} is not an open purchase order")
        order_date = date.fromisoformat(po["order_date"])
        if on_date < order_date:
            raise StockError("Received date cannot be before the order date")
        if po["order_no"]:
            arrive = conn.execute("SELECT arrive_date FROM po_headers WHERE order_no = ?",
                                  (po["order_no"],)).fetchone()[0]
            if arrive and on_date < date.fromisoformat(arrive):
                raise StockError(f"{po['order_no']} has not arrived yet. Check its status in Purchasing")
        _check_movement_date(conn, po["item_id"], on_date)
        expected = po["confirmed_qty"] if po["confirmed_qty"] is not None else po["qty"]
        received = po["received_qty"] or 0
        remaining = expected - received
        if qty > remaining:
            raise StockError(f"{po_id} only has {remaining} outstanding; "
                             f"cannot receive {qty} (the vendor confirmed {expected})")
        lead_time = (on_date - order_date).days
        moves = []
        for lot_no, expiry_date, lot_qty in clean:
            cur = conn.execute(
                "INSERT INTO lots (item_id, lot_no, expiry_date, qty, received_date, po_id) VALUES (?, ?, ?, ?, ?, ?)",
                (po["item_id"], lot_no, expiry_date.isoformat(), lot_qty, on_date.isoformat(), po_id))
            moves.append((cur.lastrowid, lot_qty))
        new_received = received + qty
        if new_received >= expected:
            conn.execute("UPDATE purchase_orders SET status = 'RECEIVED', received_date = ?, received_qty = ? "
                         "WHERE po_id = ?", (on_date.isoformat(), new_received, po_id))
        else:
            conn.execute("UPDATE purchase_orders SET received_qty = ? WHERE po_id = ?", (new_received, po_id))
        conn.execute("INSERT INTO deliveries (po_id, item_id, supplier, order_date, received_date, lead_time_days) "
                     "VALUES (?, ?, ?, ?, ?, ?)",
                     (po_id, po["item_id"], po["supplier"], po["order_date"], on_date.isoformat(), lead_time))
        short = f" Short by {expected - new_received}." if new_received < expected else ""
        lot_text = (f"Lot {clean[0][0]}, expires {clean[0][1]}." if len(clean) == 1 else
                    f"{len(clean)} lots: " + "; ".join(f"{l} ({q}, expires {e})" for l, e, q in clean) + ".")
        _ledger(conn, on_date, po["item_id"], "RECEIVE", qty, po["order_no"] or po_id,
                f"{lot_text} Lead time {lead_time} days.{short} {note}".strip(), moves)
        close_order_if_done(conn, po["order_no"], on_date)
    return lead_time


def asn_lots(conn, po_id):
    """The lots a vendor's ship notice announced for one line: [(lot_no, expiry_date, qty), ...].
    Older orders have a single lot in purchase_orders.asn_lot_no / asn_expiry."""
    rows = conn.execute("SELECT lot_no, expiry_date, qty FROM asn_lots WHERE po_id = ? ORDER BY seq",
                        (po_id,)).fetchall()
    if rows:
        return [(r["lot_no"], date.fromisoformat(r["expiry_date"]), int(r["qty"])) for r in rows]
    po = conn.execute("SELECT asn_lot_no, asn_expiry, confirmed_qty, qty FROM purchase_orders WHERE po_id = ?",
                      (po_id,)).fetchone()
    if po is None or not po["asn_lot_no"]:
        return []
    qty = po["confirmed_qty"] if po["confirmed_qty"] is not None else po["qty"]
    return [(po["asn_lot_no"], date.fromisoformat(po["asn_expiry"]), int(qty))]


def write_off(conn, lot_id, qty, reason, on_date=None, note=""):
    """Remove stock from ONE lot that can no longer be used. NOT counted as demand."""
    qty = _check_qty(qty)
    on_date = _check_date(conn, on_date or today(conn))
    with atomic(conn):
        lot = _get_lot(conn, lot_id)
        if lot["received_date"] and on_date.isoformat() < lot["received_date"]:
            raise StockError(f"Lot {lot['lot_no']} was received on {lot['received_date']}; "
                             f"cannot write it off before that date")
        _check_movement_date(conn, lot["item_id"], on_date)
        if qty > lot["qty"]:
            raise StockError(f"Lot {lot['lot_no']} only has {lot['qty']}; cannot write off {qty}")
        conn.execute("UPDATE lots SET qty = qty - ? WHERE lot_id = ?", (qty, lot_id))
        _ledger(conn, on_date, lot["item_id"], "WRITE-OFF", -qty, reason,
                f"Lot {lot['lot_no']} (exp. {lot['expiry_date']}). {note}".strip(), [(lot_id, -qty)])
    return on_hand(conn, lot["item_id"])


def write_off_all_expired(conn, on_date=None):
    """Write off every expired lot in one go. Returns (number of lots, dollar value)."""
    on_date = _check_date(conn, on_date or today(conn))
    with atomic(conn):
        rows = conn.execute(
            "SELECT l.lot_id, l.qty, i.unit_cost FROM lots l JOIN items i USING (item_id) "
            "WHERE l.qty > 0 AND l.expiry_date <= ?", (on_date.isoformat(),)).fetchall()
        for r in rows:
            write_off(conn, r["lot_id"], r["qty"], "Expired", on_date)
    return len(rows), sum(r["qty"] * r["unit_cost"] for r in rows)


def cycle_count(conn, lot_id, counted_qty, on_date=None, note=""):
    """Physical count of ONE lot. If it differs from the system, correct it and log the difference."""
    if int(counted_qty) != counted_qty or counted_qty < 0:
        raise StockError("Counted quantity must be a whole number, zero or more")
    counted_qty = int(counted_qty)
    on_date = _check_date(conn, on_date or today(conn))
    with atomic(conn):
        lot = _get_lot(conn, lot_id)
        if lot["received_date"] and on_date.isoformat() < lot["received_date"]:
            raise StockError(f"Lot {lot['lot_no']} was received on {lot['received_date']}; "
                             f"cannot count it before that date")
        _check_movement_date(conn, lot["item_id"], on_date)
        diff = counted_qty - lot["qty"]
        conn.execute("INSERT INTO cycle_counts VALUES (?, ?, ?, ?, ?, ?)",
                     (on_date.isoformat(), lot["item_id"], lot_id, lot["qty"], counted_qty, note))
        if diff != 0:
            conn.execute("UPDATE lots SET qty = ? WHERE lot_id = ?", (counted_qty, lot_id))
        _ledger(conn, on_date, lot["item_id"], "COUNT", diff, "Cycle count",
                f"Lot {lot['lot_no']}: system said {lot['qty']}, counted {counted_qty}. {note}".strip(),
                [(lot_id, diff)] if diff else [])
    return diff


def is_recalled(conn, lot_no):
    return conn.execute("SELECT 1 FROM recalls WHERE lot_no = ?", (lot_no,)).fetchone() is not None


def _next_request_id(conn):
    ids = [r[0] for r in conn.execute("SELECT request_id FROM demand_requests")]
    nums = [int(i[3:]) for i in ids if i and i.startswith("REQ") and i[3:].isdigit()]
    return f"REQ{max(nums, default=0) + 1}"


def fulfill_request(conn, item_id, qty, ward, on_date=None, note="", request_id=None):
    """Serve a ward request FEFO from usable stock; the part we cannot fill is a stockout.

    Returns {"requested", "filled", "short", "picks", ...}. Passing the same
    request_id again returns the stored result without touching stock twice.
    """
    qty = _check_qty(qty)
    on_date = _check_date(conn, on_date or today(conn))
    ward = (ward or "").strip()
    if not ward:
        raise StockError("Ward is required")
    with atomic(conn):
        request_id = request_id or _next_request_id(conn)
        item = _get_item(conn, item_id)
        existing = conn.execute("SELECT * FROM demand_requests WHERE request_id = ?",
                                (request_id,)).fetchone()
        if existing is not None:
            if (existing["item_id"] != item_id or existing["date"] != on_date.isoformat()
                    or existing["ward"] != ward or existing["requested"] != qty):
                raise StockError(f"Request {request_id} is already recorded with different details")
            stored = json.loads(existing["note"])
            return {"request_id": request_id, "item_id": item_id, "date": on_date.isoformat(), "ward": ward,
                    "requested": existing["requested"], "filled": existing["filled"], "short": existing["short"],
                    "note": stored.get("note", ""), "picks": stored.get("picks", [])}
        _check_movement_date(conn, item_id, on_date)
        lots = conn.execute(
            "SELECT * FROM lots WHERE item_id = ? AND qty > 0 AND expiry_date > ? AND received_date <= ? "
            "ORDER BY expiry_date, lot_id", (item_id, on_date.isoformat(), on_date.isoformat())).fetchall()
        available = sum(l["qty"] for l in lots)
        filled = min(qty, available)
        picks = issue(conn, item_id, filled, ward, on_date, note) if filled else []
        short = qty - filled
        if short:
            conn.execute("INSERT INTO usage (date, item_id, qty_used) VALUES (?, ?, ?)",
                         (on_date.isoformat(), item_id, short))
            conn.execute("INSERT INTO stockouts VALUES (?, ?, ?)", (on_date.isoformat(), item_id, short))
            _ledger(conn, on_date, item_id, "STOCKOUT", 0, ward,
                    f"{short} {item['unit']} requested but not available")
        conn.execute(
            "INSERT INTO demand_requests (request_id, item_id, date, ward, requested, filled, short, note) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (request_id, item_id, on_date.isoformat(), ward, qty, filled, short,
             json.dumps({"note": note, "picks": picks})))
    return {"request_id": request_id, "item_id": item_id, "date": on_date.isoformat(), "ward": ward,
            "requested": qty, "filled": filled, "short": short, "note": note, "picks": picks}


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

def ledger(conn):
    return pd.read_sql(
        "SELECT t.txn_id, t.date, t.created_at, t.item_id, i.name, t.type, t.qty, "
        "t.balance_after, t.reference, t.note "
        "FROM transactions t JOIN items i USING (item_id) ORDER BY t.txn_id DESC", conn)


def lot_trace(conn, lot_no):
    """Recall support: every movement of a given lot number, including which ward got it."""
    return pd.read_sql(
        "SELECT t.date, t.type, tl.qty, t.reference AS ward_or_reference, i.name, l.lot_no, l.expiry_date "
        "FROM transaction_lots tl JOIN transactions t USING (txn_id) JOIN lots l USING (lot_id) "
        "JOIN items i ON i.item_id = l.item_id WHERE l.lot_no = ? ORDER BY t.txn_id", conn, params=(lot_no,))


def record_accuracy(conn):
    """Share of cycle counts where the system matched the shelf (target: 97%+)."""
    row = conn.execute("SELECT COUNT(*), SUM(system_qty = counted_qty) FROM cycle_counts").fetchone()
    total, matched = row[0], row[1] or 0
    return (matched / total if total else None), total
