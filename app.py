"""
app.py — MedStock: hospital supply inventory planner (Streamlit web app).

Run:   .venv/bin/streamlit run app.py
Then open the link it prints (usually http://localhost:8501).
"""

import math
import uuid

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from datetime import date
from pathlib import Path

import auth
import db
import events
import forecasting as fc
import homepage
import inventory_math as im
import kpis
import planning
import purchasing as pu
import simulation as sim

st.set_page_config(page_title="MedStock", page_icon="🏥", layout="wide")

_view = st.session_state.get("view", "home")
if _view == "demo" and not auth.current_user():      # the demo needs a signed-in user
    _view = st.session_state["view"] = "login"
if _view == "login":
    auth.render_login()
    st.stop()
if _view != "demo":
    homepage.render_homepage()
    st.stop()


@st.cache_resource
def get_conn():
    return db.connect()


conn = get_conn()
pu.adopt_old_orders(conn)            # one-time upgrade of POs made by an earlier version
TODAY = db.today(conn)               # the real date, or the simulated date once the clock has moved
SIMULATED = TODAY != date.today()
pu.process_vendor_responses(conn, TODAY)   # close orders a disrupted vendor has rejected
items, usage, deliveries, open_pos, lots = db.load_frames(conn, TODAY)


def done(message):
    """Show a success message after the page reloads with the new numbers."""
    st.session_state["flash"] = message
    st.rerun()


if "flash" in st.session_state:
    st.toast(st.session_state.pop("flash"), icon="✅")

# ---------------------------------------------------------------------------
# Sidebar: the policy knobs a hospital supply manager would control
# ---------------------------------------------------------------------------
s1, s2 = st.sidebar.columns(2)
if s1.button("Back to project home", key="back_home"):
    st.session_state["view"] = "home"
    st.rerun()
if s2.button("Sign out", key="sign_out", help=f"Signed in as {auth.current_user()}"):
    auth.sign_out()
    st.rerun()
st.sidebar.title("🏥 MedStock")
st.sidebar.caption("Hospital supply inventory planner")
st.sidebar.subheader("🕒 Simulation clock")
st.sidebar.markdown(f"**Today: {TODAY:%a, %b %d, %Y}**" + (" *(simulated)*" if SIMULATED else ""))
k1, k2, k3 = st.sidebar.columns(3)
step_1 = k1.button("+1 day", help="Simulate one day: wards use stock, vendors ship, deliveries arrive")
step_7 = k2.button("+7 days", help="Simulate a week")
step_next = k3.button("🚚 Next", help="Jump to the day the next delivery arrives")
with st.sidebar.expander("Simulation settings"):
    auto_mode = st.radio("Automatic reordering", sim.AUTO_MODES, key="auto_mode",
                         help="What MedStock does each simulated evening for 🔴 items. Professional systems "
                              "usually create drafts that a buyer approves; low-risk items are often fully automatic.")
    auto_receive = st.checkbox("Auto-receive deliveries at the dock", value=True, key="auto_receive",
                               help="Receive each delivery exactly as the vendor's ship notice (ASN) says. "
                                    "Turn off to receive by hand and check quantities, lots and expiry dates.")
    random_events = st.checkbox("Random events (recalls, vendor disruptions)", value=False, key="random_events",
                                help="Each simulated day there is a small chance that a vendor cannot supply "
                                     "for 1-4 weeks, or that a manufacturer recalls a lot on your shelf.")
    st.caption("The clock buttons change your data: they record simulated issues, orders and receipts.")
    really = st.checkbox("I want to erase everything", key="reset_ok")

    def reset_all():          # runs before the page is redrawn, so it may untick the checkbox
        db.reset(conn)
        st.cache_data.clear()
        st.session_state.pop("sim_report", None)
        st.session_state["reset_ok"] = False
        st.session_state["flash"] = "All data erased and the sample data reloaded. The clock is back to the real date."

    st.button("🔄 Reset to fresh sample data", disabled=not really, on_click=reset_all)
st.sidebar.subheader("Service level by criticality (VED)")
sl_v = st.sidebar.slider("Vital items", 0.80, 0.999, 0.99, 0.001, format="%.3f")
sl_e = st.sidebar.slider("Essential items", 0.80, 0.999, 0.95, 0.005, format="%.3f")
sl_d = st.sidebar.slider("Desirable items", 0.50, 0.99, 0.90, 0.01, format="%.2f")
st.sidebar.subheader("Demand forecast")
SIMPLE = "Simple average (no forecast)"
fc_method = st.sidebar.selectbox(
    "Method", ["Auto (best per item)", *fc.METHODS, SIMPLE],
    help="Auto backtests every method on the last 12 months and uses the one with the lowest MAD.")
lookback = 90
if fc_method == SIMPLE:
    lookback = st.sidebar.select_slider("Average over the last … days", options=[30, 60, 90, 180, 365], value=90)
with st.sidebar.expander("Smoothing constants"):
    fc_params = {
        "ma_n": st.number_input("Moving average N (months)", 2, 12, fc.DEFAULT_PARAMS["ma_n"]),
        "alpha": st.slider("α level", 0.05, 0.9, fc.DEFAULT_PARAMS["alpha"], 0.05),
        "beta": st.slider("β trend", 0.05, 0.9, fc.DEFAULT_PARAMS["beta"], 0.05),
        "gamma": st.slider("γ seasonality", 0.05, 0.9, fc.DEFAULT_PARAMS["gamma"], 0.05),
    }


if step_1 or step_7 or step_next:
    days = 1 if step_1 else 7
    if step_next:
        nxt = sim.next_arrival(conn)
        days = min(60, max(1, (nxt - TODAY).days)) if nxt else 0
    if days == 0:
        st.sidebar.warning("No deliveries are on their way. Send a purchase order first (🛒 Purchasing).")
    else:
        with st.spinner(f"Simulating {days} day(s)…"):
            report = sim.advance(conn, days, {"V": sl_v, "E": sl_e, "D": sl_d},
                                 "Auto" if fc_method.startswith("Auto") or fc_method == SIMPLE else fc_method,
                                 fc_params, auto_mode, auto_receive, random_events=random_events)
        st.session_state["sim_report"] = report
        done(f"Simulated {days} day(s). Today is now {report['end']:%b %d, %Y}.")


@st.cache_data(show_spinner="Forecasting demand…")
def get_forecasts(usage, today, method, params):
    return fc.forecast_all(usage, today, method, params)


forecasts = get_forecasts(usage, TODAY, "Auto" if fc_method.startswith("Auto") else fc_method, fc_params)
plan = planning.build_plan(items, usage, deliveries, lookback, {"V": sl_v, "E": sl_e, "D": sl_d},
                           open_pos=open_pos, forecasts=None if fc_method == SIMPLE else forecasts,
                           as_of=TODAY, lots=lots)
plan = plan.join(pu.order_vendors(conn, plan, TODAY))      # primary vendor, or backup if it is disrupted
item_labels = dict(zip(plan["item_id"], plan["item_id"] + " · " + plan["name"]))
recall_list = events.recalls(conn)
outage_list = events.outages(conn, TODAY)
active_outages = outage_list[outage_list["state"] == "🔴 Active"]

# Expiry projection for every lot: FEFO simulation using each item's day-by-day demand forecast
daily_demand = {i: (forecasts[i]["rates"] if fc_method != SIMPLE and i in forecasts else d)
                for i, d in zip(plan["item_id"], plan["d"])}
lot_risk = planning.project_expiry(lots, daily_demand, TODAY)
lot_risk = lot_risk.merge(plan[["item_id", "name", "unit", "unit_cost", "ved"]], on="item_id")
lot_risk["value"] = lot_risk["qty"] * lot_risk["unit_cost"]
lot_risk["waste_value"] = lot_risk["projected_waste"] * lot_risk["unit_cost"]

# Seasonal outlook: forecast demand over the next 90 days vs. what we used in the last 30 days
OUTLOOK_COLUMNS = ["item_id", "method", "last_30_days", "next_30_days", "next_90_days", "peak_month", "peak_rate"]
recent_30 = planning.demand_stats(usage, 30)["d"]
outlook = pd.DataFrame([{
    "item_id": i, "method": f["method"],
    "last_30_days": recent_30.get(i, 0.0),
    "next_30_days": f["rates"][:30].mean(),
    "next_90_days": f["rates"][:90].mean(),
    "peak_month": f["future"][:12].idxmax(),
    "peak_rate": f["future"][:12].max(),
} for i, f in forecasts.items()], columns=OUTLOOK_COLUMNS)
outlook["change_90"] = outlook["next_90_days"] / outlook["last_30_days"].where(outlook["last_30_days"] > 0) - 1
outlook = outlook.merge(plan[["item_id", "name", "ved", "unit"]], on="item_id")
rising = outlook[outlook["change_90"] >= 0.15].sort_values("change_90", ascending=False) if len(outlook) else outlook

po_list = pu.orders(conn, TODAY)
stockouts = pd.read_sql("SELECT s.*, i.name, i.ved, i.unit FROM stockouts s JOIN items i USING (item_id)", conn,
                        parse_dates=["date"])

# What happened during the last simulation run
rep = st.session_state.get("sim_report")
if rep:
    with st.expander(f"🕒 Simulation report: {rep['start']:%b %d} → {rep['end']:%b %d} ({rep['days']} days)",
                     expanded=True):
        m = st.columns(5)
        m[0].metric("Units requested", f"{rep['demand']:,}")
        m[1].metric("Filled from the shelf", f"{rep['issued'] / rep['demand']:.1%}" if rep["demand"] else "—",
                    help="Share of requested units that were available (the fill rate, slides 205-207).")
        so = pd.DataFrame(rep["stockouts"])
        m[2].metric("Stockout events", len(so),
                    help="Days on which an item could not fully supply what the wards asked for.")
        m[3].metric("Deliveries received", len({r["order_no"] for r in rep["received"]}))
        m[4].metric("POs sent / drafted", f"{len(rep['sent'])} / {len(rep['drafted'])}")
        if len(so):
            worst = (so.groupby(["item", "ved"]).agg(days=("date", "count"), units_short=("short", "sum"))
                     .reset_index().sort_values(["ved", "units_short"], key=lambda c: c.map({"V": 0, "E": 1, "D": 2})
                                                if c.name == "ved" else -c))
            st.error("Stockouts: " + ", ".join(f"**{r.item}** ({r.ved}, {r.units_short:,} short over {r.days} day(s))"
                                               for r in worst.head(6).itertuples()))
        for ev in rep.get("events", []):
            st.warning(f"**{ev['date']:%b %d}**: {ev['event']}. See 🚨 Recalls & disruptions.")
        if rep["received"]:
            st.dataframe(pd.DataFrame(rep["received"]), hide_index=True, width="stretch")
        if rep["drafted"]:
            st.info(f"📝 Drafts waiting for your approval: {', '.join(rep['drafted'])} (🛒 Purchasing).")
        if st.button("Close report"):
            st.session_state.pop("sim_report")
            st.rerun()

(tab_dash, tab_kpi, tab_buy, tab_move, tab_risk, tab_fc, tab_exp, tab_item, tab_hist, tab_abc, tab_calc,
 tab_help) = st.tabs(
    ["📋 Dashboard", "📊 KPIs", "🛒 Purchasing", "📦 Stock movements", "🚨 Recalls & disruptions", "📈 Forecast",
     "⏳ Expiry", "🔎 Item detail", "📜 History", "🅰️ ABC-VED analysis", "🧮 Calculators", "📖 Help"])

# ---------------------------------------------------------------------------
# Tab: Help — the user guide (docs/USER_GUIDE.md), shown inside the app
# ---------------------------------------------------------------------------
with tab_help:
    guide = Path(__file__).parent / "docs" / "USER_GUIDE.md"
    if guide.exists():
        st.markdown(guide.read_text(encoding="utf-8"))
    else:
        st.info("The user guide (docs/USER_GUIDE.md) was not found.")
    st.caption("Technical details (formulas, data model, design decisions): docs/HOW_IT_WORKS.md")

# ---------------------------------------------------------------------------
# Tab 1: Dashboard — what needs ordering today?
# ---------------------------------------------------------------------------
with tab_dash:
    st.header("Today's reorder dashboard")
    red = plan[plan["status"].str.startswith("🔴")]
    yellow = plan[plan["status"].str.startswith("🟡")]
    vital_red = red[red["ved"] == "V"]
    at_risk = plan[plan["availability_risk"] != "🟢 OK"]
    vital_at_risk = at_risk[at_risk["ved"] == "V"]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🔴 Order now", len(red))
    c2.metric("🟡 Order soon", len(yellow))
    c3.metric("Vital items at risk", len(vital_at_risk),
              help="Vital (V) items flagged by the availability projection: zero usable stock, or their "
                   "usable stock runs out before the next reliable delivery. This is about what we can "
                   "physically give patients, independent of the reorder point.")
    c4.metric("Inventory value on hand", f"${(plan['on_hand'] * plan['unit_cost']).sum():,.0f}")

    if len(vital_at_risk):
        st.error("**Vital items at risk:** " + ", ".join(
            f"{r.name} ({r.days_of_supply:.0f} days of supply left)" for r in vital_at_risk.itertuples())
            + ". " + ("Some have no usable stock at all; " if (vital_at_risk["usable"] == 0).any() else "")
            + "Check the reorder plan and any open purchases below.")
    for o in active_outages.itertuples():
        n_items = int((plan["supplier"] == o.supplier).sum())
        st.error(f"🏭 **{o.supplier} cannot supply** until {pd.Timestamp(o.end_date):%b %d} ({o.reason}). "
                 f"New orders for its {n_items} item(s) go to their backup vendor at +{pu.BACKUP_PREMIUM:.0%}. "
                 "See 🚨 Recalls & disruptions.")
    new_recalls = recall_list[pd.to_datetime(recall_list["date"]) > pd.Timestamp(TODAY) - pd.Timedelta(days=14)]
    for r in new_recalls.itertuples():
        st.error(f"🚨 **Recall (Class {r.recall_class})**: lot {r.lot_no} of {r.name}, {r.reason}. "
                 f"{r.qty_removed:,} pulled from the shelf; wards that received it: {r.wards}.")
    if len(po_list):
        at_dock = po_list[po_list["stage"] == "ARRIVED"]
        late = po_list[po_list["late"]]
        if len(at_dock):
            st.warning(f"📦 {len(at_dock)} deliver{'y is' if len(at_dock) == 1 else 'ies are'} waiting at the "
                       f"receiving dock ({', '.join(at_dock['order_no'])}). Receive them in 🛒 Purchasing: "
                       "stock on the dock cannot be issued.")
        if len(late):
            st.warning("⏰ Late vendor deliveries: " + ", ".join(
                f"{r.order_no} from {r.supplier} (promised {pd.Timestamp(r.promised_date):%b %d})"
                for r in late.itertuples()) + ". This is why safety stock covers lead-time variability (σL).")
    recent_so = stockouts[stockouts["date"] > pd.Timestamp(TODAY) - pd.Timedelta(days=30)]
    if len(recent_so):
        by_item = recent_so.groupby(["name", "ved"])["qty_short"].sum().reset_index()
        st.error(f"🚫 Stockouts in the last 30 days: {len(recent_so)} event(s). " + ", ".join(
            f"{r.name} ({r.ved}, {r.qty_short:,} short)" for r in by_item.itertuples()))
    expired = lot_risk[lot_risk["days_left"] <= 0]
    soon = lot_risk[(lot_risk["days_left"] > 0) & (lot_risk["days_left"] <= 30)]
    parts = []
    if len(expired):
        parts.append(f"{len(expired)} expired lot(s) still on the shelf (${expired['value'].sum():,.0f})")
    if len(soon):
        parts.append(f"{len(soon)} lot(s) expiring within 30 days")
    if parts:
        st.warning("⏳ " + " and ".join(parts) + ". See the ⏳ Expiry tab.")
    if len(rising):
        names = ", ".join(f"{r.name} (+{r.change_90:.0%})" for r in rising.head(5).itertuples())
        more = f" and {len(rising) - 5} more" if len(rising) > 5 else ""
        st.info(f"📈 Demand is forecast to rise over the next 90 days for {len(rising)} items: {names}{more}. "
                "Reorder points already include this rise. See the 📈 Forecast tab.")

    STATUSES = ["🔴 Order now", "🟡 Order soon", "🟢 OK"]
    RISKS = ["🔴 No usable stock", "🔴 Shortage risk", "🟡 Shortage watch", "🟢 Enough stock"]
    VED_NAMES = {"V": "V - Vital", "E": "E - Essential", "D": "D - Desirable"}
    SORTS = {"Reorder status (🔴 → 🟢)": ["status_rank", "ved_rank", "days_of_supply"],
             "Reorder status (🟢 → 🔴)": ["status_rank_desc", "ved_rank", "days_of_supply"],
             "Availability risk (worst first)": ["risk_rank", "ved_rank", "days_of_supply"],
             "Criticality (Vital first)": ["ved_rank", "status_rank", "days_of_supply"],
             "Days of supply (lowest first)": ["days_of_supply", "ved_rank"],
             "Order value (highest first)": ["order_value", "ved_rank"]}
    f1, f2, f3, f4 = st.columns(4)
    status_filter = f1.multiselect("Reorder status", STATUSES, placeholder="All statuses", key="dash_status",
                                   help="🔴/🟡/🟢 from the reorder point: is it time to place an order?")
    risk_filter = f2.multiselect("Availability", RISKS, placeholder="All", key="dash_risk",
                                 help="Will usable stock last the next 90 days? (Can be 🔴 even when an order "
                                      "is already on the way, if it arrives too late.)")
    ved_filter = f3.multiselect("Criticality", list(VED_NAMES), format_func=VED_NAMES.get,
                                placeholder="All items", key="dash_ved")
    sort_by = f4.selectbox("Sort by", list(SORTS), key="dash_sort")
    view = plan.assign(availability_risk=plan["availability_risk"].replace({"🟢 OK": "🟢 Enough stock"}))
    view = view.assign(status_rank=view["status"].map({s: i for i, s in enumerate(STATUSES)}),
                       status_rank_desc=-view["status"].map({s: i for i, s in enumerate(STATUSES)}),
                       risk_rank=view["availability_risk"].map({s: i for i, s in enumerate(RISKS)}).fillna(9),
                       ved_rank=view["ved"].map({"V": 0, "E": 1, "D": 2}))
    if status_filter:
        view = view[view["status"].isin(status_filter)]
    if risk_filter:
        view = view[view["availability_risk"].isin(risk_filter)]
    if ved_filter:
        view = view[view["ved"].isin(ved_filter)]
    view = view.sort_values(SORTS[sort_by], ascending=[c != "order_value" for c in SORTS[sort_by]])
    hidden_vital_risk = plan[(plan["ved"] == "V") & plan["availability_risk"].str.startswith("🔴")
                             & ~plan.index.isin(view.index)]
    st.caption(f"Showing **{len(view)} of {len(plan)}** items." + (
        f" ⚠️ {len(hidden_vital_risk)} Vital item(s) with 🔴 availability are hidden by your filters."
        if len(hidden_vital_risk) else "") +
        " · **Reorder status** = time to place an order? · **Availability** = will usable stock last 90 days? "
        "(🟢 reorder status with 🔴 availability means an order is already coming, but may arrive too late.)")
    st.dataframe(
        view[["status", "availability_risk", "item_id", "name", "ved", "abc", "on_hand", "usable", "on_order",
              "rop", "safety_stock", "days_of_supply", "order_qty", "order_value", "supplier"]],
        hide_index=True, width="stretch",
        column_config={
            "availability_risk": st.column_config.TextColumn(
                "Availability", help="Projected from current usable stock over the next 90 days, FEFO. "
                                     "Independent of the reorder point."),
            "status": "Reorder status", "ved": "VED", "abc": "ABC", "on_hand": "On hand", "on_order": "On order",
            "usable": st.column_config.NumberColumn("Usable", help="On hand minus expired lots"),
            "rop": st.column_config.NumberColumn("Reorder point", format="%.0f"),
            "safety_stock": st.column_config.NumberColumn("Safety stock", format="%.0f"),
            "days_of_supply": st.column_config.NumberColumn("Days of supply", format="%.1f"),
            "order_qty": st.column_config.NumberColumn("Order qty", format="%d"),
            "order_value": st.column_config.NumberColumn("Order value", format="$%,.0f"),
        })
    capped = plan[plan["order_capped"]]
    cap_note = ""
    if len(capped):
        cap_note = (" · ⚠️ " + ", ".join(capped["item_id"].head(3)) +
                    " capped by ~80% of the shelf life: one order cannot reach the full target. "
                    "Plan **staged deliveries** or **expedited freight**, and re-check after the first receipt.")
    st.caption(f"Total of suggested orders: **${plan['order_value'].sum():,.0f}**. "
               "🔴 = usable + on order ≤ reorder point · 🟡 = will reach it within ~7 days." + cap_note)

    st.subheader("Suggested purchase orders by vendor")
    drafted = pu.items_in_drafts(conn)
    to_order = red[(red["order_qty"] > 0) & ~red["item_id"].isin(drafted)]
    if drafted:
        st.info(f"📝 {len(set(drafted.values()))} draft PO(s) with {len(drafted)} item(s) are waiting for approval "
                "in 🛒 Purchasing. A draft is not an order yet: the vendor has not received it.")
    if len(to_order):
        to_order = to_order.assign(order_value=np.where(to_order["order_vendor"] != to_order["supplier"],
                                                        to_order["order_value"] * (1 + pu.BACKUP_PREMIUM),
                                                        to_order["order_value"]),
                                   name=np.where(to_order["order_vendor"] != to_order["supplier"],
                                                 to_order["name"] + " (backup)", to_order["name"]))
        to_order = to_order[~to_order["order_vendor"].isin(active_outages["supplier"])]
        sugg = (to_order.groupby("order_vendor")
                .agg(lines=("name", "count"), items=("name", ", ".join), value=("order_value", "sum")).reset_index()
                .rename(columns={"order_vendor": "supplier"}))
        sugg["freight"] = [pu.freight(v, x) for v, x in zip(sugg["supplier"], sugg["value"])]
        st.dataframe(sugg, hide_index=True, width="stretch", column_config={
            "supplier": "Vendor", "lines": "Lines",
            "value": st.column_config.NumberColumn("PO value", format="$%,.0f"),
            "freight": st.column_config.NumberColumn("Freight", format="$%,.0f",
                                                     help="Vendor's freight charge; free above its threshold")})
        if sugg.empty:
            st.warning("Items need ordering, but their primary AND backup vendors are both disrupted. "
                       "Watch stock closely and consider substitutes until a vendor is back.")
        elif st.button(f"📝 Prepare {len(sugg)} draft purchase order(s), one per vendor", type="primary"):
            made = pu.draft_suggested_orders(conn, plan)
            done(f"Drafted {', '.join(made)} with the suggested quantities. Review and send them in 🛒 Purchasing.")
        st.caption("Quantities, prices and vendors are filled in for you. You review, adjust and approve them in "
                   "🛒 Purchasing before anything is sent to a vendor.")
    elif not drafted:
        st.success("Nothing to order right now. Everything at risk is already on order.")

    st.subheader("Measured fill rate from logged requests")
    st.caption("These are ACTUAL requests logged in this app (manual ward issues and simulated demand) since it "
               "was set up — not synthetic history. The table shows what was served vs. what was short. Compare "
               "it with the *predicted* fill rate shown in 🔎 Item detail (from the service level).")
    requests = pd.read_sql("SELECT * FROM demand_requests", conn)
    if requests.empty:
        st.info("No ward requests have been logged yet. Record them in 📦 Stock movements → Issue to ward, or run "
                "the simulation; every request (served or short) is counted here.")
    else:
        measured = requests.groupby("item_id").agg(requests=("requested", "sum"),
                                                   served=("filled", "sum"), short=("short", "sum")).reset_index()
        measured = measured.merge(plan[["item_id", "name", "ved", "unit"]], on="item_id")
        measured["fill_rate"] = measured["served"] / measured["requests"]
        st.dataframe(measured.sort_values("fill_rate")[["name", "ved", "unit", "requests", "served", "short",
                                                        "fill_rate"]], hide_index=True, width="stretch",
                     column_config={
                         "ved": "VED", "requests": "Requested", "served": "Served",
                         "short": "Short (stockouts)",
                         "fill_rate": st.column_config.ProgressColumn("Measured fill rate", format="percent",
                                                                      min_value=0, max_value=1)})
        overall = requests["filled"].sum() / requests["requested"].sum()
        st.metric("Overall measured fill rate", f"{overall:.1%}",
                  help="Served ÷ requested across all logged requests.")

# ---------------------------------------------------------------------------
# Tab: Stock movements — record what physically happens in the storeroom
# ---------------------------------------------------------------------------
def run(action, *args, **kwargs):
    """Call a db function; show a friendly error instead of crashing."""
    try:
        return action(conn, *args, **kwargs), None
    except db.StockError as e:
        st.error(str(e))
        return None, e


def pick_item(key):
    return st.selectbox("Item", plan["item_id"], format_func=item_labels.get, key=key)


def item_row(item_id):
    return plan[plan["item_id"] == item_id].iloc[0]


# ---------------------------------------------------------------------------
# Tab: KPIs — is inventory management working, and is it getting better?
# ---------------------------------------------------------------------------
def pct(x, digits=1):
    return "—" if x is None or pd.isna(x) else f"{x:.{digits}%}"


with tab_kpi:
    st.header("Key performance indicators")
    PERIODS = {"Last 30 days": 30, "Last 90 days": 90, "Last 365 days": 365}
    period = st.radio("Period", list(PERIODS), index=1, horizontal=True, key="kpi_period")
    k_start = TODAY - pd.Timedelta(days=PERIODS[period] - 1)
    k = kpis.compute(conn, k_start, TODAY)
    st.caption(f"{k_start:%b %d, %Y} → {TODAY:%b %d, %Y}. Stockouts are only recorded since the app started "
               "logging requests, and inventory KPIs start when the stock ledger starts"
               + (f" ({k['inventory_since']:%b %d, %Y})." if k["inventory_since"] else "."))

    st.subheader("Service: are patients getting what they need?")
    c = st.columns(4)
    c[0].metric("Fill rate", pct(k["fill_rate"], 2), help="Units served ÷ units requested. Target 98%+.")
    c[1].metric("Vital fill rate", pct(k["fill_by_ved"]["V"], 2), help="Same, Vital items only. Target 99.5%+.")
    c[2].metric("Stockout events", k["stockout_events"], help="Item-days on which a request could not be filled in full")
    c[3].metric("…of which Vital", k["vital_stockout_events"])

    st.subheader("Money: how much is tied up, and how much is lost?")
    c = st.columns(4)
    c[0].metric("Average inventory", f"${k['avg_inventory']:,.0f}" if k["avg_inventory"] else "—",
                help="Average dollar value on the shelf over the period")
    c[1].metric("Inventory turns (per year)", f"{k['turns']:.1f}" if k["turns"] else "—",
                help="Yearly value issued ÷ average inventory. Higher = leaner. Hospital supplies often run 8-12.")
    c[2].metric("Days on hand", f"{k['days_on_hand']:.0f}" if k["days_on_hand"] else "—",
                help="How many days the average stock would last at the current usage rate")
    c[3].metric("Waste (expiry, damage, recalls)", f"${k['waste_total']:,.0f}",
                help="Written-off value plus stock pulled by recalls")
    if k["waste_total"]:
        parts = [f"{r}: ${v:,.0f}" for r, v in k["waste_by_reason"].items()]
        if k["recall_value"]:
            parts.append(f"Recalls: ${k['recall_value']:,.0f}")
        st.caption("Waste by reason: " + " · ".join(parts))

    st.subheader("Supply: are vendors reliable?")
    c = st.columns(4)
    c[0].metric("On-time deliveries", pct(k["on_time"], 0), help="Arrived by the vendor's promised date")
    c[1].metric("Vendor fill rate", pct(k["vendor_fill"]), help="Units confirmed ÷ units ordered (backorders lower it)")
    c[2].metric("Orders rejected", k["rejected_orders"], help="Rejected by a vendor during a supply disruption")
    c[3].metric("Spend with backup vendors", pct(k["backup_share"]),
                help=f"Share of purchasing spend (${k['spend']:,.0f}) placed with a backup vendor at a higher price")
    st.caption(f"{k['recalls']} recall(s) and {k['outage_days']} vendor-disruption day(s) in this period.")
    if not k["vendors"].empty:
        st.dataframe(k["vendors"], hide_index=True, width="stretch", column_config={
            "vendor": "Vendor", "deliveries": "Deliveries",
            "on_time": st.column_config.ProgressColumn("On time", format="percent", min_value=0, max_value=1),
            "avg_lead_time": st.column_config.NumberColumn("Avg lead time (d)", format="%.1f"),
            "fill_rate": st.column_config.ProgressColumn("Fill rate", format="percent", min_value=0, max_value=1),
            "rejected_orders": "Rejected orders"})

    st.subheader("Trend by week")
    wk = kpis.weekly(conn, k_start, TODAY)
    if wk.empty:
        st.info("No activity in this period yet. Move the 🕒 clock forward to generate some.")
    else:
        g1, g2 = st.columns(2)
        fig = px.line(wk, x="week", y="fill_rate", markers=True, title="Fill rate")
        fig.update_layout(yaxis_tickformat=".1%", height=300, margin=dict(t=40, b=10))
        g1.plotly_chart(fig, width="stretch")
        if "inventory_value" in wk and wk["inventory_value"].notna().any():
            fig = px.line(wk.dropna(subset=["inventory_value"]), x="week", y="inventory_value", markers=True,
                          title="Inventory value at week end")
            fig.update_layout(yaxis_tickprefix="$", height=300, margin=dict(t=40, b=10))
            g2.plotly_chart(fig, width="stretch")
        st.caption("Try it: raise or lower the Vital service level in the sidebar, simulate a few weeks, and "
                   "watch fill rate and inventory value move in opposite directions. That is the trade-off "
                   "safety stock manages.")

# ---------------------------------------------------------------------------
# Tab: Recalls & disruptions — when the supply chain goes wrong
# ---------------------------------------------------------------------------
with tab_risk:
    st.header("Recalls & vendor disruptions")
    st.caption("Fictional, simulated events. Use them to see how the reorder system reacts: a recall removes "
               "stock at once, and a disruption forces orders to a backup vendor. Turn on **Random events** in "
               "the sidebar's Simulation settings to let them happen on their own.")

    st.subheader("🚨 Product recalls")
    st.markdown("A manufacturer (or the FDA) recalls a **lot**. Every unit still on the shelf is pulled, wards "
                "that already received it are notified, and incoming deliveries of that lot are refused.")
    lots_on_hand = lots[lots["qty"] > 0].merge(plan[["item_id", "name", "ved"]], on="item_id")
    lots_on_hand = lots_on_hand[~lots_on_hand["lot_no"].isin(recall_list["lot_no"])]
    with st.form("recall_form"):
        lot_opts = list(dict.fromkeys(lots_on_hand["lot_no"]))
        lot_desc = {r.lot_no: f"{r.lot_no} · {r.name} ({r.ved}) · {int(r.qty):,} on hand · exp. {r.expiry_date:%b %Y}"
                    for r in lots_on_hand.itertuples()}
        f1, f2 = st.columns([2, 1])
        lot_pick = f1.selectbox("Lot to recall", lot_opts, format_func=lot_desc.get, key="recall_lot")
        cls = f2.selectbox("Recall class", list(events.RECALL_CLASSES), index=1,
                           format_func=events.RECALL_CLASSES.get, key="recall_class")
        reason = st.selectbox("Reason", events.RECALL_REASONS, key="recall_reason")
        r1, r2 = st.columns(2)
        do_recall = r1.form_submit_button("🚨 Issue recall for this lot", type="primary", disabled=not lot_opts)
        do_random = r2.form_submit_button("🎲 Simulate a random manufacturer recall")
    if do_recall or do_random:
        res, err = (run(events.recall_lot, lot_pick, cls, reason) if do_recall else run(events.random_recall))
        if not err and res:
            wards = ", ".join(f"{w} ({q})" for w, q in res["wards"].items()) or "none yet"
            done(f"Recall of lot {res['lot_no']} ({item_labels[res['item_id']]}): {res['removed']:,} units "
                 f"(${res['value']:,.0f}) pulled. Wards to notify: {wards}.")
        elif not err:
            st.info("No lot on the shelf to recall.")
    if recall_list.empty:
        st.info("No recalls yet.")
    else:
        st.dataframe(recall_list[["date", "lot_no", "name", "ved", "recall_class", "reason", "qty_removed",
                                  "value_removed", "wards", "origin"]], hide_index=True, width="stretch",
                     column_config={"lot_no": "Lot", "name": "Item", "ved": "VED", "recall_class": "Class",
                                    "qty_removed": "Pulled from shelf",
                                    "value_removed": st.column_config.NumberColumn("Value lost", format="$%,.0f"),
                                    "wards": "Already issued to (notify)", "origin": "Source"})
        st.caption("What happens next: usable stock dropped, so the item may now be 🔴 on the 📋 Dashboard and "
                   "get reordered. Full movement history of any lot: 📜 History → Lot trace.")

    st.subheader("🏭 Vendor disruptions")
    st.markdown("A vendor cannot supply for a while (plant shutdown, shortage, storm, cyberattack). Orders it "
                "receives are **rejected**, and new orders for its items go to each item's **backup vendor** "
                f"(+{pu.BACKUP_PREMIUM:.0%} price, its own lead time). Items already on the way still arrive.")
    with st.form("outage_form"):
        f1, f2, f3 = st.columns([2, 1, 2])
        o_vendor = f1.selectbox("Vendor", list(pu.VENDORS), key="outage_vendor")
        o_days = f2.number_input("Days", 1, 90, 14, key="outage_days")
        o_reason = f3.selectbox("Reason", events.OUTAGE_REASONS, key="outage_reason")
        o1, o2 = st.columns(2)
        do_outage = o1.form_submit_button("🏭 Start disruption", type="primary")
        do_random_outage = o2.form_submit_button("🎲 Simulate a random disruption")
    if do_outage or do_random_outage:
        res, err = (run(events.start_outage, o_vendor, int(o_days), o_reason) if do_outage
                    else run(events.random_outage))
        if not err and res is not None:
            done(f"{o_vendor} cannot supply until {res:%b %d}." if do_outage else
                 f"{res['supplier']} cannot supply for {res['days']} days.")
        elif not err:
            st.info("Every vendor is already disrupted.")
    if outage_list.empty:
        st.info("No vendor disruptions yet.")
    else:
        st.dataframe(outage_list[["state", "supplier", "start_date", "end_date", "days", "reason", "origin"]],
                     hide_index=True, width="stretch", column_config={
                         "state": "Status", "supplier": "Vendor", "start_date": "From", "end_date": "Until",
                         "origin": "Source"})
        for o in active_outages.itertuples():
            affected = plan[plan["supplier"] == o.supplier]
            st.markdown(f"**{o.supplier}**: {len(affected)} item(s) switch to their backup vendor: " + ", ".join(
                f"{r.name} → {r.backup_supplier}" for r in affected.itertuples()))
            if st.button(f"✅ {o.supplier} is supplying again", key=f"end_outage_{o.outage_id}"):
                _, err = run(events.end_outage, o.supplier)
                if not err:
                    done(f"{o.supplier} is back. New orders go to it again.")

# ---------------------------------------------------------------------------
# Tab: Purchasing — vendor purchase orders, from draft to delivery (vendors are simulated)
# ---------------------------------------------------------------------------
def stage_bar(current):
    """📝 Draft → 📤 Sent → … with the current stage in bold."""
    if current == "CANCELLED":
        return "❌ **Cancelled**"
    now = pu.STAGES.index(current)
    parts = []
    for n, name in enumerate(pu.STAGES):
        label = pu.STAGE_LABELS[name].split(" (")[0]
        parts.append(f"**{label}**" if n == now else label if n < now else f"<span style='opacity:.35'>{label}</span>")
    return " → ".join(parts)


def vendor_card(name):
    v = pu.VENDORS[name]
    return (f"**{name}**  \n{v['address']}  \nContact: {v['contact']} · {v['email']} · {v['phone']}  \n"
            f"Our account no. {v['account_no']} · Orders via **{v['method']}** · Terms {v['terms']}  \n"
            f"Ship via {v['ship_via']} · Quoted lead time **{v['quoted_days']} days** · "
            f"Minimum order ${v['min_order']:,} · Free freight over ${v['free_freight_over']:,} "
            f"(else ${v['freight_fee']:,})")


def order_summary(supplier, subtotal):
    v = pu.VENDORS[supplier]
    fr = pu.freight(supplier, subtotal)
    st.markdown(f"Subtotal **${subtotal:,.2f}** · Freight ${fr:,.2f} · **Total ${subtotal + fr:,.2f}**")
    if 0 < subtotal < v["min_order"]:
        st.warning(f"Below {supplier}'s minimum order of ${v['min_order']:,}. The vendor may reject it or charge "
                   "a small-order fee. Consider adding items that will need ordering soon (🟡).")
    elif fr and subtotal >= 0.5 * v["free_freight_over"]:
        st.caption(f"💡 ${v['free_freight_over'] - subtotal:,.0f} more and freight is free.")


with tab_buy:
    st.header("Purchasing")
    st.caption("One purchase order (PO) per vendor, one line per item. MedStock fills in vendor, quantities and "
               "prices; you review and approve. Vendors are **fictional** and respond on their own schedule: move "
               "time forward with the 🕒 simulation clock in the sidebar.")
    stage_counts = po_list["stage"].value_counts() if len(po_list) else pd.Series(dtype=int)
    m = st.columns(5)
    m[0].metric("📝 Drafts to approve", int(stage_counts.get("DRAFT", 0)))
    m[1].metric("📤 With the vendor", int(stage_counts.get("SENT", 0) + stage_counts.get("CONFIRMED", 0)))
    m[2].metric("🚚 In transit", int(stage_counts.get("SHIPPED", 0)))
    m[3].metric("📦 At the dock", int(stage_counts.get("ARRIVED", 0)))
    m[4].metric("⏰ Late", int(po_list["late"].sum()) if len(po_list) else 0)

    if "goto_view" in st.session_state:                 # switch view after creating a PO
        st.session_state["buy_view"] = st.session_state.pop("goto_view")
    buy_view = st.radio("View", ["📄 Purchase orders", "➕ New purchase order", "🏢 Vendors"],
                        horizontal=True, key="buy_view", label_visibility="collapsed")

    if buy_view == "📄 Purchase orders":
        if po_list.empty:
            st.info("No purchase orders yet. Prepare them from the 📋 Dashboard or create one under ➕ New purchase order.")
        else:
            open_only = st.toggle("Open orders only", value=True)
            pl = po_list[~po_list["stage"].isin(["RECEIVED", "CANCELLED"])] if open_only else po_list
            pl = pl.assign(
                status=pl["stage"].map(pu.STAGE_LABELS),
                eta=np.where(pl["stage"].isin(["SHIPPED", "ARRIVED", "RECEIVED"]), pl["arrive_date"], pl["promised_date"]))
            st.dataframe(pl[["order_no", "status", "supplier", "origin", "lines", "total", "created_date",
                             "sent_date", "eta", "late"]], hide_index=True, width="stretch", column_config={
                "order_no": "PO number", "supplier": "Vendor", "origin": "Created by",
                "total": st.column_config.NumberColumn("Total", format="$%,.2f"),
                "created_date": "Created", "sent_date": "Sent",
                "eta": st.column_config.TextColumn("Due", help="Vendor's promised date; the carrier's ETA once shipped"),
                "late": st.column_config.CheckboxColumn("Late?")})
            if pl.empty:
                st.success("No open orders.")
            else:
                # drafts waiting for approval first, then the rest (newest first)
                ids = list(pl.assign(_d=pl["stage"] != "DRAFT").sort_values(["_d", "order_no"],
                                                                         ascending=[True, False])["order_no"])
                label = pl.set_index("order_no")
                goto = st.session_state.pop("open_order", None)         # a request to open a specific PO
                if goto in ids:
                    st.session_state["po_pick"] = goto
                elif st.session_state.get("po_pick") not in ids:
                    st.session_state["po_pick"] = ids[0]
                order_no = st.selectbox("Open a purchase order", ids, key="po_pick",
                                        format_func=lambda o: f"{o} · {label.at[o, 'supplier']} · "
                                                              f"{label.at[o, 'status']}")
                drafts_left = [o for o in ids if label.at[o, "stage"] == "DRAFT" and o != order_no]
                if drafts_left:
                    st.caption(f"📝 {len(drafts_left)} more draft(s) waiting for approval: " +
                               ", ".join(f"{o} ({label.at[o, 'supplier']})" for o in drafts_left))
                h = pu.order_header(conn, order_no)
                current = pu.stage(h, TODAY)
                lines = pu.order_lines(conn, order_no)
                st.markdown(stage_bar(current), unsafe_allow_html=True)

                with st.container(border=True):
                    a, b = st.columns(2)
                    a.markdown("**Vendor**  \n" + vendor_card(h["supplier"]))
                    b.markdown(f"**Ship to**  \n{pu.HOSPITAL['name']}  \n{pu.HOSPITAL['dept']}  \n{pu.HOSPITAL['address']}")
                    b.markdown(f"PO **{order_no}** · created {h['created_date']} by {h['origin']}  \n"
                               f"Need by: {h['need_by'] or '—'}  \nNotes: {h['notes'] or '—'}")

                    if current == "DRAFT":
                        if pu.active_outage(conn, h["supplier"], TODAY):
                            st.error(f"🏭 {h['supplier']} cannot supply right now: if you send this order it "
                                     "will be rejected. Delete it and order from the backup vendor instead.")
                        st.markdown("**Lines** (edit the quantities; 0 removes a line)")
                        r_by_id = plan.set_index("item_id")
                        ed = lines[["line_no", "item_id", "name", "unit", "qty", "unit_cost"]].assign(
                            status=lines["item_id"].map(r_by_id["status"]),
                            usable=lines["item_id"].map(r_by_id["usable"]),
                            rop=lines["item_id"].map(r_by_id["rop"]).round())
                        others = plan[((plan["supplier"] == h["supplier"]) | (plan["backup_supplier"] == h["supplier"]))
                                      & ~plan["item_id"].isin(lines["item_id"])]
                        edited = st.data_editor(
                            ed, hide_index=True, width="stretch", key=f"draft_{order_no}",
                            disabled=["line_no", "item_id", "name", "unit", "unit_cost", "status", "usable", "rop"],
                            column_config={"qty": st.column_config.NumberColumn("Order qty", min_value=0, step=1),
                                           "unit_cost": st.column_config.NumberColumn("Unit price", format="$%.2f"),
                                           "usable": "Usable now", "rop": "Reorder point", "line_no": "Line"})
                        add = st.multiselect("Add items from this vendor", others["item_id"],
                                             format_func=lambda i: f"{item_labels[i]} ({r_by_id.at[i, 'status']})",
                                             key=f"add_{order_no}")
                        new_lines = list(zip(edited["item_id"], edited["qty"])) + [
                            (i, int(r_by_id.at[i, "order_qty"]) or int(np.ceil(r_by_id.at[i, "q"]))) for i in add]
                        subtotal = sum(q * pu.unit_price(r_by_id.loc[i], h["supplier"]) for i, q in new_lines)
                        order_summary(h["supplier"], subtotal)
                        c1, c2 = st.columns(2)
                        need_by = c1.date_input("Need by", value=date.fromisoformat(h["need_by"]) if h["need_by"]
                                                else TODAY + pd.Timedelta(days=pu.VENDORS[h["supplier"]]["quoted_days"]),
                                                min_value=TODAY, key=f"need_{order_no}")
                        notes = c2.text_input("Notes to vendor", value=h["notes"] or "", key=f"notes_{order_no}")
                        b1, b2, b3 = st.columns(3)
                        if b1.button("✅ Approve & send to vendor", type="primary", key=f"send_{order_no}"):
                            _, err = run(pu.update_draft, order_no, new_lines, need_by, notes)
                            if not err:
                                _, err = run(pu.send_order, order_no)
                            if not err:
                                nxt = drafts_left[0] if drafts_left else order_no   # move on to the next draft
                                st.session_state["open_order"] = nxt
                                done(f"{order_no} sent to {h['supplier']} via {pu.VENDORS[h['supplier']]['method']}. " +
                                     (f"Next draft: {nxt} ({label.at[nxt, 'supplier']})." if drafts_left else
                                      "No drafts left. Move the clock forward to see the vendors respond."))
                        if b2.button("💾 Save changes", key=f"save_{order_no}"):
                            _, err = run(pu.update_draft, order_no, new_lines, need_by, notes)
                            if not err:
                                done(f"{order_no} saved (still a draft).")
                        if b3.button("🗑️ Delete draft", key=f"del_{order_no}"):
                            _, err = run(pu.cancel_order, order_no, "Draft deleted")
                            if not err:
                                if drafts_left:
                                    st.session_state["open_order"] = drafts_left[0]
                                done(f"Draft {order_no} deleted.")
                    else:
                        acked = h["ack_date"] and h["ack_date"] <= TODAY.isoformat()
                        shipped = h["ship_date"] and h["ship_date"] <= TODAY.isoformat()
                        hidden = pd.Series(None, index=lines.index, dtype=object)
                        show = lines.assign(              # only show what the vendor has told us so far
                            confirmed=lines["confirmed_qty"] if acked else hidden,
                            lot=lines["asn_lot_no"] if shipped else hidden,
                            expiry=lines["asn_expiry"] if shipped else hidden)
                        st.dataframe(show[["line_no", "item_id", "name", "unit", "qty", "confirmed", "unit_cost",
                                           "amount", "lot", "expiry", "status", "received_qty"]],
                                     hide_index=True, width="stretch", column_config={
                                         "line_no": "Line", "qty": "Ordered",
                                         "confirmed": st.column_config.NumberColumn(
                                             "Confirmed", help="What the vendor confirmed it can supply (after acknowledgement)"),
                                         "unit_cost": st.column_config.NumberColumn("Unit price", format="$%.2f"),
                                         "amount": st.column_config.NumberColumn("Amount", format="$%,.2f"),
                                         "lot": st.column_config.TextColumn("Lot (ASN)", help="From the vendor's ship notice"),
                                         "expiry": "Expiry (ASN)", "received_qty": "Received"})
                        order_summary(h["supplier"], float(lines["amount"].sum()))

                st.markdown("**Vendor messages**")
                for when, msg in pu.vendor_messages(conn, order_no, TODAY):
                    st.markdown(f"- **{when:%b %d}**: {msg}")
                if current in ("SENT", "CONFIRMED", "SHIPPED"):
                    eta = h["arrive_date"] if current == "SHIPPED" else h["promised_date"]
                    st.caption(f"Next: {'delivery' if current == 'SHIPPED' else 'the vendor ships it'}. "
                               f"Expected around {pd.Timestamp(eta):%b %d}. Use 🚚 Next in the sidebar to jump ahead.")

                c1, c2, c3 = st.columns(3)
                if current == "ARRIVED":
                    if c1.button("📥 Receive whole shipment (as per ASN)", type="primary", key=f"recv_{order_no}"):
                        got, err = run(pu.receive_order, order_no)
                        if not err:
                            done(f"Received {order_no}: " + ", ".join(f"{n} × {q:,} (lot {l}, lead time {lt} d)"
                                                                    for n, q, l, lt in got))
                    c1.caption("Different quantity or lot on the boxes? Receive line by line in 📦 Stock movements.")
                if current in ("SENT", "CONFIRMED"):
                    if c2.button("❌ Cancel order", key=f"cancel_{order_no}"):
                        _, err = run(pu.cancel_order, order_no, "Cancelled by buyer")
                        if not err:
                            done(f"{order_no} cancelled.")
                c3.download_button("⬇️ Download PO document", pu.po_document_html(conn, order_no),
                                   f"{order_no}.html", "text/html", key=f"doc_{order_no}",
                                   help="A printable purchase order (open it in your browser and print or save as PDF)")

    elif buy_view == "➕ New purchase order":
        vendor_names = list(pu.VENDORS)
        red_counts = plan[plan["status"].str.startswith("🔴")].groupby("order_vendor").size()
        down = set(active_outages["supplier"])
        supplier = st.selectbox("Vendor", vendor_names,
                                format_func=lambda v: f"{v} ({red_counts.get(v, 0)} item(s) to order now)"
                                                      + (" · 🏭 DISRUPTED" if v in down else ""))
        if supplier in down:
            st.error(f"🏭 {supplier} cannot supply right now. Orders sent to it will be rejected.")
        with st.container(border=True):
            st.markdown(vendor_card(supplier))
        vi = plan[(plan["supplier"] == supplier) | (plan["backup_supplier"] == supplier)]
        vi = vi.assign(_backup=vi["supplier"] != supplier,
                       unit_cost=[pu.unit_price(r, supplier) for _, r in vi.iterrows()])
        # backup items are only pre-filled when their primary vendor is the one disrupted
        prefill = vi["status"].str.startswith("🔴") & (vi["order_vendor"] == supplier)
        vi = vi.sort_values(["_backup", "status", "ved"])
        drafted = pu.items_in_drafts(conn)
        suggested = np.where(vi["status"].str.startswith("🔴"), vi["order_qty"], np.ceil(vi["q"])).astype(int)
        form = pd.DataFrame({
            "item_id": vi["item_id"], "name": vi["name"],
            "source": np.where(vi["_backup"], "Backup (+" + f"{pu.BACKUP_PREMIUM:.0%})", "Primary"),
            "status": vi["status"], "ved": vi["ved"],
            "usable": vi["usable"], "on_order": vi["on_order"], "rop": vi["rop"].round(),
            "in_draft": vi["item_id"].map(drafted).fillna(""),
            "suggested": suggested,
            "qty": np.where(prefill.loc[vi.index] & ~vi["item_id"].isin(drafted), vi["order_qty"], 0).astype(int),
            "unit_cost": vi["unit_cost"]})
        st.markdown("**Lines.** *Order qty* is pre-filled for 🔴 items with the plan's suggestion "
                    "(order up to R + Q). Type a quantity for any other item you want on this PO.")
        edited = st.data_editor(form, hide_index=True, width="stretch", key=f"new_po_{supplier}",
                                disabled=[c for c in form.columns if c != "qty"], column_config={
                                    "name": "Item", "ved": "VED", "usable": "Usable", "on_order": "On order",
                                    "source": st.column_config.TextColumn(
                                        "Source", help="Primary = this vendor is the usual source. Backup = it can "
                                                       "supply the item when the primary vendor cannot, at a higher price"),
                                    "rop": "Reorder point", "in_draft": "Already in draft",
                                    "suggested": st.column_config.NumberColumn(
                                        "Suggested", help="🔴: order up to R + Q. Others: one economic order quantity Q"),
                                    "qty": st.column_config.NumberColumn("Order qty", min_value=0, step=1),
                                    "unit_cost": st.column_config.NumberColumn("Unit price", format="$%.2f")})
        chosen = edited[edited["qty"] > 0]
        order_summary(supplier, float((chosen["qty"] * chosen["unit_cost"]).sum()))
        c1, c2 = st.columns(2)
        need_by = c1.date_input("Need by", value=TODAY + pd.Timedelta(days=pu.VENDORS[supplier]["quoted_days"]),
                                min_value=TODAY, key="new_need_by")
        notes = c2.text_input("Notes to vendor", key="new_notes", placeholder="e.g. deliver to dock B before noon")
        b1, b2 = st.columns(2)
        lines_in = list(zip(chosen["item_id"], chosen["qty"]))
        if b1.button("✅ Approve & send to vendor", type="primary", disabled=chosen.empty):
            order_no, err = run(pu.create_order, supplier, lines_in, need_by, notes)
            if not err:
                _, err = run(pu.send_order, order_no)
            if not err:
                st.session_state.update(open_order=order_no, goto_view="📄 Purchase orders")
                done(f"{order_no} sent to {supplier}. Move the clock forward to see the vendor respond.")
        if b2.button("💾 Save as draft", disabled=chosen.empty):
            order_no, err = run(pu.create_order, supplier, lines_in, need_by, notes)
            if not err:
                st.session_state.update(open_order=order_no, goto_view="📄 Purchase orders")
                done(f"Draft {order_no} saved. Approve it in 📄 Purchase orders.")

    else:
        st.subheader("Vendor directory")
        st.caption("Fictional vendors. In a real hospital this is the vendor master, usually with contract prices "
                   "negotiated by a group purchasing organization (GPO).")
        directory = pd.DataFrame([{"vendor": n, "contact": v["contact"], "email": v["email"], "phone": v["phone"],
                                   "orders via": v["method"], "terms": v["terms"], "ship via": v["ship_via"],
                                   "min order": v["min_order"], "free freight over": v["free_freight_over"],
                                   "items": int((plan["supplier"] == n).sum()),
                                   "backup for": int((plan["backup_supplier"] == n).sum()),
                                   "status": "🏭 Disrupted" if n in set(active_outages["supplier"]) else "✅ Supplying"}
                                  for n, v in pu.VENDORS.items()])
        st.dataframe(directory, hide_index=True, width="stretch", column_config={
            "min order": st.column_config.NumberColumn(format="$%,.0f"),
            "free freight over": st.column_config.NumberColumn(format="$%,.0f"),
            "items": st.column_config.NumberColumn("Items (primary)"),
            "backup for": st.column_config.NumberColumn("Backup for", help="Items it can supply when their primary "
                                                                          "vendor cannot (at +12% price)")})
        st.subheader("Vendor scorecard")
        st.caption("Measured from every delivery received. The lead-time average and standard deviation are the "
                   "L̄ and σL that go into each item's safety stock.")
        sc = pu.vendor_scorecard(conn)
        st.dataframe(sc, hide_index=True, width="stretch", column_config={
            "vendor": "Vendor", "deliveries": "Deliveries", "quoted_days": "Quoted lead time (d)",
            "avg_lead_time": st.column_config.NumberColumn("Actual avg L̄ (d)", format="%.1f"),
            "sd_lead_time": st.column_config.NumberColumn("σL (d)", format="%.1f"),
            "on_time": st.column_config.ProgressColumn("On time", format="percent", min_value=0, max_value=1,
                                                       help="Delivered within the quoted lead time"),
            "fill_rate": st.column_config.ProgressColumn("Fill rate", format="percent", min_value=0, max_value=1,
                                                         help="Units received ÷ units ordered (vendor backorders "
                                                              "lower it). Only POs made in this version.")})


with tab_move:
    st.header("Stock movements")
    action = st.radio("What happened?", ["📤 Issue to ward", "📥 Receive delivery", "🗑️ Write-off", "🔢 Cycle count"],
                      horizontal=True)
    st.caption("To order stock, go to 🛒 Purchasing.")

    if action == "📤 Issue to ward":
        st.caption("Stock leaves the storeroom, picked **FEFO** (first expired, first out). Expired lots are "
                   "never issued. This usage also feeds the demand estimate (d̄, σd). Anything requested but not "
                   "available is logged as a stockout and still counts as demand; the success message below shows "
                   "exactly how much was served and how much was short.")
        iid = pick_item("issue_item")
        r = item_row(iid)
        st.info(f"Usable: **{r['usable']:,} {r['unit']}** (on hand {r['on_hand']:,}) · reorder point {r['rop']:,.0f}")
        c1, c2, c3 = st.columns(3)
        ward = c1.selectbox("Department", db.WARDS)
        qty = c2.number_input("Quantity", min_value=1, step=1, value=1, key="issue_qty")
        when = c3.date_input("Date", value=TODAY, max_value=TODAY, key="issue_date")
        note = st.text_input("Note (optional)", key="issue_note", placeholder="e.g. requested by")
        if "issue_req_id" not in st.session_state:
            st.session_state["issue_req_id"] = str(uuid.uuid4())
        if st.button("Issue stock", type="primary"):
            res, err = run(db.fulfill_request, iid, qty, ward, when, note, st.session_state["issue_req_id"])
            if not err:
                st.session_state["issue_req_id"] = str(uuid.uuid4())
                pick_text = ", ".join(f"lot {no} × {q}" for no, q in res["picks"])
                if res["short"]:
                    st.error(f"Only **{res['filled']:,} of {res['requested']:,} {r['unit']}** could be served to "
                             f"{ward} — {res['short']:,} was **not available** and is logged as a stockout "
                             f"(and counts as demand). Take from shelf: {pick_text or 'nothing'}.")
                else:
                    left = r["usable"] - qty
                    warn = " ⚠️ Now at or below the reorder point!" if left + r["on_order"] <= r["rop"] else ""
                    done(f"All {qty} × {r['name']} issued to {ward}. Take from shelf: {pick_text}.{warn}")

    elif action == "📥 Receive delivery":
        st.caption("Goods arrived at the dock. Check the boxes against the vendor's ship notice (ASN): quantity, "
                   "lot number and expiry date are pre-filled from it; change them if the boxes say otherwise. "
                   "The real lead time is saved, so the σL estimate keeps getting better.")
        at_dock = open_pos[open_pos["arrive_date"].isna() | (open_pos["arrive_date"] <= pd.Timestamp(TODAY))]
        if at_dock.empty:
            coming = open_pos["arrive_date"].dropna()
            st.info("Nothing is waiting at the receiving dock." + (
                f" {open_pos['order_no'].nunique()} order(s) are on their way; check 🛒 Purchasing or press "
                "🚚 Next in the sidebar to jump to the next delivery." if len(open_pos) else
                " Order stock in 🛒 Purchasing."))
        else:
            labels = {p.po_id: f"{p.order_no or p.po_id}"
                               f"{f' line {p.line_no:.0f}' if pd.notna(p.line_no) else ''} · {item_labels[p.item_id]} · "
                               f"{p.qty:,} outstanding"
                      for p in at_dock.itertuples()}
            po_id = st.selectbox("Delivery line", list(labels), format_func=labels.get)
            po = at_dock[at_dock["po_id"] == po_id].iloc[0]
            r = item_row(po["item_id"])
            has_asn = pd.notna(po["asn_lot_no"])
            outstanding = int(po["qty"])
            c1, c2, c3, c4 = st.columns(4)
            qty = c1.number_input("Quantity received", min_value=1, step=1, max_value=outstanding,
                                  value=outstanding, key=f"recv_qty_{po_id}",
                                  help="Enter less than expected for a short delivery")
            when = c2.date_input("Date received", value=TODAY, max_value=TODAY,
                                 min_value=po["order_date"].date(), key=f"recv_date_{po_id}")
            lot_no = c3.text_input("Lot number", value=po["asn_lot_no"] if has_asn else "", key=f"recv_lot_{po_id}",
                                   placeholder="printed on the box")
            expiry = c4.date_input("Expiry date", key=f"recv_exp_{po_id}",
                                   value=date.fromisoformat(po["asn_expiry"]) if has_asn
                                   else TODAY + pd.Timedelta(days=int(r["shelf_life_days"])))
            if has_asn:
                st.caption(f"Pre-filled from the vendor's ship notice for {po['order_no']}.")
            if outstanding < int(po["ordered_qty"]):
                st.caption(f"⚠️ This line is a **partial receipt**: {outstanding:,} of {int(po['ordered_qty']):,} "
                           f"ordered units are still outstanding (vendor backorder or earlier short delivery). "
                           "What you enter now is added to what was already received.")
            no_conf = po["expected_date"] < pd.Timestamp(TODAY)
            if no_conf:
                st.warning("⚠️ This delivery is overdue. If it is really at the dock, receive it now; "
                           "otherwise chase the vendor (its ETA is no longer reliable).")
            # Smart check: can we use this lot before it expires, at today's usage rate?
            if r["d"] > 0 and expiry > TODAY:
                days_to_use = (r["usable"] + qty) / r["d"]
                days_left = (expiry - TODAY).days
                if days_to_use > days_left:
                    waste = (r["usable"] + qty) - r["d"] * days_left
                    st.warning(f"⚠️ At {r['d']:.1f} {r['unit']}/day it takes about {days_to_use:.0f} days to use "
                               f"this delivery plus current stock, but this lot expires in {days_left} days. "
                               f"About {min(waste, qty):,.0f} units may expire unused. Consider refusing it "
                               f"or asking the vendor for a longer-dated lot.")
            note = st.text_input("Note (optional)", key="recv_note", placeholder="e.g. packing slip no.")
            b1, b2 = st.columns([1, 4])
            if b1.button("Receive", type="primary"):
                lt, err = run(db.receive, po_id, qty, lot_no, expiry, when, note)
                if not err:
                    done(f"Received {qty} × {r['name']}. Actual lead time: {lt} days.")
            if b2.button("Refuse / cancel this line"):
                _, err = run(db.cancel_po, po_id, "Refused at the dock")
                if not err:
                    done(f"Line refused; {r['name']} is no longer on order.")

    elif action == "🗑️ Write-off":
        st.caption("Stock that can no longer be used. This is NOT demand, so it does not change the forecast.")
        iid = pick_item("wo_item")
        r = item_row(iid)
        item_lots = lots[lots["item_id"] == iid]
        if item_lots.empty:
            st.info("This item has no stock.")
        else:
            lot_labels = {l.lot_id: f"Lot {l.lot_no} · expires {l.expiry_date:%Y-%m-%d}"
                                    f"{' (EXPIRED)' if l.expiry_date <= pd.Timestamp(TODAY) else ''} · {l.qty:,} left"
                          for l in item_lots.itertuples()}
            lot_id = st.selectbox("Lot", list(lot_labels), format_func=lot_labels.get, key=f"wo_lot_{iid}")
            lot = item_lots[item_lots["lot_id"] == lot_id].iloc[0]
            is_expired = lot["expiry_date"] <= pd.Timestamp(TODAY)
            c1, c2, c3 = st.columns(3)
            reason = c1.selectbox("Reason", db.WRITE_OFF_REASONS, index=0 if is_expired else 1, key=f"wo_r_{lot_id}")
            qty = c2.number_input("Quantity", min_value=1, step=1, max_value=int(lot["qty"]),
                                  value=int(lot["qty"]) if is_expired else 1, key=f"wo_qty_{lot_id}")
            when = c3.date_input("Date", value=TODAY, max_value=TODAY, key="wo_date")
            note = st.text_input("Note (optional)", key="wo_note", placeholder="e.g. found damaged in receiving")
            if st.button("Write off", type="primary"):
                new, err = run(db.write_off, lot_id, qty, reason, when, note)
                if not err:
                    done(f"Wrote off {qty} × {r['name']} from lot {lot['lot_no']} ({reason}). On hand now {new}. "
                         f"Loss: ${qty * r['unit_cost']:,.2f}")

    else:
        st.caption("Count what is physically on the shelf, lot by lot. The system quantity is hidden on purpose "
                   "(a *blind count*), so the counter is not influenced by it. Empty lots are listed too, so a "
                   "lot the system says is empty can still be found and counted (e.g. if stock was found missed).")
        iid = pick_item("cc_item")
        item_lots = pd.read_sql("SELECT * FROM lots WHERE item_id = ? ORDER BY expiry_date, lot_id", conn,
                                params=(iid,), parse_dates=["expiry_date", "received_date"])
        if item_lots.empty:
            st.info("The system has no lots for this item.")
        else:
            lot_labels = {l.lot_id: f"Lot {l.lot_no} · expires {l.expiry_date:%Y-%m-%d}"
                                    f"{' · empty' if l.qty == 0 else ''}"
                          for l in item_lots.itertuples()}
            lot_id = st.selectbox("Lot", list(lot_labels), format_func=lot_labels.get, key=f"cc_lot_{iid}")
            c1, c2 = st.columns(2)
            counted = c1.number_input("Counted quantity", min_value=0, step=1, value=0, key=f"cc_qty_{lot_id}")
            when = c2.date_input("Date", value=TODAY, max_value=TODAY, key="cc_date")
            note = st.text_input("Note (optional)", key="cc_note", placeholder="e.g. counted by")
            if st.button("Save count", type="primary"):
                diff, err = run(db.cycle_count, lot_id, counted, when, note)
                if not err:
                    done("Count matches the system ✔" if diff == 0
                         else f"Difference of {diff:+d} found and corrected. Check for unrecorded issues or receipts.")

    st.divider()
    st.subheader("On order (lines sent to vendors)")
    if open_pos.empty:
        st.caption("None.")
    else:
        show = open_pos.assign(name=open_pos["item_id"].map(item_labels),
                               overdue=(open_pos["expected_date"] < pd.Timestamp(TODAY))
                               & ~(open_pos["arrive_date"] <= pd.Timestamp(TODAY)))
        st.dataframe(show[["order_no", "line_no", "name", "supplier", "ordered_qty", "qty", "order_date",
                           "expected_date", "overdue"]],
                     hide_index=True, width="stretch", column_config={
                         "order_no": "PO", "line_no": "Line", "supplier": "Vendor", "ordered_qty": "Ordered",
                         "qty": st.column_config.NumberColumn("On order", help="Confirmed by the vendor, once acknowledged"),
                         "order_date": st.column_config.DateColumn("Sent"),
                         "expected_date": st.column_config.DateColumn("Promised"),
                         "overdue": st.column_config.CheckboxColumn("Late?")})
        st.caption("Details, vendor messages and tracking: 🛒 Purchasing.")

# ---------------------------------------------------------------------------
# Tab: Forecast — what will demand be, and how good is each method?
# ---------------------------------------------------------------------------
with tab_fc:
    st.header("Demand forecast")
    if fc_method == SIMPLE:
        st.warning("Reorder points currently use a simple average (sidebar). The forecasts below are shown for "
                   "comparison only.")
    st.markdown("""
Each item's history is turned into a **monthly series of average daily usage**. MedStock runs the four
methods from the course (slides 276-306) and **backtests** them: for each of the last 12 months it makes
a one-step-ahead forecast using only the data available at the time, then compares it with what really
happened. **Auto** uses the method with the lowest **MAD** for each item.
""")

    st.subheader("Seasonal outlook: next 90 days")
    if len(rising):
        st.info(f"{len(rising)} items are forecast to be at least 15% busier over the next 90 days than in the "
                "last 30. Their reorder points already use the forecast, so they are reordered earlier and in "
                "larger amounts.")
    if outlook.empty:
        st.info("Not enough usage history to build a seasonal outlook yet. Items with at least ~4 months of "
                "complete usage appear here; reorder points meanwhile use the simple average (d̄).")
    st.dataframe(
        outlook.sort_values("change_90", ascending=False)[
            ["name", "ved", "method", "last_30_days", "next_30_days", "next_90_days", "change_90",
             "peak_month", "peak_rate"]],
        hide_index=True, width="stretch", column_config={
            "ved": "VED", "method": "Method used",
            "last_30_days": st.column_config.NumberColumn("Last 30 days (per day)", format="%.1f"),
            "next_30_days": st.column_config.NumberColumn("Next 30 days (per day)", format="%.1f"),
            "next_90_days": st.column_config.NumberColumn("Next 90 days (per day)", format="%.1f"),
            "change_90": st.column_config.NumberColumn("Change", format="percent"),
            "peak_month": st.column_config.DateColumn("Peak month", format="MMM YYYY"),
            "peak_rate": st.column_config.NumberColumn("Peak (per day)", format="%.1f"),
        })
    if outlook.empty:
        st.caption("Methods chosen by Auto: —")
    else:
        st.caption("Methods chosen by Auto: " + ", ".join(
            f"{m} × {n}" for m, n in outlook["method"].value_counts().items()))

    st.subheader("One item in detail")
    if not forecasts:
        st.info("No forecasts to show yet. The app needs at least 4 months of complete usage history for an "
                "item to run the backtest; reorder points still work on the simple average in the meantime.")
    else:
        fc_item = st.selectbox("Item", list(forecasts), format_func=item_labels.get, key="fc_item")
        f = forecasts[fc_item]
        hist = f["history"]
        fig = go.Figure()
        fig.add_scatter(x=hist.index, y=hist, name="Actual", mode="lines+markers", line=dict(color="#34495e"))
        fig.add_scatter(x=hist.index, y=f["fitted"], name=f"{f['method']}: one-step forecast",
                        line=dict(dash="dot", color="#e67e22"))
        fig.add_scatter(x=f["future"].index, y=f["future"], name="Forecast (next 12 months)",
                        mode="lines+markers", line=dict(color="#c0392b", width=3))
        bt0 = hist.index[max(0, len(hist) - 12)]
        fig.add_vrect(x0=bt0, x1=hist.index[-1], fillcolor="#3498db", opacity=0.07, line_width=0,
                      annotation_text="backtest period", annotation_position="top left")
        fig.update_layout(title=f"{item_labels[fc_item]}: average daily usage per month",
                          yaxis_title="Units per day", height=420, legend=dict(orientation="h", y=-0.15))
        st.plotly_chart(fig, width="stretch")

        c1, c2 = st.columns([3, 2])
        with c1:
            st.markdown("**Backtest accuracy, last 12 months** (e = F − D, slide 270)")
            scores = f["scores"].reset_index()
            scores["chosen"] = scores["method"] == f["method"]
            st.dataframe(scores[["chosen", "method", "MAD", "MSE", "MAPE", "bias"]], hide_index=True, width="stretch",
                         column_config={
                             "chosen": st.column_config.CheckboxColumn("Used"),
                             "MAD": st.column_config.NumberColumn(format="%.2f"),
                             "MSE": st.column_config.NumberColumn(format="%.2f"),
                             "MAPE": st.column_config.NumberColumn(format="percent"),
                             "bias": st.column_config.NumberColumn("Bias", format="%+.2f",
                                                                   help="Average error. > 0 means we over-forecast."),
                         })
        with c2:
            mad = f["scores"].loc[f["method"], "MAD"]
            sigma = f["sigma_daily"]
            st.markdown(f"""
**From forecast error to safety stock**
- MAD of {f['method']} = **{mad:.2f}** units/day (monthly averages)
- σ of a month's average ≈ 1.25 × MAD = **{1.25 * mad:.2f}**
- One day's σd = that × √30.4 = **{sigma:.1f}**

This σd goes into SS = z·√(L̄σd² + d̄²σL²). Safety stock protects against what the
forecast **cannot** predict. Predictable swings like flu season are handled by the forecast itself.
""")

# ---------------------------------------------------------------------------
# Tab: Expiry — what is expiring, and what will we fail to use in time?
# ---------------------------------------------------------------------------
LOT_COLUMNS = {
    "lot_no": "Lot", "expiry_date": st.column_config.DateColumn("Expires"),
    "days_left": st.column_config.NumberColumn("Days left", format="%d"),
    "qty": "Qty", "projected_use": st.column_config.NumberColumn("Will be used", format="%.0f"),
    "projected_waste": st.column_config.NumberColumn("Will expire unused", format="%.0f"),
    "value": st.column_config.NumberColumn("Value", format="$%,.2f"),
    "waste_value": st.column_config.NumberColumn("Waste $", format="$%,.2f"),
}

with tab_exp:
    st.header("Expiry management")
    st.markdown("""
Each lot is projected forward with **FEFO**: lots are used in expiry order at the item's average daily usage d̄.
Whatever is still on the shelf on the expiry date is **projected waste**. This is the cost side of the
newsvendor trade-off (Co, slides 221-224): too much stock of a short-dated item means paying for units that expire.
""")
    expired = lot_risk[lot_risk["days_left"] <= 0]
    at_risk = lot_risk[(lot_risk["days_left"] > 0) & (lot_risk["projected_waste"] > 0.5)]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Expired on shelf", f"${expired['value'].sum():,.0f}", f"{len(expired)} lots", delta_color="off")
    c2.metric("Expiring ≤ 30 days", f"${lot_risk.loc[(lot_risk['days_left'] > 0) & (lot_risk['days_left'] <= 30), 'value'].sum():,.0f}")
    c3.metric("Expiring 31-90 days", f"${lot_risk.loc[(lot_risk['days_left'] > 30) & (lot_risk['days_left'] <= 90), 'value'].sum():,.0f}")
    c4.metric("Projected waste (not yet expired)", f"${at_risk['waste_value'].sum():,.0f}", f"{len(at_risk)} lots",
              delta_color="off", help="Units in lots that, at current usage, will expire before they are used")

    st.subheader("1. Expired: remove from the shelf now")
    if expired.empty:
        st.success("No expired stock. 👍")
    else:
        st.error("Expired stock must never reach a patient. MedStock already refuses to issue it, "
                 "but it should be physically removed and written off.")
        st.dataframe(expired[["name", "lot_no", "expiry_date", "days_left", "qty", "value"]],
                     hide_index=True, width="stretch", column_config=LOT_COLUMNS)
        if st.button(f"🗑️ Write off all {len(expired)} expired lots (${expired['value'].sum():,.2f})", type="primary"):
            n, value = db.write_off_all_expired(conn, TODAY)
            done(f"Wrote off {n} expired lots worth ${value:,.2f}.")

    st.subheader("2. At risk: will expire before we use it")
    if at_risk.empty:
        st.success("At current usage rates every lot will be used before it expires.")
    else:
        st.dataframe(at_risk.sort_values("waste_value", ascending=False)
                     [["name", "ved", "lot_no", "expiry_date", "days_left", "qty", "projected_use",
                       "projected_waste", "waste_value"]],
                     hide_index=True, width="stretch", column_config=LOT_COLUMNS)
        st.markdown("""
**What a supply manager can do:**
- **Transfer** the short-dated lot to the department that uses the most of it (e.g. the Emergency Department).
- **Return or exchange** it with the supplier. Many accept returns 60-90 days before expiry.
- **Pause reordering** this item until the short-dated lot is used up.
- **Order smaller quantities** next time. MedStock already caps Q at 80% of shelf life × d̄.
""")

    st.subheader("All lots by expiry")
    band = st.multiselect("Show", ["Expired", "≤ 30 days", "31-90 days", "> 90 days"],
                          default=["Expired", "≤ 30 days", "31-90 days"])
    show = lot_risk[lot_risk["expiry_band"].isin(band)].sort_values("expiry_date")
    st.dataframe(show[["name", "lot_no", "expiry_date", "days_left", "qty", "value", "projected_waste"]],
                 hide_index=True, width="stretch", column_config=LOT_COLUMNS)

# ---------------------------------------------------------------------------
# Tab: History — the ledger explains every change in stock
# ---------------------------------------------------------------------------
with tab_hist:
    st.header("Transaction history")
    log = db.ledger(conn)
    acc, n_counts = db.record_accuracy(conn)
    c1, c2, c3 = st.columns(3)
    c1.metric("Movements recorded", f"{len(log):,}")
    c2.metric("Cycle counts", n_counts)
    c3.metric("Record accuracy", "—" if acc is None else f"{acc:.0%}",
              help="Share of counts where the system matched the shelf. Good practice: 97% or more.")
    if log.empty:
        st.info("No movements yet. Record one in 📦 Stock movements.")
    else:
        f1, f2 = st.columns(2)
        types = f1.multiselect("Type", sorted(log["type"].unique()))
        chosen = f2.multiselect("Item", sorted(log["item_id"].unique()), format_func=item_labels.get)
        view = log
        if types:
            view = view[view["type"].isin(types)]
        if chosen:
            view = view[view["item_id"].isin(chosen)]
        st.dataframe(view, hide_index=True, width="stretch", column_config={
            "txn_id": "#", "created_at": "Recorded at", "qty": "Qty change", "balance_after": "Balance"})
        st.download_button("⬇️ Download as CSV", view.to_csv(index=False), "medstock_transactions.csv", "text/csv")

    st.subheader("🔍 Lot trace (for recalls)")
    st.caption("A manufacturer recalls a lot: find out where every unit of it went.")
    lot_no = st.text_input("Lot number", placeholder="e.g. L81739", key="trace_lot").strip()
    if lot_no:
        trace = db.lot_trace(conn, lot_no)
        if trace.empty:
            st.info(f"No movements recorded for lot {lot_no} yet (or it does not exist).")
        else:
            st.dataframe(trace, hide_index=True, width="stretch")
            issued = trace[trace["type"] == "ISSUE"]
            if len(issued):
                by_ward = issued.groupby("ward_or_reference")["qty"].sum().abs()
                st.write("Issued to: " + ", ".join(f"**{w}** ({q})" for w, q in by_ward.items()))

# ---------------------------------------------------------------------------
# Tab: Item detail — show the math for one item, step by step
# ---------------------------------------------------------------------------
with tab_item:
    labels = plan["item_id"] + " · " + plan["name"]
    choice = st.selectbox("Choose an item", labels)
    r = plan[labels == choice].iloc[0]

    st.header(f"{r['name']}  {r['status']}")
    st.caption(f"{r['category']} · {r['unit']} · ${r['unit_cost']:,.2f} each · "
               f"VED = {r['ved']} · ABC = {r['abc']} · Control category {r['control']} · {r['supplier']}")

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Usable on hand", f"{r['usable']:,.0f}",
              help=f"{r['on_hand']:,} on shelf, {r['on_hand'] - r['usable']:,} expired. "
                   f"Plus {r['on_order']:,} on order = position {r['position']:,}")
    c2.metric("Reorder point", f"{r['rop']:,.0f}")
    c3.metric("Order quantity", f"{r['q']:,.0f}")
    c4.metric("Safety stock", f"{r['safety_stock']:,.0f}")
    c5.metric("Predicted fill rate", f"{r['fill_rate']:.2%}",
              help="THEORETICAL: what the service level promises, from the lead-time-demand formula "
                   "(slides 205-207). For the fill rate actually achieved, see 'Measured fill rate from "
                   "logged requests' on the 📋 Dashboard.")

    with st.expander("📐 Show the calculation (lecture formulas)", expanded=True):
        st.markdown(f"""
**Step 1: Forecast demand and measure lead time from history**
- Demand method: **{r['method']}**
- {"Forecast daily demand during the next " + f"{math.ceil(r['L'])}" + " days (the lead time)" if fc_method != SIMPLE else "Average daily usage"} d̄ = **{r['d']:.2f}** units/day
- σd = **{r['sd']:.2f}** {"(from forecast errors: 1.25 × MAD × √30.4, see 📈 Forecast)" if fc_method != SIMPLE else f"(std. dev. of daily usage, last {lookback} days)"}
- Average lead time L̄ = **{r['L']:.1f}** days, σL = **{r['sL']:.1f}** days (from {r['n_orders']:.0f} past orders)
- Annual demand D = {"sum of the next 365 days of forecast" if fc_method != SIMPLE else "d̄ × 365"} = **{r['D']:,.0f}**

**Step 2: EOQ** (slide 188)  H = i × C = {r['holding_rate']:.0%} × ${r['unit_cost']:,.2f} = ${r['H']:,.2f}
- EOQ = √(2DS/H) = √(2 × {r['D']:,.0f} × {r['ordering_cost']} / {r['H']:.2f}) = **{r['eoq']:,.1f}**
- {"⚠️ Capped by shelf life: we can only use " + f"{r['q']:,.0f}" + " units in 80% of the shelf life (" + str(r['shelf_life_days']) + " days)." if r['q_limited_by_expiry'] else "Shelf life is not a constraint for this item."}
- One order lasts about **{r['cycle_days']:.0f} days**

**Step 3: Safety stock and reorder point** (slides 200-201)
- Service level {r['service_level']:.1%} → z = **{r['z']:.3f}**
- DDLT = d̄ × L̄ = {r['d']:.2f} × {r['L']:.1f} = **{r['ddlt']:.1f}**
- σ_DDLT = √(L̄σd² + d̄²σL²) = √({r['L']:.1f}×{r['sd']:.2f}² + {r['d']:.2f}²×{r['sL']:.1f}²) = **{r['sigma_ddlt']:.1f}**
- SS = z × σ_DDLT = **{r['safety_stock']:.1f}**
- ROP = DDLT + SS = **{r['rop']:.1f}**

**Step 4: Predicted fill rate** (slides 205-207): 1 − σ_DDLT·L(z)/Q = **{r['fill_rate']:.3%}**
(measured from logged requests: 📋 Dashboard)
""")

    if r["availability_risk"] != "🟢 OK" or r["unknown_eta"]:
        short_txt = ""
        if not pd.isna(r["shortage_date"]):
            short_txt = f" — first day stock runs out: **{pd.Timestamp(r['shortage_date']):%b %d}**, " \
                        f"projected **{r['projected_short_units']:,.0f} units short** over the next 90 days."
        eta_txt = " ⚠️ One of the open orders has **no reliable arrival date**." if r["unknown_eta"] else ""
        st.warning(f"**Availability projection:** {r['availability_risk']}{short_txt}{eta_txt}")

    # Usage history chart
    hist = usage[usage["item_id"] == r["item_id"]].copy()
    if hist.empty:
        st.info("No usage history is available for this item yet.")
    else:
        hist["7-day average"] = hist["qty_used"].rolling(7).mean()
        fig = px.line(hist, x="date", y=["qty_used", "7-day average"],
                      labels={"value": "Units used per day", "date": "", "variable": ""},
                      title="Daily usage (3 years)")
        fig.update_traces(selector=dict(name="qty_used"), opacity=0.35, name="Daily usage")
        st.plotly_chart(fig, width="stretch")

    col_a, col_b = st.columns(2)
    # Cost curve: what if we order more or less than EOQ? (slide 190)
    with col_a:
        if r["eoq"] > 0:
            qs = np.linspace(max(1, r["eoq"] * 0.2), r["eoq"] * 3, 200)
            ordering = r["D"] / qs * r["ordering_cost"]
            holding = qs / 2 * r["H"]
            fig = go.Figure()
            fig.add_scatter(x=qs, y=ordering, name="Ordering cost")
            fig.add_scatter(x=qs, y=holding, name="Holding cost")
            fig.add_scatter(x=qs, y=ordering + holding, name="Total", line=dict(width=3))
            fig.add_vline(x=r["eoq"], line_dash="dash", annotation_text="EOQ")
            fig.update_layout(title="Cost vs order quantity (slide 190 sensitivity)",
                              xaxis_title="Order quantity Q", yaxis_title="$ per year")
            st.plotly_chart(fig, width="stretch")
    # Lead time reliability of the supplier
    with col_b:
        lt = deliveries[deliveries["item_id"] == r["item_id"]]
        fig = px.bar(lt, x="order_date", y="lead_time_days", title="Supplier lead time per order",
                     labels={"order_date": "Order date", "lead_time_days": "Lead time (days)"})
        fig.add_hline(y=r["L"], line_dash="dash", annotation_text="average")
        st.plotly_chart(fig, width="stretch")

    st.subheader("Lots on the shelf (FEFO order)")
    item_lots = lot_risk[lot_risk["item_id"] == r["item_id"]].sort_values("expiry_date")
    if item_lots.empty:
        st.caption("No stock.")
    else:
        st.dataframe(item_lots[["lot_no", "expiry_date", "days_left", "qty", "projected_use", "projected_waste"]],
                     hide_index=True, width="stretch", column_config=LOT_COLUMNS)

    st.subheader("Recent movements")
    item_log = db.ledger(conn)
    item_log = item_log[item_log["item_id"] == r["item_id"]].head(20)
    if item_log.empty:
        st.caption("No movements recorded in the app yet for this item.")
    else:
        st.dataframe(item_log[["date", "type", "qty", "balance_after", "reference", "note"]],
                     hide_index=True, width="stretch")

# ---------------------------------------------------------------------------
# Tab 3: ABC-VED — where should management attention go?
# ---------------------------------------------------------------------------
with tab_abc:
    st.header("ABC-VED analysis")
    st.markdown("""
**ABC** (slides 213-215) ranks items by annual dollar value: where the **money** is.
**VED** ranks items by clinical criticality: **V**ital, **E**ssential, **D**esirable.
Hospitals combine both. A cheap item like epinephrine is class **C** but **Vital**, so it still gets tight control.
""")
    abc_sorted = plan.sort_values("annual_value", ascending=False)
    fig = go.Figure()
    fig.add_bar(x=abc_sorted["name"], y=abc_sorted["annual_value"], name="Annual value ($)",
                marker_color=abc_sorted["abc"].map({"A": "#c0392b", "B": "#e67e22", "C": "#7f8c8d"}))
    fig.add_scatter(x=abc_sorted["name"], y=abc_sorted["cumulative_share"] * 100, name="Cumulative %",
                    yaxis="y2", mode="lines+markers")
    fig.update_layout(title="Pareto chart of annual consumption value",
                      yaxis=dict(title="$ per year"),
                      yaxis2=dict(title="Cumulative %", overlaying="y", side="right", range=[0, 105]),
                      xaxis_tickangle=-45, height=500)
    st.plotly_chart(fig, width="stretch")

    c1, c2 = st.columns([1, 1])
    with c1:
        st.subheader("Matrix (number of items)")
        matrix = pd.crosstab(plan["abc"], plan["ved"]).reindex(index=["A", "B", "C"], columns=["V", "E", "D"], fill_value=0)
        st.dataframe(matrix, width="stretch")
    with c2:
        st.subheader("Control policy")
        st.markdown("""
| Category | Cells | Policy |
|---|---|---|
| **I** | AV AE AD BV CV | Weekly review, highest service level, never stock out |
| **II** | BE CE BD | Monthly review, normal service level |
| **III** | CD | Quarterly review, order in bulk, low priority |
""")
    summary = plan.groupby("abc").agg(items=("item_id", "count"), value=("annual_value", "sum"))
    summary["share"] = summary["value"] / summary["value"].sum()
    st.dataframe(summary, width="stretch", column_config={
        "value": st.column_config.NumberColumn("Annual value", format="$%,.0f"),
        "share": st.column_config.NumberColumn("Share", format="percent")})

# ---------------------------------------------------------------------------
# Tab 4: Calculators — free-form what-if tools (defaults = slide examples)
# ---------------------------------------------------------------------------
with tab_calc:
    st.header("Calculators")
    which = st.radio("Model", ["EOQ", "Reorder point (uncertain demand & lead time)",
                               "Newsvendor (single period)"], horizontal=True)

    if which == "EOQ":
        st.caption("Defaults = slide 188 example")
        c1, c2, c3, c4 = st.columns(4)
        D = c1.number_input("Annual demand D", value=1000.0, min_value=1.0)
        S = c2.number_input("Ordering cost S", value=50.0, min_value=0.01)
        C = c3.number_input("Unit cost C", value=40.0, min_value=0.01)
        i = c4.number_input("Holding rate i", value=0.25, min_value=0.01)
        Q = im.eoq(D, S, i * C)
        cost = im.total_annual_cost(Q, D, S, i * C, C)
        c1, c2, c3 = st.columns(3)
        c1.metric("EOQ", f"{Q:,.1f}")
        c2.metric("Total annual cost", f"{cost['total']:,.2f}")
        c3.metric("Cycle time", f"{im.cycle_time_days(Q, D):.1f} days")

    elif which.startswith("Reorder"):
        st.caption("Defaults = slide 203 example, in months (d = 1000/12, σd = 50/√12)")
        c1, c2, c3, c4, c5 = st.columns(5)
        d = c1.number_input("Avg demand per period d̄", value=round(1000 / 12, 3))
        sd = c2.number_input("σd per period", value=round(50 / 12 ** 0.5, 3))
        L = c3.number_input("Avg lead time L̄ (periods)", value=0.2)
        sL = c4.number_input("σL (periods)", value=0.05)
        sl = c5.number_input("Service level", value=0.95, min_value=0.5, max_value=0.9999)
        res = im.reorder_point(d, sd, L, sL, sl)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("z", f"{res['z']:.3f}")
        c2.metric("DDLT", f"{res['ddlt']:.2f}")
        c3.metric("Safety stock", f"{res['safety_stock']:.2f}")
        c4.metric("Reorder point", f"{res['rop']:.2f}")

    else:
        st.caption("Defaults = Joe's Slop House (slides 228-231). Hospital use: platelets (5-day shelf life), "
                   "seasonal flu vaccine, or a one-time stock-up before a winter storm.")
        c1, c2, c3, c4, c5 = st.columns(5)
        price = c1.number_input("Price / value per unit", value=4.0)
        cost_ = c2.number_input("Cost per unit", value=2.0)
        salvage = c3.number_input("Salvage value", value=0.5)
        mu = c4.number_input("Mean demand μ", value=80.0)
        sigma = c5.number_input("Std. dev. σ", value=20.0)
        if price > cost_ > salvage:
            nv = im.newsvendor(price, cost_, salvage, mu, sigma)
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Cu / Co", f"{nv['cu']:.2f} / {nv['co']:.2f}")
            c2.metric("Optimal service level", f"{nv['service_level']:.1%}")
            c3.metric("Order quantity Q", f"{nv['q']:.1f}")
            c4.metric("Expected profit", f"{nv['expected_profit']:.2f}")
            st.write(f"Expected shortage **{nv['expected_shortage']:.2f}** · "
                     f"expected sales **{nv['expected_sales']:.2f}** · "
                     f"expected leftover **{nv['expected_excess']:.2f}**")
        else:
            st.warning("Needs price > cost > salvage value.")
