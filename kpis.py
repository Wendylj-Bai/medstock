"""
kpis.py: Key performance indicators: is inventory management working, and is it getting better?

Service (are patients getting what they need?)
  fill rate          units served ÷ units requested            (target: 98%+, higher for Vital items)
  stockout events    days on which an item could not fully supply a request

Money (how much is tied up, and how much is lost?)
  avg inventory      average dollar value on the shelf over the period
  inventory turns    yearly issued value ÷ average inventory value   (how many times stock "turns over")
  days on hand       average inventory ÷ daily issued value          (how long stock lasts)
  waste              value written off (expired, damaged, …) + value pulled by recalls

Supply (are vendors reliable?)
  on time            deliveries that arrived by the vendor's promised date
  vendor fill rate   units confirmed ÷ units ordered
  rejected orders    orders refused because of a vendor disruption
  backup spend       share of purchasing spend placed with a backup vendor (costs more)

Stock levels are rebuilt from the transaction ledger, so inventory KPIs start on the first day the
ledger has movements (the sample history before that has usage but no stock movements).
"""

import pandas as pd


def _ledger(conn):
    return pd.read_sql("SELECT t.date, t.item_id, t.type, t.qty, t.reference, i.unit_cost, i.ved "
                       "FROM transactions t JOIN items i USING (item_id)", conn, parse_dates=["date"])


def inventory_value_by_day(conn, start, end):
    """Dollar value on the shelf at the end of each day, rebuilt backwards from today's lots."""
    t = _ledger(conn)
    moves = t[t["qty"] != 0]
    current = pd.read_sql("SELECT l.item_id, SUM(l.qty) AS qty, i.unit_cost FROM lots l JOIN items i "
                          "USING (item_id) GROUP BY l.item_id", conn)
    value_now = float((current["qty"] * current["unit_cost"]).sum())
    if moves.empty:
        return pd.Series(dtype=float), None
    first = moves["date"].min().date()
    start = max(start, first)
    days = pd.date_range(start, end, freq="D")
    if len(days) == 0:
        return pd.Series(dtype=float), first
    daily_change = (moves["qty"] * moves["unit_cost"]).groupby(moves["date"]).sum()
    # value at the end of day d = value now − every change dated after d
    series = [value_now - daily_change[daily_change.index > d].sum() for d in days]
    return pd.Series(series, index=days), first


def compute(conn, start, end):
    """All KPIs for the period start..end (dates, inclusive). Returns a dict."""
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    usage = pd.read_sql("SELECT u.date, u.item_id, u.qty_used, i.ved FROM usage u JOIN items i USING (item_id) "
                        "WHERE u.date BETWEEN ? AND ?", conn, params=(start.isoformat(), end.isoformat()))
    so = pd.read_sql("SELECT s.date, s.item_id, s.qty_short, i.ved FROM stockouts s JOIN items i USING (item_id) "
                     "WHERE s.date BETWEEN ? AND ?", conn, params=(start.isoformat(), end.isoformat()))
    demand, short = int(usage["qty_used"].sum()), int(so["qty_short"].sum())
    by_ved = {}
    for v in ["V", "E", "D"]:
        dv = usage.loc[usage["ved"] == v, "qty_used"].sum()
        sv = so.loc[so["ved"] == v, "qty_short"].sum()
        by_ved[v] = 1 - sv / dv if dv else None

    t = _ledger(conn)
    t = t[(t["date"] >= s) & (t["date"] <= e)]
    value = -(t["qty"] * t["unit_cost"])
    issued_value = float(value[t["type"] == "ISSUE"].sum())
    write_offs = t[t["type"] == "WRITE-OFF"]
    waste_by_reason = (-(write_offs["qty"] * write_offs["unit_cost"])).groupby(write_offs["reference"]).sum().to_dict()
    recall_value = float(value[t["type"] == "RECALL"].sum())

    inv, first_move = inventory_value_by_day(conn, start, end)
    avg_inv = float(inv.mean()) if len(inv) else None
    inv_days = len(inv)
    issued_in_inv_window = float(value[(t["type"] == "ISSUE") & (t["date"] >= (inv.index.min() if len(inv) else s))].sum())
    daily_issue = issued_in_inv_window / inv_days if inv_days else 0
    turns = (daily_issue * 365 / avg_inv) if avg_inv else None
    days_on_hand = (avg_inv / daily_issue) if avg_inv and daily_issue else None

    # Vendors: orders that reached the dock (or were rejected) in the period
    h = pd.read_sql("SELECT * FROM po_headers WHERE sent_date IS NOT NULL", conn)
    lines = pd.read_sql("SELECT p.order_no, p.item_id, p.supplier, p.qty, p.confirmed_qty, p.unit_cost, "
                        "i.supplier AS primary_supplier FROM purchase_orders p JOIN items i USING (item_id) "
                        "WHERE p.order_no IS NOT NULL AND p.status != 'DRAFT'", conn)
    rejected = h[h["vendor_note"].notna() & (h["ack_date"] >= start.isoformat()) & (h["ack_date"] <= end.isoformat())]
    arrived = h[h["vendor_note"].isna() & (h["arrive_date"] >= start.isoformat())
                & (h["arrive_date"] <= end.isoformat())]
    sent = h[(h["sent_date"] >= start.isoformat()) & (h["sent_date"] <= end.isoformat())]
    sent_lines = lines[lines["order_no"].isin(sent["order_no"])]
    spend = float((sent_lines["qty"] * sent_lines["unit_cost"]).sum())
    backup = sent_lines[sent_lines["supplier"] != sent_lines["primary_supplier"]]
    backup_spend = float((backup["qty"] * backup["unit_cost"]).sum())
    acked = lines[lines["order_no"].isin(arrived["order_no"])]

    vendors = []
    for name, g in arrived.groupby("supplier"):
        lt = (pd.to_datetime(g["arrive_date"]) - pd.to_datetime(g["sent_date"])).dt.days
        gl = acked[acked["order_no"].isin(g["order_no"])]
        vendors.append({"vendor": name, "deliveries": len(g),
                        "on_time": float((g["arrive_date"] <= g["promised_date"]).mean()),
                        "avg_lead_time": float(lt.mean()),
                        "fill_rate": float(gl["confirmed_qty"].sum() / gl["qty"].sum()) if gl["qty"].sum() else None,
                        "rejected_orders": int((rejected["supplier"] == name).sum())})
    for name in set(rejected["supplier"]) - {v["vendor"] for v in vendors}:
        vendors.append({"vendor": name, "deliveries": 0, "on_time": None, "avg_lead_time": None,
                        "fill_rate": None, "rejected_orders": int((rejected["supplier"] == name).sum())})

    return {
        "start": start, "end": end, "demand": demand, "short": short,
        "fill_rate": 1 - short / demand if demand else None, "fill_by_ved": by_ved,
        "stockout_events": len(so), "vital_stockout_events": int((so["ved"] == "V").sum()),
        "issued_value": issued_value, "avg_inventory": avg_inv, "turns": turns, "days_on_hand": days_on_hand,
        "inventory_series": inv, "inventory_since": first_move,
        "waste_by_reason": waste_by_reason, "recall_value": recall_value,
        "waste_total": float(sum(waste_by_reason.values())) + recall_value,
        "on_time": float((arrived["arrive_date"] <= arrived["promised_date"]).mean()) if len(arrived) else None,
        "vendor_fill": float(acked["confirmed_qty"].sum() / acked["qty"].sum()) if acked["qty"].sum() else None,
        "rejected_orders": len(rejected), "spend": spend,
        "backup_share": backup_spend / spend if spend else None, "backup_spend": backup_spend,
        "vendors": pd.DataFrame(vendors),
        "recalls": conn.execute("SELECT COUNT(*) FROM recalls WHERE date BETWEEN ? AND ?",
                                (start.isoformat(), end.isoformat())).fetchone()[0],
        "outage_days": _outage_days(conn, start, end),
    }


def _outage_days(conn, start, end):
    o = pd.read_sql("SELECT start_date, end_date FROM vendor_outages", conn)
    total = 0
    for r in o.itertuples():
        a = max(pd.Timestamp(r.start_date), pd.Timestamp(start))
        b = min(pd.Timestamp(r.end_date), pd.Timestamp(end))
        total += max(0, (b - a).days + 1)
    return total


def weekly(conn, start, end):
    """Week-by-week trend: demand, shortages, fill rate, inventory value at week end, waste."""
    usage = pd.read_sql("SELECT date, qty_used FROM usage WHERE date BETWEEN ? AND ?", conn,
                        params=(start.isoformat(), end.isoformat()), parse_dates=["date"])
    so = pd.read_sql("SELECT date, qty_short FROM stockouts WHERE date BETWEEN ? AND ?", conn,
                     params=(start.isoformat(), end.isoformat()), parse_dates=["date"])
    t = _ledger(conn)
    t = t[(t["date"] >= pd.Timestamp(start)) & (t["date"] <= pd.Timestamp(end))
          & t["type"].isin(["WRITE-OFF", "RECALL"])]
    wk = lambda d: d.dt.to_period("W-SUN").dt.start_time
    df = pd.DataFrame({
        "demand": usage.groupby(wk(usage["date"]))["qty_used"].sum(),
        "short": so.groupby(wk(so["date"]))["qty_short"].sum(),
        "waste": (-(t["qty"] * t["unit_cost"])).groupby(wk(t["date"])).sum(),
    }).fillna(0)
    inv, _ = inventory_value_by_day(conn, start, end)
    if len(inv):
        df["inventory_value"] = inv.groupby(inv.index.to_period("W-SUN").start_time).last()
    df["fill_rate"] = 1 - df["short"] / df["demand"].where(df["demand"] > 0)
    df.index.name = "week"
    return df.reset_index()
