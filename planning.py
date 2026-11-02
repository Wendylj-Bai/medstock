"""
planning.py — turns raw data (items, usage, deliveries) into decisions.

This is where the app becomes "smart": nobody types in the average demand
or the lead-time variability. We MEASURE them from history, then feed them
into the formulas in inventory_math.py.
"""

import math
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

import inventory_math as im

DATA = Path(__file__).parent / "data"

# Hospital policy: how often may we run out during a replenishment cycle?
# Vital items get the highest protection.
DEFAULT_SERVICE_LEVELS = {"V": 0.99, "E": 0.95, "D": 0.90}

# ABC x VED matrix, a standard tool in hospital inventory control.
#   Category I   -> tight control, never stock out (all Vital + all A items)
#   Category II  -> normal control
#   Category III -> loose control (cheap and non-critical)
ABC_VED_CATEGORY = {
    "AV": "I", "AE": "I", "AD": "I", "BV": "I", "CV": "I",
    "BE": "II", "CE": "II", "BD": "II",
    "CD": "III",
}


def demand_stats(usage, lookback_days):
    """Average and std. dev. of DAILY usage per item over the last N days.

    Several issues on the same day are added together, and days with no
    usage count as 0 (a quiet day is still a day of demand data).
    """
    end = usage["date"].max()
    if pd.isna(end):
        return pd.DataFrame({"d": pd.Series(dtype=float), "sd": pd.Series(dtype=float)})
    days = pd.date_range(end - pd.Timedelta(days=lookback_days - 1), end)
    daily = (usage[usage["date"] >= days[0]]
             .groupby(["date", "item_id"])["qty_used"].sum()
             .unstack("item_id")
             .reindex(days)
             .fillna(0))
    return pd.DataFrame({"d": daily.mean(), "sd": daily.std()})


def leadtime_stats(deliveries):
    """Average and std. dev. of lead time (days) per item, from past orders."""
    return deliveries.groupby("item_id")["lead_time_days"].agg(L="mean", sL="std", n_orders="count")


def build_plan(items, usage, deliveries, lookback_days=90, service_levels=None,
               review_buffer_days=7, open_pos=None, forecasts=None, as_of=None, lots=None):
    """One row per item with every number needed to decide what to order.

    open_pos: purchase orders placed but not yet received. We compare the
    reorder point with the INVENTORY POSITION = on hand + on order. Otherwise
    the app would keep shouting "order now" for something already ordered.

    forecasts: output of forecasting.forecast_all(). When given, demand comes
    from the forecast instead of the plain average of the last N days:
        d̄  = forecast daily demand over the coming lead time
        σd = forecast error (1.25 × MAD), not the raw ups and downs
        D  = forecast demand over the next 365 days

    as_of: the date the plan is written for (normally "today"). When given,
    the plan also projects each item's usable stock forward day by day FEFO
    over a 90-day horizon, including outstanding purchases, and reports:

        availability_risk      a status independent of the reorder point
        shortage_date          first day projected demand exceeds what we can serve
        projected_short_units  total units short over the 90-day horizon
        unknown_eta            an open order is overdue / undated, so stock may
                               arrive later than promised (or never)
    """
    as_of = pd.Timestamp(as_of or pd.Timestamp(date.today()))
    service_levels = service_levels or DEFAULT_SERVICE_LEVELS
    df = (items
          .join(demand_stats(usage, lookback_days), on="item_id")
          .join(leadtime_stats(deliveries), on="item_id"))
    df[["d", "sd"]] = df[["d", "sd"]].fillna(0)
    # New item with no delivery history yet: borrow its supplier's average
    df["L"] = df["L"].fillna(df.groupby("supplier")["L"].transform("mean")).fillna(7)
    df["sL"] = df["sL"].fillna(0)
    df["n_orders"] = df["n_orders"].fillna(0)

    if open_pos is not None and len(open_pos):
        on_order = open_pos.groupby("item_id")["qty"].sum()
        df["on_order"] = df["item_id"].map(on_order).fillna(0).astype(int)
    else:
        df["on_order"] = 0
    # Expired stock cannot be given to patients, so it does not protect us.
    if "usable" not in df:
        df["usable"] = df["on_hand"]
    df["position"] = df["usable"] + df["on_order"]

    # Annual demand (D) and holding cost (H = i * C)
    df["D"] = df["d"] * 365
    df["method"] = f"Average of last {lookback_days} days"
    for i, r in df.iterrows():
        f = (forecasts or {}).get(r["item_id"])
        if f is None:
            continue
        rates = f["rates"]                                   # forecast for each of the next 365 days
        horizon = max(1, math.ceil(r["L"]))
        df.at[i, "d"] = rates[:horizon].mean()               # demand rate DURING the lead time
        df.at[i, "sd"] = f["sigma_daily"]
        df.at[i, "D"] = rates.sum()
        df.at[i, "method"] = f["method"]
    df["H"] = df["holding_rate"] * df["unit_cost"]

    # ABC on annual dollar value, then combine with VED
    abc = im.abc_classify(df.rename(columns={"D": "annual_demand"})
                          [["item_id", "unit_cost", "annual_demand"]].to_dict("records"))
    abc_df = pd.DataFrame(abc).set_index("item_id")[["annual_value", "share", "cumulative_share", "abc"]]
    df = df.join(abc_df, on="item_id")
    df["abc_ved"] = df["abc"] + df["ved"]
    df["control"] = df["abc_ved"].map(ABC_VED_CATEGORY)

    rows = []
    for r in df.itertuples():
        sl = service_levels[r.ved]
        rop = im.reorder_point(r.d, r.sd, r.L, r.sL, sl)
        q_eoq = im.eoq(r.D, r.ordering_cost, r.H) if r.D > 0 else 0

        # Healthcare rule: never order more than we can use before it expires.
        # Keep a 20% margin of the shelf life.
        q_shelf = r.d * r.shelf_life_days * 0.8
        q = min(q_eoq, q_shelf)
        q_limited_by_expiry = q_shelf < q_eoq

        z = rop["z"]
        sig = rop["sigma_ddlt"]
        fr = im.fill_rate(z, sig, q) if q > 0 and sig > 0 else 1.0
        days_of_supply = r.usable / r.d if r.d > 0 else math.inf

        # Status uses inventory position (on hand + on order):
        # red = at or below reorder point; yellow = will hit it within a week
        if r.position <= rop["rop"]:
            status = "🔴 Order now"
        elif r.position <= rop["rop"] + r.d * review_buffer_days:
            status = "🟡 Order soon"
        else:
            status = "🟢 OK"

        # Recommended order: bring the position up to R + Q.
        # Normally position = R exactly, so this is just Q. If position has dropped
        # BELOW R (big emergency issue, or we reacted late), we also order the shortfall.
        # A hospital never orders more than it can use before the shelf life runs out
        # (a 20% margin), even when that stops one order from reaching the target:
        # order_capped tells the app to suggest staged deliveries or expedited freight.
        target = rop["rop"] + q - r.position if status.startswith("🔴") else 0
        order_cap = math.floor(r.d * r.shelf_life_days * 0.8)
        order_qty = int(min(max(target, 0), order_cap))
        order_capped = status.startswith("🔴") and order_qty < target

        cost = im.total_annual_cost(q, r.D, r.ordering_cost, r.H, r.unit_cost, rop["safety_stock"]) if q > 0 else None
        rows.append({
            "item_id": r.item_id,
            "service_level": sl,
            "z": z,
            "ddlt": rop["ddlt"],
            "sigma_ddlt": sig,
            "safety_stock": rop["safety_stock"],
            "rop": rop["rop"],
            "eoq": q_eoq,
            "q": q,
            "q_limited_by_expiry": q_limited_by_expiry,
            "fill_rate": fr,
            "days_of_supply": days_of_supply,
            "status": status,
            "order_qty": order_qty,
            "order_capped": order_capped,
            "order_value": order_qty * r.unit_cost,
            "annual_cost": cost["total"] if cost else 0,
            "cycle_days": im.cycle_time_days(q, r.D) if r.D > 0 else math.inf,
        })
    df = df.merge(pd.DataFrame(rows), on="item_id")
    risk = availability_risks(df, lots, open_pos, daily_demand_rate(df, forecasts), as_of)
    risk_df = pd.DataFrame.from_records(list(risk.values()), index=list(risk.keys()))
    if "shortage_date" not in risk_df:
        risk_df["shortage_date"] = pd.NaT
    return df.set_index("item_id").join(risk_df, how="left").reset_index()


def daily_demand_rate(plan_df, forecasts=None):
    """Per item: one number (average daily demand) or an array (forecast rates).

    The projection uses the same demand assumption as the reorder math: for
    forecast items the day-by-day rates (e.g. rising into flu season), for
    everything else the plain average d̄.
    """
    out = {}
    for r in plan_df.itertuples():
        f = (forecasts or {}).get(r.item_id)
        out[r.item_id] = f["rates"] if f is not None else r.d
    return out


def availability_risks(plan_df, lots, open_pos, demand, as_of, horizon=90):
    """Project usable stock forward day by day (FEFO) and score the risk.

    Returns {item_id: {"availability_risk", "shortage_date", "projected_short_units", "unknown_eta"}}.

    Outstanding purchases are added on the day they actually arrive: only a
    line the vendor has already SHIPPED is trusted to arrive on its arrive_date;
    everything else is only as good as its promised expected_date. An overdue
    promise with no ship date cannot be assumed to arrive, so its item is
    flagged unknown_eta and NO receipt is counted until a reliable date exists.
    A receipt planned for as_of itself does not erase a shortage at as_of: stock
    you do not physically have today cannot be given to a patient today.
    """
    as_of = pd.Timestamp(as_of)
    pool_lots = lots if lots is not None and len(lots) else None
    if pool_lots is not None and "status" in pool_lots.columns:
        pool_lots = pool_lots[pool_lots["status"].astype(str).str.lower() != "quarantined"]
    arrivals, unknown_eta = {}, set()
    open_rows = open_pos if open_pos is not None and not open_pos.empty else pd.DataFrame()
    for po in open_rows.itertuples():
        qty = float(po.qty)
        if not np.isfinite(qty) or qty <= 0:
            continue
        shipped = pd.notna(po.ship_date) and pd.Timestamp(po.ship_date) <= as_of
        if shipped and pd.notna(po.arrive_date):
            day = (pd.Timestamp(po.arrive_date) - as_of).days
            expiry = pd.Timestamp(po.asn_expiry) if pd.notna(po.asn_expiry) else None
        elif pd.notna(po.expected_date):
            day = (pd.Timestamp(po.expected_date) - as_of).days
            expiry = None
        else:
            day = None
        if day is None or day < 0:                        # overdue promise, not shipped: not reliable
            unknown_eta.add(po.item_id)
            continue
        arrivals.setdefault(po.item_id, {}).setdefault(max(day, 1), []).append((qty, expiry))

    out = {}
    for r in plan_df.itertuples():
        usable = float(r.usable) if np.isfinite(r.usable) else float(r.on_hand or 0)
        rate = demand.get(r.item_id, 0.0)
        rate = 0.0 if rate is None else rate
        if pool_lots is not None:
            item_lots = pool_lots[(pool_lots["item_id"] == r.item_id)
                                  & (pool_lots["qty"] > 0)
                                  & (pool_lots["expiry_date"] > as_of)
                                  & (pool_lots["received_date"] <= as_of)]
            pool = sorted(((pd.Timestamp(e), float(q)) for e, q in
                           zip(item_lots["expiry_date"], item_lots["qty"])),
                          key=lambda e_q: (e_q[0], e_q[1]))
        else:
            pool = []
            if usable > 0:
                pool.append((as_of + pd.Timedelta(days=horizon), usable))
        short_units, shortage_date = 0.0, None
        for day in range(1, horizon + 1):
            for qty, expiry in arrivals.get(r.item_id, {}).get(day, []):
                pool.append((expiry if expiry is not None else as_of + pd.Timedelta(days=horizon), qty))
                pool.sort(key=lambda e_q: (e_q[0].value, e_q[1]))
            remaining = rate[day - 1] if not np.isscalar(rate) else float(rate)
            for i, (expiry, qty) in enumerate(pool):
                if remaining <= 0:
                    break
                take = min(qty, remaining)
                pool[i] = (expiry, qty - take)
                remaining -= take
            if remaining > 0:
                short_units += remaining
                shortage_date = shortage_date or (as_of + pd.Timedelta(days=day))
            pool = [(e, q) for e, q in pool if q > 0.5]
        if usable <= 0 and r.ved == "V":
            risk = "🔴 No usable stock"
        elif shortage_date is None:
            risk = "🟢 OK"
        elif shortage_date <= as_of + pd.Timedelta(days=7):
            risk = "🔴 Shortage risk"
        elif shortage_date <= as_of + pd.Timedelta(days=30):
            risk = "🟡 Shortage watch"
        else:
            risk = "🟢 OK"
        out[r.item_id] = {"availability_risk": risk, "shortage_date": shortage_date,
                          "projected_short_units": round(short_units, 1),
                          "unknown_eta": r.item_id in unknown_eta}
    return out


# ---------------------------------------------------------------------------
# Expiry risk: which lots will we NOT manage to use before they expire?
# ---------------------------------------------------------------------------

def cumulative_demand(rate, days):
    """Total expected demand over the next `days` days.

    rate is either one number (same demand every day) or an array with a
    forecast for each future day (e.g. rising into flu season).
    """
    if days <= 0:
        return 0.0
    if np.isscalar(rate):
        return float(rate) * days
    rate = np.asarray(rate, dtype=float)
    days = int(days)
    if days <= len(rate):
        return float(rate[:days].sum())
    return float(rate.sum() + rate[-1] * (days - len(rate)))   # beyond the forecast: last rate


def project_expiry(lots, daily_demand, today):
    """Simulate FEFO usage to estimate waste per lot.

    lots:          DataFrame with item_id, lot_no, expiry_date, qty
    daily_demand:  dict item_id -> d̄ (one number) or an array of daily forecasts
    today:         the date we project from

    Idea: we use lots in expiry order. By a lot's expiry date, total demand
    will be C(days_left). Part of that demand is served by the lots ahead of
    it; whatever demand is left can use this lot. Anything still on the shelf
    on the expiry date becomes waste.

    Example: d̄ = 5/day, lot A = 100 units expiring in 10 days.
             We can use only 5 × 10 = 50 → 50 units will expire.
    """
    out = lots.copy()
    today = pd.Timestamp(today)
    out["days_left"] = (out["expiry_date"] - today).dt.days
    out["projected_use"] = 0.0
    out["projected_waste"] = 0.0
    for item_id, group in out.sort_values(["expiry_date", "lot_id"]).groupby("item_id", sort=False):
        rate = daily_demand.get(item_id, 0)
        rate = 0 if rate is None else rate
        used_so_far = 0.0                   # demand already served by earlier lots
        for idx, lot in group.iterrows():
            demand_until_expiry = cumulative_demand(rate, lot["days_left"])
            used = min(lot["qty"], max(0.0, demand_until_expiry - used_so_far))
            out.loc[idx, "projected_use"] = used
            out.loc[idx, "projected_waste"] = lot["qty"] - used
            used_so_far += used
    out["expiry_band"] = pd.cut(out["days_left"], [-math.inf, 0, 30, 90, math.inf],
                                labels=["Expired", "≤ 30 days", "31-90 days", "> 90 days"])
    return out
