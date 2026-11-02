"""
simulation.py: Move the clock forward and let the hospital "live".

Each simulated day, in this order:
  0. Vendor news: orders rejected by a disrupted vendor are closed. With random events on,
     a vendor may become unable to supply, or a manufacturer may recall a lot (see events.py).
  1. Morning: deliveries that reached the dock are received (if auto-receive is on).
  2. During the day: every item has random demand around its forecast (with the usual
     weekend dip). It is issued FEFO from usable stock. Demand that cannot be filled is a
     STOCKOUT: it is logged, and still counted as demand so the forecast stays honest.
  3. Evening: if auto-reorder is on, the reorder plan is recalculated and POs are created
     for 🔴 items, one per vendor: as drafts for a buyer to approve, or sent automatically.

Vendors respond on their own schedule (see purchasing.py).
This lets you watch the (Q, R) policy work, or fail, over weeks in a few seconds.
"""

from datetime import timedelta

import numpy as np
import pandas as pd

import db
import events
import forecasting as fc
import planning
import purchasing as pu

AUTO_MODES = ["Off (I order myself)", "Create drafts for approval", "Fully automatic (send POs)"]
# Chance per simulated day of a random event (when random events are on)
OUTAGE_PER_DAY = 1 / 45        # a vendor disruption about every 6 weeks
RECALL_PER_DAY = 1 / 40        # a lot recall about every 6 weeks


def weekday_factors(usage, days=365):
    """Average demand on each weekday relative to the overall average (weekends are quieter)."""
    recent = usage[usage["date"] > usage["date"].max() - pd.Timedelta(days=days)]
    daily = recent.groupby("date")["qty_used"].sum()
    f = daily.groupby(daily.index.day_of_week).mean() / daily.mean()
    return f.reindex(range(7), fill_value=1.0).to_numpy()


def next_arrival(conn):
    """Date of the next delivery still on its way (or None)."""
    today = db.today(conn)
    o = pu.orders(conn, today)
    if o.empty:
        return None
    coming = o[o["stage"].isin(["SENT", "CONFIRMED", "SHIPPED"])]
    return pd.to_datetime(coming["arrive_date"]).min().date() if len(coming) else None


def advance(conn, days, service_levels=None, method="Auto", params=None,
            auto_mode=AUTO_MODES[0], auto_receive=True, seed=None, random_events=False):
    """Simulate `days` days. Returns a summary dict of what happened."""
    start = db.today(conn)
    _, usage, *_ = db.load_frames(conn, start)
    week = weekday_factors(usage)
    variability = planning.demand_stats(usage, 90)              # sd / mean = how bumpy each item is
    cv = (variability["sd"] / variability["d"]).replace([np.inf], 0).fillna(0).clip(0, 1.5)
    rng = np.random.default_rng(seed if seed is not None else start.toordinal())

    report = {"start": start, "days": days, "demand": 0, "issued": 0, "stockouts": [],
              "received": [], "drafted": [], "sent": [], "events": []}
    forecasts, fc_date = fc.forecast_all(usage, start, method, params), start
    for k in range(1, days + 1):
        day = start + timedelta(days=k)
        db.set_today(conn, day)
        if day.month != fc_date.month:                  # a month was completed: update the forecast
            forecasts, fc_date = fc.forecast_all(usage, day, method, params), day
        offset = (day - fc_date).days                   # rates[0] is the forecast for fc_date

        # 0. Vendor news and random events
        for order_no in pu.process_vendor_responses(conn, day):
            report["events"].append({"date": day, "event": f"❌ {order_no} rejected by "
                                                           f"{pu.order_header(conn, order_no)['supplier']} "
                                                           "(supply disruption)"})
        if random_events:
            if rng.random() < OUTAGE_PER_DAY:
                o = events.random_outage(conn, rng, day)
                if o:
                    report["events"].append({"date": day, "event": f"🏭 {o['supplier']} cannot supply for "
                                                                   f"{o['days']} days"})
            if rng.random() < RECALL_PER_DAY:
                r = events.random_recall(conn, rng, day)
                if r:
                    report["events"].append({"date": day, "event": f"🚨 Recall of lot {r['lot_no']} "
                                                                   f"({r['item_id']}): {r['removed']} pulled"})

        # 1. Morning: receive what is at the dock
        if auto_receive:
            o = pu.orders(conn, day)
            for order_no in o.loc[o["stage"] == "ARRIVED", "order_no"]:
                for name, qty, lot_no, lead in pu.receive_order(conn, order_no, day):
                    report["received"].append({"date": day, "order_no": order_no, "item": name, "qty": qty,
                                               "lot": lot_no, "lead_time": lead})

        # 2. Daily demand around the forecast, issued FEFO
        items, _ = db.load_stock(conn, day)
        today_usage = []
        for r in items.itertuples():
            f = forecasts.get(r.item_id)
            if f is None:
                continue
            mean = f["rates"][min(offset, len(f["rates"]) - 1)] * week[day.weekday()]
            demand = int(round(max(0.0, rng.normal(mean, mean * cv.get(r.item_id, 0.3)))))
            if demand == 0:
                continue
            today_usage.append((pd.Timestamp(day), r.item_id, demand))
            served = db.fulfill_request(conn, r.item_id, demand, str(rng.choice(db.WARDS)), day,
                                        "Simulated demand")
            report["demand"] += demand
            report["issued"] += served["filled"]
            if served["short"]:
                report["stockouts"].append({"date": day, "item_id": r.item_id, "item": r.name,
                                            "ved": r.ved, "short": served["short"]})
        # keep the in-memory usage history in step with the database (cheaper than re-reading it)
        usage = pd.concat([usage, pd.DataFrame(today_usage, columns=["date", "item_id", "qty_used"])],
                          ignore_index=True)

        # 3. Evening: automatic replenishment
        if auto_mode != AUTO_MODES[0]:
            items, open_pos = db.load_stock(conn, day)
            deliveries = pd.read_sql("SELECT * FROM deliveries", conn, parse_dates=["order_date", "received_date"])
            lots = pd.read_sql("SELECT * FROM lots WHERE qty > 0 ORDER BY item_id, expiry_date", conn,
                               parse_dates=["expiry_date", "received_date"])
            shifted = {i: {**f, "rates": f["rates"][offset:]} for i, f in forecasts.items()}
            plan = planning.build_plan(items, usage, deliveries, service_levels=service_levels,
                                       open_pos=open_pos, forecasts=shifted, as_of=day, lots=lots)
            for order_no in pu.draft_suggested_orders(conn, plan, origin="Auto", on_date=day):
                if auto_mode == AUTO_MODES[2]:
                    pu.send_order(conn, order_no, day)
                    report["sent"].append(order_no)
                else:
                    report["drafted"].append(order_no)
    report["end"] = db.today(conn)
    return report
