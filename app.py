"""
app.py: MedStock: hospital supply inventory planner (Streamlit web app).

Run:   .venv/bin/streamlit run app.py
Then open the link it prints (usually http://localhost:8501).
"""

import html
import math
import re
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
import help_page
import homepage
import inventory_math as im
import kpis
import planning
import purchasing as pu
import simulation as sim
import ui
import assistant

ASSETS = Path(__file__).parent / "assets"
st.set_page_config(page_title="MedStock", page_icon=str(ASSETS / "logo.png"), layout="wide",
                   initial_sidebar_state="expanded")          # the menu is visible as soon as you sign in

if st.query_params.get("open") == "demo":           # "Open the demo" links on the homepage
    del st.query_params["open"]
    st.session_state["view"] = "demo" if auth.current_user() else "login"
# The open page is kept in the address (?page=help). A reload or a new tab starts a new session, which
# signs you out (sign-in lives only in the session); the link then goes to sign-in and back to that page.
_linked = ui.page_from_slug(st.query_params.get("page"))
if _linked and "view" not in st.session_state:      # fresh session opened on a page link
    st.session_state["view"] = "login"
if _linked and st.session_state.get("linked_slug") != st.query_params.get("page"):
    st.session_state["linked_slug"] = st.query_params.get("page")
    st.session_state["page"] = _linked                # also works when the address is edited by hand
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


def n(count, word, plural=None):
    """'1 lot', '2 lots' (or a given plural)."""
    return f"{count:,} {word if count == 1 else plural or word + 's'}"


KPI_TILES = {}          # container key -> (icon, color); drawn by ui.kpi_css at the end of the run


MUTED_KPIS = set()      # cards whose value cannot be calculated yet (drawn in gray)


def kpi(col, label, value, icon, color, missing=None, **kw):
    """A metric card with a colored icon tile in its corner (see ui.kpi_css). When `missing` gives a reason,
    the value is not available yet: the card shows a dash in gray and the reason under it."""
    key = "kpi_" + re.sub(r"\W+", "_", label.lower()).strip("_")
    KPI_TILES[key] = (icon, color)
    if missing:
        MUTED_KPIS.add(key)
        value, kw = ui.MISSING, {**kw, "delta": "Not enough data yet", "delta_color": "off", "delta_arrow": "off",
                                 "help": (kw.get("help", "") + " " if kw.get("help") else "") + missing}
    col.container(key=key).metric(label, value, **kw)


PO_VIEW = "Purchase orders"


def open_purchase_order(order_no):
    """Jump to Purchasing with this purchase order open (used as a button callback or before done())."""
    st.session_state.update(page="Purchasing", open_order=order_no, goto_view=PO_VIEW)


def section(title, question, icon, color):
    st.html(ui.section(title, question, icon, color))


def done(message, level="success"):
    """Show a message after the page reloads with the new numbers ("success", "warning" or "error")."""
    st.session_state["flash"] = (level, message)
    st.rerun()


def show_flash():
    """The result of the last action, at the top of the page until the next action."""
    if "flash" not in st.session_state:
        return
    level, message = st.session_state.pop("flash")
    message = ui.md_safe(message)
    {"success": st.success, "warning": st.warning, "error": st.error}[level](
        message, icon={"success": ":material/check_circle:", "warning": ":material/warning:",
                       "error": ":material/error:"}[level])

# ---------------------------------------------------------------------------
# Sidebar: the policy knobs a hospital supply manager would control
# ---------------------------------------------------------------------------
st.logo(str(ASSETS / "logo_wordmark.svg"), icon_image=str(ASSETS / "logo.svg"), size="large")
st.html("<style>" + ui.APP_CSS + "</style>")

# Menu: one button per page; only the open page is drawn (see the `if PAGE == ...` blocks below)
PAGE_TITLES = [t for t, _, _ in ui.PAGES]
if st.session_state.get("page") not in PAGE_TITLES:
    st.session_state["page"] = "Dashboard"


def open_page(page):
    st.session_state["page"] = page
    st.session_state["linked_slug"] = ui.page_slug(page)
    st.query_params["page"] = ui.page_slug(page)


menu_top = st.sidebar.container(horizontal=True, key="menu_top")   # "Menu" label + notification bell
with menu_top:
    st.html('<p class="ms-menu-label">Menu</p>')
bell_slot = menu_top.container(width="content")         # filled once the alert count is known (below)
with st.sidebar.container(key="nav_menu"):
    for _title in ui.MAIN_PAGES:
        st.button(ui.nav_label(_title), key=ui.nav_key(_title), on_click=open_page, args=(_title,), width="stretch",
                  help=f"Open {_title}" if ui.nav_label(_title) != _title else None)
with st.sidebar.expander("More", icon=":material/more_horiz:",
                         expanded=st.session_state["page"] in ui.MORE_PAGES), st.container(key="nav_more"):
    for _title in ui.MORE_PAGES:
        st.button(_title, key=ui.nav_key(_title), on_click=open_page, args=(_title,), width="stretch")
PAGE = st.session_state["page"]
if st.query_params.get("page") != ui.page_slug(PAGE):     # keep the address in step with the open page
    st.query_params["page"] = ui.page_slug(PAGE)
    st.session_state["linked_slug"] = ui.page_slug(PAGE)

# Planning settings: the simulation clock and every policy knob, collapsed so the menu stays short.
# (Streamlit cannot nest expanders, so the former "Simulation settings" and "Smoothing constants"
# expanders are plain labeled groups inside this one.)
with st.sidebar.expander("Planning settings", icon=":material/tune:"):
    st.markdown(f"**Simulation clock**  \nToday: {TODAY:%a, %b %d, %Y}" + (" (simulated)" if SIMULATED else ""))
    k1, k2 = st.columns(2)
    step_1 = k1.button("+1 day", type="primary", width="stretch",
                       help="Simulate one day: wards use stock, vendors ship, deliveries arrive")
    step_7 = k2.button("+7 days", width="stretch", help="Simulate a week")
    step_next = st.button("Next delivery", icon=":material/local_shipping:", width="stretch",
                          help="Jump to the day the next delivery arrives")
    auto_mode = st.radio("Automatic reordering", sim.AUTO_MODES, key="auto_mode",
                         help="What MedStock does each simulated evening for items at their reorder point. "
                              "Professional systems usually create drafts that a buyer approves; low-risk items "
                              "are often fully automatic.")
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
        st.session_state["flash"] = ("success", "All data erased and the sample data reloaded. "
                                                "The clock is back to the real date.")

    st.button("Reset to fresh sample data", icon=":material/restart_alt:", disabled=not really, on_click=reset_all)
    st.divider()
    st.markdown("**Service level by criticality (VED)**")
    sl_v = st.slider("Vital items", 0.80, 0.999, 0.99, 0.001, format="%.3f")
    sl_e = st.slider("Essential items", 0.80, 0.999, 0.95, 0.005, format="%.3f")
    sl_d = st.slider("Desirable items", 0.50, 0.99, 0.90, 0.01, format="%.2f")
    st.divider()
    st.markdown("**Demand forecast**")
    SIMPLE = "Simple average (no forecast)"
    fc_method = st.selectbox(
        "Method", ["Auto (best per item)", *fc.METHODS, SIMPLE],
        help="Auto backtests every method on the last 12 months and uses the one with the lowest MAD.")
    lookback = 90
    if fc_method == SIMPLE:
        lookback = st.select_slider("Average over the last … days", options=[30, 60, 90, 180, 365], value=90)
    st.caption("Smoothing constants")
    fc_params = {
        "ma_n": st.number_input("Moving average N (months)", 2, 12, fc.DEFAULT_PARAMS["ma_n"]),
        "alpha": st.slider("α level", 0.05, 0.9, fc.DEFAULT_PARAMS["alpha"], 0.05),
        "beta": st.slider("β trend", 0.05, 0.9, fc.DEFAULT_PARAMS["beta"], 0.05),
        "gamma": st.slider("γ seasonality", 0.05, 0.9, fc.DEFAULT_PARAMS["gamma"], 0.05),
    }
st.sidebar.divider()
s1, s2 = st.sidebar.columns(2)
if s1.button("Project home", key="back_home", icon=":material/home:"):
    st.session_state["view"] = "home"
    st.query_params.clear()
    st.rerun()
if s2.button("Sign out", key="sign_out", icon=":material/logout:", help=f"Signed in as {auth.current_user()}"):
    auth.sign_out()
    st.query_params.clear()
    st.rerun()


if step_1 or step_7 or step_next:
    days = 1 if step_1 else 7
    if step_next:
        nxt = sim.next_arrival(conn)
        days = min(60, max(1, (nxt - TODAY).days)) if nxt else 0
    if days == 0:
        st.sidebar.warning("No deliveries are on their way. Send a purchase order first (Purchasing).")
    else:
        with st.spinner(f"Simulating {n(days, 'day')}…"):
            report = sim.advance(conn, days, {"V": sl_v, "E": sl_e, "D": sl_d},
                                 "Auto" if fc_method.startswith("Auto") or fc_method == SIMPLE else fc_method,
                                 fc_params, auto_mode, auto_receive, random_events=random_events)
        st.session_state["sim_report"] = report
        done(f"Simulated {n(days, 'day')}. Today is now {report['end']:%b %d, %Y}.")


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

show_flash()

# What happened during the last simulation run
rep = st.session_state.get("sim_report")
if rep:
    with st.expander(f":material/schedule: Simulation report: {rep['start']:%b %d} to {rep['end']:%b %d} ({rep['days']} days)",
                     expanded=True):
        m = st.columns(5)
        m[0].metric("Units requested", f"{rep['demand']:,}")
        m[1].metric("Filled from the shelf", f"{rep['issued'] / rep['demand']:.1%}" if rep["demand"] else "n/a",
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
            st.error("Stockouts: " + ", ".join(f"**{r.item}** ({r.ved}, {r.units_short:,} short over {n(r.days, 'day')})"
                                               for r in worst.head(6).itertuples()))
        for ev in rep.get("events", []):
            st.warning(f"**{ev['date']:%b %d}**: {ev['event']}. See Recalls & disruptions.")
        if rep["received"]:
            st.dataframe(pd.DataFrame(rep["received"]), hide_index=True, width="stretch")
        if rep["drafted"]:
            st.info(f"Drafts waiting for your approval: {', '.join(rep['drafted'])}.")
            st.button("Review drafts in Purchasing", icon=":material/arrow_forward:", icon_position="right",
                      key="report_drafts", on_click=open_purchase_order, args=(rep["drafted"][0],))
        if st.button("Close report"):
            st.session_state.pop("sim_report")
            st.rerun()

recalls_14d = recall_list[pd.to_datetime(recall_list["date"]) > pd.Timestamp(TODAY) - pd.Timedelta(days=14)]
ALERTS = events.alert_counts(recall_list, outage_list, lot_risk, TODAY)
bell_slot.button(ui.alerts_label(ALERTS["total"]), key="bell_btn", on_click=open_page, args=("Recalls & disruptions",),
                 help=f"Alerts: {n(ALERTS['recalls'], 'recent recall')}, {n(ALERTS['disruptions'], 'vendor disruption')}, "
                      f"{n(ALERTS['expiring'], 'item')} with stock expired or expiring within 30 days")
st.html("<style>" + ui.nav_css(PAGE)                    # no count on the Alerts menu item: the bell is the one count
        + ui.bell_css(ALERTS["total"]) + "</style>")

# ---------------------------------------------------------------------------
# Help page: the user guide (docs/USER_GUIDE.md), shown inside the app
# ---------------------------------------------------------------------------
if PAGE == "Ask MedStock":
    st.header("Ask MedStock")
    st.caption("An AI assistant that answers with MedStock's own numbers. It looks things up with read-only "
               "tools, so it can explain and advise but cannot order, issue or change anything. All data is "
               "fictional.")
    try:
        ai_cfg = assistant.settings(st.secrets)
        ai_key = assistant.get_api_key(st.secrets, ai_cfg["provider"])
    except Exception:
        ai_cfg = assistant.settings(None)
        ai_key = assistant.get_api_key(None, ai_cfg["provider"])
    ai_name = {"gemini": "Google Gemini", "anthropic": "Anthropic Claude"}[ai_cfg["provider"]]
    ai_free = ai_cfg["provider"] == "gemini" and ai_cfg["billing"] != "paid"
    ai_user = auth.current_user() or "demo"
    st.session_state.setdefault("ai_messages", [])      # the conversation in the provider's format (append-only)
    st.session_state.setdefault("ai_chat", [])          # what is shown on screen
    if st.session_state.get("ai_provider") != (ai_cfg["provider"], ai_cfg["model"]):   # switching starts over
        st.session_state.update(ai_provider=(ai_cfg["provider"], ai_cfg["model"]), ai_messages=[], ai_chat=[])

    def ai_ask(q):
        st.session_state["ai_pending"] = q

    st.caption(f":material/shield: Answers come from {ai_name} ({ai_cfg['model']}) using only MedStock's tools. "
               + ("On Gemini's free tier, Google may use what you type to improve its products. " if ai_free else "")
               + "Use it only with this fictional demo data, never with real patient, hospital, vendor-confidential "
                 "or personal information.")
    if not ai_key:
        key_name = assistant.KEY_NAMES[ai_cfg["provider"]]
        st.info(f"Ask MedStock needs a {ai_name} API key. Add a line `{key_name} = \"...\"` to "
                "`.streamlit/secrets.toml` (on Streamlit Cloud: Manage app > Settings > Secrets), then reload. "
                "The key stays in secrets and is never saved in the code. Everything else in MedStock works "
                "without it.")
    for m in st.session_state["ai_chat"]:
        with st.chat_message(m["role"], avatar=":material/person:" if m["role"] == "user" else ":material/auto_awesome:"):
            st.markdown(m["text"])
            if m.get("run"):
                r = m["run"]
                grounded = (f"all {n(r['figures'], 'figure')} found in the looked-up data" if not r["ungrounded"]
                            else f"{len(r['ungrounded'])} of {n(r['figures'], 'figure')} not found in the looked-up "
                                 "data: " + ", ".join(f"{x:g}" for x in r["ungrounded"][:5]))
                tokens = f"{r['input_tokens'] + r['output_tokens']:,} tokens"
                cost = (ui.md_safe(f"est. ${r['cost']:.4f} at paid rates") if r["cost"] is not None
                        else "provider-dependent cost")
                if r["cost"] is not None and ai_free:
                    cost += ui.md_safe(" (expected charge $0 within the free tier; billing not verified)")
                st.caption(f"{n(len(r['tools']), 'lookup')} · {r['latency_ms'] / 1000:.1f} s · {tokens} · {cost} · "
                           f"{grounded}" if r["status"] == "ok" else
                           f"{n(len(r['tools']), 'lookup')} · {r['latency_ms'] / 1000:.1f} s · {r['status']}")
                if r["tools"]:
                    with st.expander("What it looked up"):
                        for t in r["tools"]:
                            args = ", ".join(f"{k}={v}" for k, v in (t["input"] or {}).items())
                            st.markdown(f"- **{assistant.TOOL_LABELS.get(t['tool'], t['tool'])}**"
                                        + (f" ({args})" if args else "") + (" · error" if t["is_error"] else ""))

    if not st.session_state["ai_chat"]:
        st.markdown("**Try a question:**")
        ex = st.columns(len(assistant.EXAMPLE_QUESTIONS))
        for i, q in enumerate(assistant.EXAMPLE_QUESTIONS):
            ex[i].button(q, key=f"ai_example_{i}", on_click=ai_ask, args=(q,), disabled=not ai_key, width="stretch")

    typed = st.chat_input("Ask about stock, orders, vendors, recalls or KPIs", disabled=not ai_key, key="ai_input")
    question = typed or st.session_state.pop("ai_pending", None)
    if question and ai_key:
        st.session_state["ai_chat"].append({"role": "user", "text": question})
        with st.chat_message("user", avatar=":material/person:"):
            st.markdown(question)
        with st.chat_message("assistant", avatar=":material/auto_awesome:"):
            with st.status("Looking things up…", expanded=False) as ai_status:
                def show_tool(name, _input, failed):
                    ai_status.write(f"{'Could not read' if failed else 'Checked'} "
                                    f"{assistant.TOOL_LABELS.get(name, name).lower()}")
                ctx = assistant.Context(conn, TODAY, plan, lots=lots, po_list=po_list, outlook=outlook)
                try:
                    provider = assistant.make_provider(ai_cfg, ai_key)
                except Exception as e:                      # SDK missing or misconfigured: say so, never crash
                    provider = None
                    result = {"answer": "The AI service is not set up correctly on this server. Everything else in "
                                        "MedStock still works.", "status": "error", "tools": [], "latency_ms": 0,
                              "error": assistant._safe_error(e)}
                if provider is not None:
                    result = assistant.run_turn(provider, ctx, st.session_state["ai_messages"], question,
                                                user=ai_user, on_tool=show_tool, budget=ai_cfg["daily_budget_usd"],
                                                question_limit=ai_cfg["daily_question_limit"])
                ai_status.update(label="Done" if result["status"] == "ok" else "Stopped", state="complete")
        st.session_state["ai_chat"].append({"role": "assistant", "text": result["answer"], "run": result})
        st.rerun()

    c1, c2 = st.columns([1, 3])
    if st.session_state["ai_chat"] and c1.button("New conversation", icon=":material/refresh:", key="ai_reset"):
        st.session_state["ai_messages"], st.session_state["ai_chat"] = [], []
        st.rerun()
    with st.expander("Audit log and usage"):
        s_ = assistant.usage_summary(conn)
        a1, a2, a3, a4 = st.columns(4)
        a1.metric("Answers", s_["answers"])
        a2.metric("Estimated cost", f"${s_['cost']:.2f}",
                  help="Estimated from the providers' standard paid rates, not an invoice. "
                       + ("Configured as Gemini free tier: the expected charge is $0 while the project stays within "
                          "an eligible free tier. MedStock cannot verify the project's billing status. "
                          if ai_free else "")
                       + f"{n(s_['unpriced'], 'answer')} had no price list (provider-dependent).")
        a3.metric("Average time", f"{s_['avg_seconds']:.1f} s")
        a4.metric("Figures found in data", f"{s_['grounded_share']:.0%}" if s_["grounded_share"] is not None else "n/a",
                  help="Share of numbers in answers that match a value the tools returned")
        st.caption(ui.md_safe(
            f"Today for {ai_user}: {assistant.questions_today(conn, ai_user)} of {ai_cfg['daily_question_limit']} "
            f"questions, ${assistant.spent_today(conn, ai_user):.2f} of ${ai_cfg['daily_budget_usd']:.2f} estimated "
            f"spending (paid-rate estimate, checked before each new question). Provider: {ai_name}, "
            f"model {ai_cfg['model']}."))
        log = pd.read_sql("SELECT created_at, provider, model, question, status, tool_calls, input_tokens, "
                          "output_tokens, cost_usd, cost_note, latency_ms, figures, ungrounded "
                          "FROM ai_runs ORDER BY run_id DESC LIMIT 20", conn)
        if len(log):
            st.dataframe(log, hide_index=True, width="stretch", column_config={
                "created_at": "When", "provider": "Provider", "model": "Model", "question": "Question",
                "status": "Status", "tool_calls": "Lookups", "input_tokens": "Tokens in", "output_tokens": "Tokens out",
                "cost_usd": st.column_config.NumberColumn("Est. cost", format="$%.4f",
                                                          help="Estimate at standard paid rates, not an invoice. "
                                                               "Blank: no price list for the model"),
                "cost_note": "How to read the cost",
                "latency_ms": st.column_config.NumberColumn("Time (ms)"), "figures": "Figures",
                "ungrounded": "Not found in data"})

if PAGE == "Help":
    help_page.render(open_page)

# ---------------------------------------------------------------------------
# Dashboard page: what needs ordering today?
# ---------------------------------------------------------------------------
RISK_ORDER = {"🔴 No usable stock": 0, "🔴 Shortage risk": 1, "🟡 Shortage watch": 2, "🟢 OK": 3}


def plain(label):
    """'🔴 Shortage risk' -> 'Shortage risk': explicit text, never color or emoji alone."""
    return str(label).split(" ", 1)[1] if str(label)[:1] in "🔴🟡🟢" else str(label)


def card_row(key):
    """A row of equal cards that wraps on narrow screens (4 across on desktop, 2 x 2 on a tablet).
    The minimum card width for each row is set in ui.APP_CSS under 'responsive card rows'."""
    return st.container(horizontal=True, wrap=True, gap="medium", key=key)


def card_title(title, caption=None):
    """Same title treatment for every dashboard card."""
    st.markdown(f"**{title}**")
    if caption:
        st.caption(caption)


# ---------------------------------------------------------------------------
# Shared page pieces (same look on every page; styles in ui.APP_CSS)
# ---------------------------------------------------------------------------
def page_header(title, subtitle=None):
    """Page title and a one-line subtitle."""
    st.header(title)
    if subtitle:
        st.caption(subtitle)


def empty_state(key, title, text, actions=()):
    """A friendly empty state with the next useful actions: [(label, icon, callback, args), ...]."""
    with st.container(border=True, key=f"empty_{key}"):
        st.markdown(f"**{title}**")
        st.caption(text)
        if actions:
            cols = st.columns(len(actions) + 1)
            for col, (label, icon, cb, args) in zip(cols, actions):
                col.button(label, key=f"empty_{key}_{label}", icon=icon, on_click=cb, args=args, width="stretch")


def warning_card(key, title, text):
    """A compact warning card: amber edge, bold title, one or two lines of text."""
    with st.container(border=True, key=f"warncard_{key}"):
        st.markdown(f":material/warning: **{title}**")
        st.caption(text)


def styled(df, status_cols):
    """A table with the status columns drawn as tinted text badges (the label is always kept)."""
    cols = [c for c in status_cols if c in df.columns]
    return df.style.map(ui.status_style, subset=cols) if cols else df


def go_item_detail(item_id):
    st.session_state["detail_item"] = item_id
    open_page("Item detail")


def go_issue(item_id):
    st.session_state.update(issue_item=item_id, move_tab="Issue to ward")
    open_page("Stock movements")


def go_new_po(vendor):
    st.session_state.update(goto_view="New purchase order", new_po_vendor=vendor)
    open_page("Purchasing")


def go_history(item_id):
    st.session_state["hist_items"] = [item_id]
    open_page("History")


if PAGE == "Dashboard":
    red = plan[plan["status"].str.startswith("🔴")]
    yellow = plan[plan["status"].str.startswith("🟡")]
    at_risk = plan[plan["availability_risk"] != "🟢 OK"]
    vital_at_risk = at_risk[at_risk["ved"] == "V"]
    vital_empty = int((vital_at_risk["usable"] == 0).sum())

    # Weekly history for the KPI deltas (only recorded usage and ledger history, never invented)
    try:
        wk = kpis.weekly(conn, TODAY - pd.Timedelta(days=56), TODAY).tail(8)
    except Exception:
        wk = pd.DataFrame(columns=["week", "demand", "short", "fill_rate", "inventory_value"])
    last4 = wk.tail(4)
    fill_4w = (1 - last4["short"].sum() / last4["demand"].sum()) if last4["demand"].sum() > 0 else None
    fr = wk["fill_rate"].dropna()
    iv = wk["inventory_value"].dropna() if "inventory_value" in wk else pd.Series(dtype=float)

    # Alert inputs
    expired = lot_risk[lot_risk["days_left"] <= 0]
    soon = lot_risk[(lot_risk["days_left"] > 0) & (lot_risk["days_left"] <= 30)]
    at_dock = po_list[po_list["stage"] == "ARRIVED"] if len(po_list) else po_list
    late = po_list[po_list["late"]] if len(po_list) else po_list
    new_recalls = recall_list[pd.to_datetime(recall_list["date"]) > pd.Timestamp(TODAY) - pd.Timedelta(days=14)]
    recent_so = stockouts[stockouts["date"] > pd.Timestamp(TODAY) - pd.Timedelta(days=30)]

    # 1. Header
    st.header("Today's reorder dashboard")
    st.caption(f"{TODAY:%A, %B %d, %Y}" + (" · simulated date" if SIMULATED else ""))
    summary = [f"**{n(len(red), 'item')}** to order now", f"**{n(len(vital_at_risk), 'Vital item')}** at risk"]
    if len(recent_so):
        summary.append(f"**{n(len(recent_so), 'stockout')}** in the last 30 days")
    if len(active_outages):
        summary.append(f"**{n(len(active_outages), 'vendor')}** unable to supply")
    st.markdown(", ".join(summary[:-1]) + (" and " if len(summary) > 1 else "") + summary[-1] + ".")

    # 2. KPI cards: same layout in all four (label, value, one line of context)
    c1 = c2 = c3 = c4 = card_row("row_kpi")
    st.html("<style>" + ui.kpi_css({"kpi_now": ("cart", "red"), "kpi_vital": ("heart", "violet"),
                                    "kpi_fill": ("gauge", "green"), "kpi_value": ("dollar", "blue")}) + "</style>")
    c1.container(key="kpi_now").metric(
        "Order now", f"{len(red):,}", delta=f"{len(yellow):,} more due soon", delta_color="off", delta_arrow="off",
        help="Items at or below their reorder point (usable stock plus stock on order).")
    c2.container(key="kpi_vital").metric(
        "Vital items at risk", f"{len(vital_at_risk):,}", delta=f"{vital_empty:,} with no usable stock",
        delta_color="off", delta_arrow="off",
        help="Vital (V) items flagged by the availability projection: zero usable stock, or their "
             "usable stock runs out before the next reliable delivery. This is about what we can "
             "physically give patients, independent of the reorder point.")
    c3.container(key="kpi_fill").metric(
        "Fill rate", f"{fill_4w:.1%}" if fill_4w is not None else "n/a",
        delta=(f"{(fr.iloc[-1] - fr.iloc[-2]) * 100:+.1f} pts vs last week" if len(fr) >= 2
               else "No weekly history yet"),
        delta_color="normal" if len(fr) >= 2 else "off", delta_arrow="auto" if len(fr) >= 2 else "off",
        help="Share of requested units filled from the shelf over the last 4 weeks.")
    c4.container(key="kpi_value").metric(
        "Inventory value", f"${(plan['on_hand'] * plan['unit_cost']).sum():,.0f}",
        delta=((f"{'+' if iv.iloc[-1] >= iv.iloc[-2] else '-'}${abs(iv.iloc[-1] - iv.iloc[-2]):,.0f} vs last week")
               if len(iv) >= 2 else "No weekly history yet"),
        delta_color="off", delta_arrow="auto" if len(iv) >= 2 else "off",
        help="Inventory value on hand: stock on the shelf at unit cost.")

    # 3. Urgent inventory actions
    st.subheader("Urgent inventory actions")
    urgent = plan[plan["status"].str.startswith("🔴") | plan["availability_risk"].str.startswith("🔴")]
    urgent = (urgent.assign(risk_rank=urgent["availability_risk"].map(RISK_ORDER).fillna(9),
                            ved_rank=urgent["ved"].map({"V": 0, "E": 1, "D": 2}))
              .sort_values(["risk_rank", "ved_rank", "days_of_supply"]))
    if urgent.empty:
        st.success("Nothing urgent: no item is at its reorder point or projected to run short.")
    else:
        top = urgent.head(8)
        risk_text = np.where(top["availability_risk"] == "🟢 OK", "Order now", top["availability_risk"].map(plain))
        ut = pd.DataFrame({
            "Item": top["name"] + np.where(top["ved"] == "V", " (Vital)", ""),
            "Risk": risk_text,
            "Days left": top["days_of_supply"].clip(lower=0),
            "On order": top["on_order"].astype(int),
            "Suggested order": top["order_qty"].astype(int),
            "Vendor": top["order_vendor"],
        })
        with st.container(key="urgent_table"):
            st.dataframe(ut, hide_index=True, width="stretch", column_config={
                "Risk": st.column_config.TextColumn(help="No usable stock, then shortage risk, then items at "
                                                         "their reorder point"),
                "Days left": st.column_config.NumberColumn(format="%.1f", help="Usable stock ÷ expected daily demand"),
                "On order": st.column_config.NumberColumn(format="%d"),
                "Suggested order": st.column_config.NumberColumn(format="%d", help="From the reorder plan; 0 = "
                                                                 "not at the reorder point yet"),
            })
        st.button(f"View all {len(plan)} items", icon=":material/list:", key="view_all_items",
                  on_click=open_page, args=("Inventory",),
                  help=f"Showing the {len(top)} most urgent of {n(len(urgent), 'item')} that need action")

    # Draft purchase orders: created only on request, never sent or approved automatically
    with st.container(border=True, key="card_drafts"):
        drafted = pu.items_in_drafts(conn)
        to_order = red[(red["order_qty"] > 0) & ~red["item_id"].isin(drafted)]
        if drafted:
            st.info(f"{n(len(set(drafted.values())), 'draft PO')} with {n(len(drafted), 'item')} "
                    f"{'is' if len(set(drafted.values())) == 1 else 'are'} waiting for approval "
                    "in Purchasing. A draft is not an order yet: the vendor has not received it.")
            st.button("Review drafts in Purchasing", icon=":material/arrow_forward:", icon_position="right",
                      key="review_drafts", on_click=open_purchase_order, args=(sorted(set(drafted.values()))[0],))
        if len(to_order):
            to_order = to_order.assign(order_value=np.where(to_order["order_vendor"] != to_order["supplier"],
                                                            to_order["order_value"] * (1 + pu.BACKUP_PREMIUM),
                                                            to_order["order_value"]),
                                       name=np.where(to_order["order_vendor"] != to_order["supplier"],
                                                     to_order["name"] + " (backup)", to_order["name"]))
            to_order = to_order[~to_order["order_vendor"].isin(active_outages["supplier"])]
            sugg = (to_order.groupby("order_vendor")
                    .agg(lines=("name", "count"), items=("name", ", ".join), value=("order_value", "sum"))
                    .reset_index().rename(columns={"order_vendor": "supplier"}))
            sugg["freight"] = [pu.freight(v, x) for v, x in zip(sugg["supplier"], sugg["value"])]
            if sugg.empty:
                st.warning("Items need ordering, but their primary AND backup vendors are both disrupted. "
                           "Watch stock closely and consider substitutes until a vendor is back.")
            else:
                st.markdown(f"**Suggested purchase orders:** {n(len(sugg), 'vendor')}, "
                            f"{n(int(sugg['lines'].sum()), 'item')}, estimated **\\${sugg['value'].sum():,.0f}**"
                            + (f" plus \\${sugg['freight'].sum():,.0f} freight" if sugg["freight"].sum() else "") + ".")
                if st.button(f"Prepare {n(len(sugg), 'draft purchase order')}, one per vendor",
                             icon=":material/edit_note:", type="primary", key="prepare_drafts"):
                    made = pu.draft_suggested_orders(conn, plan)
                    if made:
                        open_purchase_order(made[0])          # take the buyer straight to the first draft
                    done(f"Drafted {', '.join(made)} with the suggested quantities. Review each one and approve "
                         "it to send it to the vendor.")
                st.caption("This only creates drafts. Nothing is sent to a vendor until you review and approve "
                           "each draft in Purchasing.")
                with st.expander("Breakdown by vendor"):
                    st.dataframe(sugg, hide_index=True, width="stretch", column_config={
                        "supplier": "Vendor", "lines": st.column_config.NumberColumn("Items", format="%d"),
                        "items": "Item names",
                        "value": st.column_config.NumberColumn("PO value", format="$%,.0f"),
                        "freight": st.column_config.NumberColumn(
                            "Freight", format="$%,.0f", help="Vendor's freight charge; free above its threshold")})
        elif not drafted:
            st.success("Nothing to order right now. Everything at risk is already on order.")

    # 4. Supply alerts: three cards with the same layout (title, status label, description, action)
    st.subheader("Supply alerts")

    def alert_card(col, key, title, question, icon_name, color, ok, text, action, page=None, po=None):
        with col.container(border=True, height="stretch", key=key):
            st.html(ui.section(title, question, icon_name, color))
            if ok:
                st.badge("All clear", icon=":material/check_circle:", color="green")
            else:
                st.badge("Needs attention", icon=":material/warning:", color="orange")
            st.markdown(text)
            if po:
                st.button(action, key="dock_receive", on_click=open_purchase_order, args=(po,),
                          icon=":material/arrow_forward:", icon_position="right")
            else:
                st.button(action, key=f"{key}_open", on_click=open_page, args=(page,),
                          icon=":material/arrow_forward:", icon_position="right")

    a1 = a2 = a3 = card_row("row_supply")
    exp_parts = []
    if len(expired):
        exp_parts.append(f"{n(len(expired), 'expired lot')} still on the shelf (\\${expired['value'].sum():,.0f})")
    if len(soon):
        exp_parts.append(f"{n(len(soon), 'lot')} expiring within 30 days")
    alert_card(a1, "supply_expiry", "Expiring stock", "Lots past or near their expiry date", "expiry", "amber",
               not exp_parts, (" and ".join(exp_parts) + ".") if exp_parts else "No expired lots and none "
               "expiring in the next 30 days.", "Review expiring lots", page="Expiry")
    if len(rising):
        names = ", ".join(f"{r.name} (+{r.change_90:.0%})" for r in rising.head(3).itertuples())
        more = f" and {len(rising) - 3} more" if len(rising) > 3 else ""
        rise_text = (f"{n(len(rising), 'item')} forecast to rise over the next 90 days: {names}{more}. "
                     "Reorder points already include the rise.")
    else:
        rise_text = "No item is forecast to rise sharply over the next 90 days."
    alert_card(a2, "supply_demand", "Rising demand", "Items getting busier in the next 90 days", "trend", "violet",
               not len(rising), rise_text, "Review the forecast", page="Forecast")
    vend_parts = []
    for o in active_outages.itertuples():
        vend_parts.append(f"{o.supplier} cannot supply until {pd.Timestamp(o.end_date):%b %d}; its items use "
                          f"the backup vendor at +{pu.BACKUP_PREMIUM:.0%}.")
    if len(late):
        vend_parts.append(f"{n(len(late), 'late delivery', 'late deliveries')}: " + ", ".join(
            f"{r.order_no} from {r.supplier} (promised {pd.Timestamp(r.promised_date):%b %d})"
            for r in late.head(3).itertuples()) + ".")
    for r in new_recalls.itertuples():
        vend_parts.append(f"Class {r.recall_class} recall of lot {r.lot_no} ({r.name}).")
    if len(at_dock):
        vend_parts.append(f"{n(len(at_dock), 'delivery', 'deliveries')} waiting at the dock and not yet usable.")
    if len(at_dock):
        v_action, v_page, v_po = f"Receive {at_dock['order_no'].iloc[0]}", None, at_dock["order_no"].iloc[0]
    elif len(active_outages) or len(new_recalls):
        v_action, v_page, v_po = "Open alerts", "Recalls & disruptions", None
    else:
        v_action, v_page, v_po = "Open purchasing", "Purchasing", None
    alert_card(a3, "supply_vendors", "Vendor delays", "Late deliveries, outages and recalls", "truck", "red",
               not vend_parts, " ".join(vend_parts) if vend_parts else "All open orders are on schedule and no "
               "vendor is disrupted.", v_action, page=v_page, po=v_po)

    # 5. Analytics: two rows of two equal cards, same height, titles and legend placement
    st.subheader("Analytics")
    CHART_H = 280
    CHART = dict(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", margin=dict(l=8, r=8, t=8, b=8),
                 font=dict(color="#4A4F6A", size=12), hoverlabel=dict(bgcolor="#FFFFFF"), height=CHART_H,
                 legend=dict(orientation="h", y=1.08, x=0, xanchor="left"))
    PLOT_CFG = {"displayModeBar": False}
    r1a = r1b = card_row("row_chart1")
    with r1a.container(border=True, height="stretch", key="card_demand"):
        card_title("Demand trend", "Units requested per week: the last 8 weeks and a 4-week forecast.")
        week0 = pd.Timestamp(TODAY).to_period("W-SUN").start_time          # Monday of the current week
        hist = usage[(usage["date"] >= week0 - pd.Timedelta(weeks=8)) & (usage["date"] < week0)]
        if len(hist):                                   # keep only weeks with all 7 days of recorded usage
            wkly = hist.set_index("date")["qty_used"].resample("W-MON", label="left", closed="left")
            days = hist.groupby(pd.Grouper(key="date", freq="W-MON", label="left", closed="left"))["date"].nunique()
            actual = wkly.sum()[days.reindex(wkly.sum().index, fill_value=0) == 7]
        else:
            actual = pd.Series(dtype=float)
        future = np.zeros(28)
        for v in daily_demand.values():
            arr = np.asarray(v, dtype=float).ravel()
            future += np.resize(arr, 28) if arr.size > 1 else np.full(28, float(arr[0]) if arr.size else 0.0)
        fweeks = pd.date_range(pd.Timestamp(TODAY), periods=4, freq="7D")
        fvals = future.reshape(4, 7).sum(axis=1)
        fig = go.Figure()
        if len(actual):
            fig.add_scatter(x=actual.index, y=actual.values.round(0), name="Actual", mode="lines+markers",
                            line=dict(color="#F2706B", width=2.5), marker=dict(size=6),
                            hovertemplate="Week of %{x|%b %d}: %{y:,.0f} units<extra>Actual</extra>")
            fx, fy = [actual.index[-1], *fweeks], [actual.values[-1], *fvals]
        else:
            fx, fy = list(fweeks), list(fvals)
        fig.add_scatter(x=fx, y=np.round(fy, 0), name="Forecast", mode="lines+markers",
                        line=dict(color="#6D4AFF", width=2.5, dash="dash"), marker=dict(size=6, symbol="diamond"),
                        hovertemplate="Week of %{x|%b %d}: %{y:,.0f} units<extra>Forecast</extra>")
        fig.update_layout(**CHART, yaxis=dict(gridcolor="#EEEAF8", zeroline=False, tickformat=",.0f"),
                          xaxis=dict(gridcolor="rgba(0,0,0,0)"), hovermode="x unified")
        st.plotly_chart(fig, width="stretch", config=PLOT_CFG, key="chart_demand")
    with r1b.container(border=True, height="stretch", key="card_status"):
        card_title("Reorder status", f"How the {len(plan)} items stand against their reorder points.")
        counts = [len(red), len(yellow), len(plan) - len(red) - len(yellow)]
        labels = [f"Order now ({counts[0]})", f"Order soon ({counts[1]})", f"Enough stock ({counts[2]})"]
        fig = go.Figure(go.Pie(labels=labels, values=counts, hole=.62, sort=False, direction="clockwise",
                               marker=dict(colors=["#F2706B", "#F5B544", "#22B3A6"],
                                           line=dict(color="#FFFFFF", width=2)),
                               textinfo="none", hovertemplate="%{label}<extra></extra>"))
        fig.update_layout(**CHART, annotations=[dict(text=f"<b>{len(plan)}</b><br>items", showarrow=False,
                                                     font=dict(size=16, color="#1B1F3B"))])
        st.plotly_chart(fig, width="stretch", config=PLOT_CFG, key="chart_status")
    r2a = r2b = card_row("row_chart2")
    with r2a.container(border=True, height="stretch", key="card_vendors"):
        card_title("Vendor performance", "Share of deliveries that arrived within the quoted lead time.")
        sc = pu.vendor_scorecard(conn).dropna(subset=["on_time"])
        if sc.empty:
            st.info("No deliveries received yet. Run the simulation clock (Planning settings) to build a "
                    "vendor history.")
        else:
            sc = sc.sort_values("on_time")
            fig = go.Figure(go.Bar(x=(sc["on_time"] * 100).round(1), y=sc["vendor"], orientation="h",
                                   marker=dict(color="#6D4AFF"), text=[f"{v:.1%}" for v in sc["on_time"]],
                                   textposition="outside", cliponaxis=False,
                                   hovertemplate="%{y}: %{x:.1f}% on time<extra></extra>"))
            fig.update_layout(**CHART, xaxis=dict(range=[0, 120], visible=False), yaxis=dict(automargin=True),
                              bargap=0.45, showlegend=False)
            st.plotly_chart(fig, width="stretch", config=PLOT_CFG, key="chart_vendors")
    with r2b.container(border=True, height="stretch", key="card_abcved"):
        card_title("ABC-VED mix", "Items by spend class (A = highest) and clinical criticality.")
        mix = pd.crosstab(plan["abc"], plan["ved"]).reindex(index=["A", "B", "C"], columns=["V", "E", "D"],
                                                              fill_value=0)
        fig = go.Figure(go.Heatmap(z=mix.values, x=["Vital", "Essential", "Desirable"], y=["A", "B", "C"],
                                   text=mix.values, texttemplate="%{text}", textfont=dict(size=14),
                                   colorscale=[[0, "#F3F1FC"], [1, "#6D4AFF"]], showscale=False, xgap=4, ygap=4,
                                   hovertemplate="Class %{y}, %{x}: %{z} items<extra></extra>"))
        fig.update_layout(**CHART, yaxis=dict(autorange="reversed"), xaxis=dict(side="top"))
        st.plotly_chart(fig, width="stretch", config=PLOT_CFG, key="chart_abcved")

# ---------------------------------------------------------------------------
# Inventory page: the full reorder plan with filters (moved here from the dashboard)
# ---------------------------------------------------------------------------
if PAGE == "Inventory":
    page_header("Inventory", f"All {len(plan)} items as of {ui.fmt_date(TODAY)}. Search or pick a view, then "
                             "select a row to open the item, issue stock or order it.")
    STATUSES = ["🔴 Order now", "🟡 Order soon", "🟢 OK"]
    RISKS = ["🔴 No usable stock", "🔴 Shortage risk", "🟡 Shortage watch", "🟢 Enough stock"]
    VED_NAMES = {"V": "Vital", "E": "Essential", "D": "Desirable"}
    SORTS = {"Reorder status (red first)": ["status_rank", "ved_rank", "days_of_supply"],
             "Reorder status (green first)": ["status_rank_desc", "ved_rank", "days_of_supply"],
             "Availability risk (worst first)": ["risk_rank", "ved_rank", "days_of_supply"],
             "Criticality (Vital first)": ["ved_rank", "status_rank", "days_of_supply"],
             "Days of supply (lowest first)": ["days_of_supply", "ved_rank"],
             "Order value (highest first)": ["order_value", "ved_rank"]}
    base = plan.assign(availability_risk=plan["availability_risk"].replace({"🟢 OK": "🟢 Enough stock"}))
    expiring_ids = set(lot_risk.loc[lot_risk["days_left"] <= 30, "item_id"])
    QUICK = {"All": base.index == base.index,
             "Order now": base["status"].str.startswith("🔴"),
             "Shortage risk": base["availability_risk"].isin(RISKS[:2]),
             "Incoming": base["on_order"] > 0,
             "Expiring": base["item_id"].isin(expiring_ids)}
    QUICK_HELP = {"Order now": "Usable plus on order is at or below the reorder point",
                  "Shortage risk": "Usable stock runs out within 7 days (or a Vital item has none)",
                  "Incoming": "An order for the item is on its way",
                  "Expiring": "A lot on the shelf has expired or expires within 30 days"}
    FILTER_KEYS = {"inv_search": "", "inv_quick": "All", "dash_status": [], "dash_risk": [], "dash_ved": [],
                   "dash_sort": list(SORTS)[0]}

    def clear_filters():
        for k, v in FILTER_KEYS.items():
            st.session_state[k] = v

    with st.container(border=True, key="toolbar_inventory"):
        t1, t2 = st.columns([2, 3], vertical_alignment="top")
        search = t1.text_input("Search", key="inv_search", placeholder="Item name or ID, e.g. insulin or MED007",
                               icon=":material/search:")
        quick = t2.segmented_control(
            "Quick view", list(QUICK), key="inv_quick", default="All", required=True, wrap=True,
            format_func=lambda q: f"{q} ({int(QUICK[q].sum())})",
            help="  \n".join(f"**{k}**: {v}" for k, v in QUICK_HELP.items()))
        with st.expander("More filters and columns", icon=":material/tune:"):
            f1, f2, f3, f4 = st.columns(4)
            status_filter = f1.multiselect("Reorder status", STATUSES, placeholder="All", key="dash_status",
                                           format_func=ui.plain_status,
                                           help="Is it time to place an order? From the reorder point.")
            risk_filter = f2.multiselect("Availability", RISKS, placeholder="All", key="dash_risk",
                                         format_func=ui.plain_status,
                                         help="Will usable stock last? Projected over the next 90 days.")
            ved_filter = f3.multiselect("Criticality", list(VED_NAMES), format_func=VED_NAMES.get,
                                        placeholder="All", key="dash_ved")
            sort_by = f4.selectbox("Sort by", list(SORTS), key="dash_sort")
            EXTRA = {"status": "Reorder status", "availability_risk": "Availability", "on_hand": "On hand",
                     "rop": "Reorder point", "safety_stock": "Safety stock", "ved": "VED", "abc": "ABC",
                     "order_value": "Order value"}
            extra_cols = st.multiselect("Extra columns", list(EXTRA), format_func=EXTRA.get, key="inv_cols",
                                        placeholder="Add calculation columns")

    view = base.assign(status_rank=base["status"].map({s: i for i, s in enumerate(STATUSES)}),
                       status_rank_desc=-base["status"].map({s: i for i, s in enumerate(STATUSES)}),
                       risk_rank=base["availability_risk"].map({s: i for i, s in enumerate(RISKS)}).fillna(9),
                       ved_rank=base["ved"].map({"V": 0, "E": 1, "D": 2}))
    view = view[QUICK[quick or "All"]]
    if search.strip():
        q = search.strip().lower()
        view = view[view["name"].str.lower().str.contains(q, regex=False)
                    | view["item_id"].str.lower().str.contains(q, regex=False)]
    if status_filter:
        view = view[view["status"].isin(status_filter)]
    if risk_filter:
        view = view[view["availability_risk"].isin(risk_filter)]
    if ved_filter:
        view = view[view["ved"].isin(ved_filter)]
    view = view.sort_values(SORTS[sort_by], ascending=[c != "order_value" for c in SORTS[sort_by]])

    active = ([f'search "{search.strip()}"'] if search.strip() else []) + \
             ([f"view: {quick}"] if quick and quick != "All" else []) + \
             ([("reorder status: " + ", ".join(map(ui.plain_status, status_filter)))] if status_filter else []) + \
             ([("availability: " + ", ".join(map(ui.plain_status, risk_filter)))] if risk_filter else []) + \
             ([("criticality: " + ", ".join(VED_NAMES[v] for v in ved_filter))] if ved_filter else [])
    hidden_vital_risk = plan[(plan["ved"] == "V") & plan["availability_risk"].str.startswith("🔴")
                             & ~plan.index.isin(view.index)]
    a1, a2 = st.columns([3, 1], vertical_alignment="center")
    a1.markdown(f"Showing **{len(view)} of {len(plan)}** items" +
                (" · Filters on: " + "; ".join(active) if active else "") +
                (f"  \n:red-badge[:material/error: {n(len(hidden_vital_risk), 'Vital item')} at risk "
                 f"{'is' if len(hidden_vital_risk) == 1 else 'are'} hidden by these filters]"
                 if len(hidden_vital_risk) and active else ""))
    a2.button("Clear filters", key="inv_clear", on_click=clear_filters, icon=":material/filter_alt_off:",
              disabled=not active, width="stretch")

    table = view.assign(primary=[ui.primary_status(s, a) for s, a in zip(view["status"], view["availability_risk"])],
                        status=view["status"].map(ui.plain_status),
                        availability_risk=view["availability_risk"].map(ui.plain_status),
                        ved=view["ved"].map(VED_NAMES))
    table = table[["name", "item_id", "primary", "usable", "on_order", "days_of_supply", "order_qty", "supplier",
                   "status", "availability_risk", "on_hand", "rop", "safety_stock", "ved", "abc",
                   "order_value"]].reset_index(drop=True)
    p1, p2, _ = st.columns([1, 1, 4])
    page_size = p1.selectbox("Rows per page", [25, 50, 100, "All"], index=1, key="inv_page_size")
    pages = 1 if page_size == "All" else max(1, math.ceil(len(table) / page_size))
    page_no = p2.number_input(f"Page (of {pages})", 1, pages, 1, key="inv_page") if pages > 1 else 1
    shown = table if page_size == "All" else table.iloc[(page_no - 1) * page_size: page_no * page_size]
    if shown.empty:
        empty_state("inventory", "No items match", "Try a different search or quick view, or clear the filters.",
                    [("Clear filters", ":material/filter_alt_off:", clear_filters, ())])
        picked = None
    else:
        event = st.dataframe(
            styled(shown, ["primary", "status", "availability_risk"]), hide_index=True, width="stretch",
            key="inv_table", on_select="rerun", selection_mode="single-row",
            column_order=["name", "item_id", "primary", "usable", "on_order", "days_of_supply", "order_qty",
                          "supplier", *extra_cols],
            column_config={
                "name": st.column_config.TextColumn("Item", width="medium"),
                "item_id": st.column_config.TextColumn("ID", width="small"),
                "primary": st.column_config.TextColumn(
                    "Status", help="The more urgent of reorder status and availability (see How statuses work)"),
                "usable": st.column_config.NumberColumn("Usable", format="%d", help="On hand minus expired lots"),
                "on_order": st.column_config.NumberColumn("On order", format="%d"),
                "days_of_supply": st.column_config.NumberColumn("Days of supply", format="%.1f",
                                                                help="Usable stock ÷ forecast daily use"),
                "order_qty": st.column_config.NumberColumn("Suggested order", format="%d"),
                "supplier": st.column_config.TextColumn("Vendor"),
                "status": "Reorder status", "availability_risk": "Availability",
                "on_hand": st.column_config.NumberColumn("On hand", format="%d"),
                "rop": st.column_config.NumberColumn("Reorder point", format="%.0f"),
                "safety_stock": st.column_config.NumberColumn("Safety stock", format="%.0f"),
                "ved": "VED", "abc": "ABC",
                "order_value": st.column_config.NumberColumn("Order value", format="$%,.0f"),
            })
        rows = event.selection.rows if event and hasattr(event, "selection") else []
        picked = shown.iloc[rows[0]] if rows else None
    with st.container(border=True, key="toolbar_selected"):
        if picked is None:
            st.caption(":material/touch_app: Select a row (the box at the left of the table) to open the item, "
                       "issue it or order it.")
        else:
            row = plan[plan["item_id"] == picked["item_id"]].iloc[0]
            st.markdown(f"**{row['name']}** ({row['item_id']}) {ui.badge_md(picked['primary'])}  \n"
                        f"Usable {ui.fmt_int(row['usable'])} {row['unit']} · on order {ui.fmt_int(row['on_order'])} · "
                        f"{ui.fmt_num(row['days_of_supply'])} days of supply · suggested order "
                        f"{ui.fmt_int(row['order_qty'])}")
            b1, b2, b3, b4 = st.columns(4)
            b1.button("Open item detail", key="inv_go_detail", icon=":material/info:", on_click=go_item_detail,
                      args=(row["item_id"],), width="stretch", type="primary")
            b2.button("Issue stock", key="inv_go_issue", icon=":material/output:", on_click=go_issue,
                      args=(row["item_id"],), width="stretch")
            b3.button("Create purchase order", key="inv_go_po", icon=":material/add_shopping_cart:",
                      on_click=go_new_po, args=(row["order_vendor"],), width="stretch")
            b4.button("View history", key="inv_go_hist", icon=":material/history:", on_click=go_history,
                      args=(row["item_id"],), width="stretch")
    st.download_button(f"Download {n(len(view), 'item')} as CSV", key="inv_csv", icon=":material/download:",
                       data=view.drop(columns=["status_rank", "status_rank_desc", "risk_rank", "ved_rank"])
                       .assign(status=view["status"].map(ui.plain_status),
                               availability_risk=view["availability_risk"].map(ui.plain_status)).to_csv(index=False),
                       file_name=f"medstock_inventory_{TODAY:%Y-%m-%d}.csv", mime="text/csv",
                       help="Every column with full precision, for the items shown (all pages)")

    with card_row("row_inv_footer"):
        with st.container(border=True, key="card_inv_orders"):
            sugg = plan[plan["order_qty"] > 0]
            card_title("Suggested orders",
                       f"{n(len(sugg), 'item')} from {n(sugg['order_vendor'].nunique(), 'vendor')}, "
                       f"estimated {ui.fmt_money(sugg['order_value'].sum())} before freight.")
            st.button("Prepare drafts on the Dashboard", key="inv_go_dash", icon=":material/arrow_forward:",
                      icon_position="right", on_click=open_page, args=("Dashboard",))
        capped = plan[plan["order_capped"]]
        if len(capped):
            with st.container(border=True, key="card_inv_shelf"):
                card_title(f":material/warning: Shelf life limits {n(len(capped), 'order')}",
                           ", ".join(capped["name"].head(3)) + (" and others" if len(capped) > 3 else "") +
                           ": one order cannot reach the full target before about 80% of the shelf life runs out. "
                           "Plan staged deliveries or expedited freight, and check again after the first receipt.")
    with st.expander("How statuses work", icon=":material/help:"):
        st.markdown(
            f"- {ui.badge_md('Order now')}: usable plus on order is at or below the reorder point.\n"
            f"- {ui.badge_md('Order soon')}: it will reach the reorder point within about 7 days.\n"
            f"- {ui.badge_md('No usable stock')} / {ui.badge_md('Shortage risk')} / {ui.badge_md('Shortage watch')}: "
            "usable stock projected day by day runs out now, within 7 days, or within 30 days. A delivery only "
            "counts on the day it is due.\n"
            "- **Status** shows the more urgent of the two. An item can be OK for ordering (an order is placed) "
            "and still at risk (that order arrives too late).\n"
            "- The measured fill rate from logged requests is on **Reports**.")

# ---------------------------------------------------------------------------
# Stock movements page: record what physically happens in the storeroom
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
# Confirmations. Every irreversible action and every simulated event asks first.
# A button only stores the request (ask); the dialog shows exactly what will change; only Confirm
# changes data. Each request has an id and is removed before it runs, so a Streamlit rerun or a
# double click can never apply it twice.
# ---------------------------------------------------------------------------
def ask(kind, **params):
    """Open the confirmation for an action. Nothing changes until the user presses Confirm."""
    st.session_state["pending_action"] = {"id": str(uuid.uuid4()), "kind": kind, **params}


def cancel_pending():
    st.session_state.pop("pending_action", None)


def lot_info(lot_id):
    return conn.execute("SELECT l.*, i.name, i.unit, i.unit_cost, i.ved FROM lots l JOIN items i USING (item_id) "
                        "WHERE l.lot_id = ?", (lot_id,)).fetchone()


def expired_lot_rows():
    """The lots db.write_off_all_expired would write off today (same query)."""
    return pd.read_sql("SELECT l.lot_id, l.lot_no, l.qty, l.expiry_date, i.name, i.unit, i.unit_cost FROM lots l "
                       "JOIN items i USING (item_id) WHERE l.qty > 0 AND l.expiry_date <= ? ORDER BY l.expiry_date",
                       conn, params=(TODAY.isoformat(),))


def describe_action(p):
    """What the confirmation shows: title, facts, an optional table, the expected effect, and whether it is
    a simulated event. 'blocked' explains why Confirm is unavailable."""
    k = p["kind"]
    if k == "recall":
        pv = events.recall_preview(conn, p["lot_no"])
        sim_ = p["origin"] != "Manual"
        wards = ", ".join(f"{w} ({q:,})" for w, q in pv["wards"].items()) or "None yet"
        return dict(
            title=("Simulated manufacturer recall" if sim_ else "Issue a recall") + f" for lot {p['lot_no']}",
            simulated=True,
            facts=[("Item", f"{pv['name']} ({pv['item_id']})"), ("Lot", p["lot_no"]),
                   ("Units pulled from the shelf", f"{ui.fmt_int(pv['qty'])} {pv['unit']}"),
                   ("Value written off", ui.fmt_money(pv["value"], cents=True)),
                   ("Recall class", events.RECALL_CLASSES[p["recall_class"]]), ("Reason", p["reason"]),
                   ("Wards that already received it", wards),
                   ("Deliveries of this lot still on the way", ui.fmt_int(pv["incoming_lines"]))],
            effect="Every unit of this lot leaves usable stock at once and is recorded as a recall loss, not as "
                   "demand. The wards listed above need to be told. Any delivery that carries this lot will be "
                   "refused at the dock. The item may move to Order now. A recall stays on record and cannot be "
                   "undone.",
            confirm="Confirm recall", danger=True,
            blocked=None if pv["item_id"] else f"Lot {p['lot_no']} is not in stock and not on its way.")
    if k == "outage":
        affected = plan[plan["supplier"] == p["supplier"]]
        open_with = po_list[(po_list["supplier"] == p["supplier"]) & po_list["stage"].isin(["SENT", "CONFIRMED"])] \
            if len(po_list) else po_list
        until = TODAY + pd.Timedelta(days=int(p["days"]) - 1)
        sim_ = p["origin"] != "Manual"
        return dict(
            title=("Simulated vendor disruption" if sim_ else "Start a vendor disruption") + f": {p['supplier']}",
            simulated=True,
            facts=[("Vendor", p["supplier"]), ("Length", f"{n(int(p['days']), 'day')}, until {ui.fmt_date(until)}"),
                   ("Reason", p["reason"]),
                   ("Items that switch to a backup vendor", ui.fmt_int(len(affected))),
                   ("Orders with this vendor not yet confirmed", ui.fmt_int(len(open_with)))],
            table=affected[["name", "backup_supplier"]].rename(columns={"name": "Item", "backup_supplier": "Backup vendor"}).head(10),
            effect=f"Orders sent to {p['supplier']} during the disruption are rejected. New orders for its items go "
                   f"to each item's backup vendor at {pu.BACKUP_PREMIUM:.0%} higher price. Deliveries already "
                   f"shipped still arrive. You can end it early on this page with \"{p['supplier']} is supplying again\".",
            confirm="Start disruption", danger=True,
            blocked=f"{p['supplier']} is already disrupted." if pu.active_outage(conn, p["supplier"], TODAY) else None)
    if k == "write_off_lot":
        lot = lot_info(p["lot_id"])
        if lot is None:
            return dict(title="Write off stock", facts=[], effect="", confirm="Write off", danger=True,
                        simulated=False, blocked="This lot no longer exists.")
        days_left = (date.fromisoformat(lot["expiry_date"]) - TODAY).days
        on_hand_now = int(plan.loc[plan["item_id"] == lot["item_id"], "on_hand"].iloc[0])
        return dict(
            title=f"Write off {ui.fmt_int(p['qty'])} {lot['unit']} of {lot['name']}", simulated=False,
            facts=[("Item", f"{lot['name']} ({lot['item_id']})"), ("Lot", lot["lot_no"]),
                   ("Expiry", f"{ui.fmt_date(lot['expiry_date'])} ({ui.expiry_phrase(days_left)})"),
                   ("Quantity", f"{ui.fmt_int(p['qty'])} of {ui.fmt_int(lot['qty'])} {lot['unit']} in this lot"),
                   ("Value", ui.fmt_money(p["qty"] * lot["unit_cost"], cents=True)), ("Reason", p["reason"]),
                   ("Date", ui.fmt_date(p["date"]))],
            effect=f"The units leave stock and are recorded as waste ({p['reason'].lower()}). Item on hand goes from "
                   f"{ui.fmt_int(on_hand_now)} to {ui.fmt_int(on_hand_now - p['qty'])}. A write-off is not demand, so "
                   "the forecast does not change. It cannot be undone; if it was a mistake, correct the shelf "
                   "quantity with a cycle count.",
            confirm="Write off", danger=True,
            blocked=f"Lot {lot['lot_no']} only has {lot['qty']:,} left." if p["qty"] > lot["qty"] else None)
    if k == "write_off_expired":
        rows = expired_lot_rows()
        changed = sorted(rows["lot_id"].tolist()) != sorted(p["lot_ids"])
        table = pd.DataFrame({"Item": rows["name"], "Lot": rows["lot_no"],
                              "Expired": [ui.expiry_phrase((date.fromisoformat(e) - TODAY).days) for e in rows["expiry_date"]],
                              "Quantity": rows["qty"].map(ui.fmt_int),
                              "Value": (rows["qty"] * rows["unit_cost"]).map(lambda v: ui.fmt_money(v, cents=True))})
        return dict(
            title=f"Write off all {n(len(rows), 'expired lot')}", simulated=False,
            facts=[("Lots", ui.fmt_int(len(rows))), ("Units", ui.fmt_int(rows["qty"].sum())),
                   ("Value", ui.fmt_money((rows["qty"] * rows["unit_cost"]).sum(), cents=True)),
                   ("Reason", "Expired"), ("Date", ui.fmt_date(TODAY))],
            table=table,
            effect="Every lot above leaves stock and is recorded as expiry waste. MedStock already refuses to issue "
                   "expired stock, so usable stock does not change, but on-hand stock and inventory value drop. It "
                   "cannot be undone.",
            confirm="Write off all", danger=True,
            blocked="The list of expired lots changed after you opened this. Close it and review the list again."
            if changed else None)
    if k == "issue":
        r = item_row(p["item_id"])
        usable = int(r["usable"])
        short = max(0, p["qty"] - usable)
        effect = (f"Only {ui.fmt_int(usable)} {r['unit']} can be served, picked earliest-expiry first. The other "
                  f"{ui.fmt_int(short)} are logged as a stockout and still count as demand." if short else
                  f"All {ui.fmt_int(p['qty'])} {r['unit']} are picked earliest-expiry first. Usable stock goes from "
                  f"{ui.fmt_int(usable)} to {ui.fmt_int(usable - p['qty'])}.")
        return dict(
            title=f"Issue {ui.fmt_int(p['qty'])} {r['unit']} of {r['name']} to {p['ward']}", simulated=False,
            facts=[("Item", f"{r['name']} ({r['item_id']})"), ("Department", p["ward"]),
                   ("Quantity", f"{ui.fmt_int(p['qty'])} {r['unit']}"), ("Usable now", f"{ui.fmt_int(usable)} {r['unit']}"),
                   ("Average daily use", f"{ui.fmt_num(r['d'])} {r['unit']} per day"), ("Date", ui.fmt_date(p["date"]))],
            effect=effect + " The request is recorded in the ledger and cannot be undone.",
            confirm="Issue stock", danger=False, blocked=None)
    if k in ("po_send", "po_new_send"):
        sup = p["supplier"]
        by_id = plan.set_index("item_id")
        lines_ = [(i, int(q)) for i, q in p["lines"] if int(q) > 0]
        subtotal = sum(q * pu.unit_price(by_id.loc[i], sup) for i, q in lines_)
        fr = pu.freight(sup, subtotal)
        table = pd.DataFrame([{"Item": by_id.at[i, "name"], "Quantity": ui.fmt_int(q),
                               "Amount": ui.fmt_money(q * pu.unit_price(by_id.loc[i], sup), cents=True)} for i, q in lines_])
        blocked = "The order has no lines with a quantity above 0." if not lines_ else None
        if pu.active_outage(conn, sup, TODAY):
            blocked = f"{sup} cannot supply right now, so the order would be rejected. Use the backup vendor."
        return dict(
            title=f"Approve and send {'purchase order ' + p['order_no'] if k == 'po_send' else 'a new purchase order'} to {sup}",
            simulated=True,
            facts=[("Vendor", f"{sup} (orders via {pu.VENDORS[sup]['method']})"), ("Lines", ui.fmt_int(len(lines_))),
                   ("Subtotal", ui.fmt_money(subtotal, cents=True)), ("Freight", ui.fmt_money(fr, cents=True)),
                   ("Total", ui.fmt_money(subtotal + fr, cents=True)), ("Need by", ui.fmt_date(p["need_by"]))],
            table=table,
            effect="Approving sends the order to the vendor now. The vendor is simulated: it acknowledges, ships "
                   "and sometimes runs late or short as the clock moves. You can still cancel until it ships.",
            confirm="Approve and send", danger=False, blocked=blocked)
    if k == "end_outage":
        o = pu.active_outage(conn, p["supplier"], TODAY)
        affected = plan[plan["supplier"] == p["supplier"]]
        facts = [("Vendor", p["supplier"])]
        if o:
            facts += [("Current disruption", f"{ui.fmt_date(o['start_date'])} to {ui.fmt_date(o['end_date'])}, "
                                             f"{o['reason'] or 'no reason given'} ({o['origin']})"),
                      ("Items now ordered from a backup vendor", ui.fmt_int(len(affected)))]
        return dict(
            title=f"End the disruption: {p['supplier']} is supplying again", simulated=True, facts=facts,
            effect=f"The disruption ends yesterday, so {p['supplier']} can supply from today. New orders for its "
                   f"{n(len(affected), 'item')} may go back to it at the usual price instead of the backup vendor. "
                   "Orders already placed with backup vendors are not changed. The ended disruption stays in the "
                   "event history.",
            confirm="Vendor is supplying again", danger=False,
            blocked=None if o and int(o["outage_id"]) == int(p["outage_id"])
            else f"{p['supplier']} is no longer disrupted, or the disruption changed. Close this and check again.")
    if k == "refuse_line":
        po = conn.execute("SELECT p.*, i.name, i.unit FROM purchase_orders p JOIN items i USING (item_id) "
                          "WHERE p.po_id = ?", (p["po_id"],)).fetchone()
        if po is None:
            return dict(title="Refuse a delivery line", facts=[], effect="", confirm="Refuse line", danger=True,
                        simulated=False, blocked="This order line no longer exists.")
        line = f" line {po['line_no']}" if po["line_no"] is not None else ""
        refused = int(p.get("qty", po["qty"]))
        return dict(
            title=f"Refuse {ui.fmt_int(refused)} {po['unit']} of {po['name']} at the dock", simulated=True,
            facts=[("Purchase order", f"{po['order_no'] or po['po_id']}{line}"),
                   ("Item", f"{po['name']} ({po['item_id']})"),
                   ("Quantity refused", f"{ui.fmt_int(refused)} {po['unit']} (all that is still outstanding)"),
                   ("Vendor", po["supplier"])],
            effect="The line is cancelled and no longer counts as on order, so the item may move to Order now. "
                   "Nothing is received into stock. A refused line cannot be reopened; order the item again if "
                   "you still need it.",
            confirm="Refuse line", danger=True,
            blocked=None if po["status"] == "OPEN" else "This line is no longer open (already received or cancelled).")
    if k == "po_delete":
        return dict(title=f"Delete draft {p['order_no']}", simulated=False,
                    facts=[("Purchase order", p["order_no"]), ("Vendor", p["supplier"])],
                    effect="The draft is cancelled and its items are no longer on any draft. Nothing was sent to the "
                           "vendor. A deleted draft cannot be restored; create a new one if needed.",
                    confirm="Delete draft", danger=True, blocked=None)
    if k == "po_cancel":
        return dict(title=f"Cancel purchase order {p['order_no']}", simulated=True,
                    facts=[("Purchase order", p["order_no"]), ("Vendor", p["supplier"])],
                    effect="The vendor is told to stop, and the items are no longer counted as on order, so they may "
                           "move to Order now. A cancelled order cannot be reopened.",
                    confirm="Cancel order", danger=True, blocked=None)
    raise ValueError(f"Unknown action {k}")


def apply_action(p):
    """Carry out a confirmed action. Returns (level, message) for the result banner."""
    k = p["kind"]
    if k == "recall":
        res = events.recall_lot(conn, p["lot_no"], p["recall_class"], p["reason"], origin=p["origin"])
        wards = ", ".join(f"{w} ({q})" for w, q in res["wards"].items()) or "none yet"
        return "success", (f"Recall of lot {res['lot_no']} ({item_labels[res['item_id']]}): {res['removed']:,} units "
                           f"(${res['value']:,.0f}) pulled. Wards to notify: {wards}.")
    if k == "outage":
        end = events.start_outage(conn, p["supplier"], int(p["days"]), p["reason"], origin=p["origin"])
        return "success", f"{p['supplier']} cannot supply until {ui.fmt_date(end)}. New orders go to backup vendors."
    if k == "write_off_lot":
        lot = lot_info(p["lot_id"])
        new = db.write_off(conn, p["lot_id"], p["qty"], p["reason"], p["date"], p["note"])
        return "success", (f"Wrote off {p['qty']:,} × {lot['name']} from lot {lot['lot_no']} ({p['reason']}). "
                           f"Loss: {ui.fmt_money(p['qty'] * lot['unit_cost'], cents=True)}. On hand now: {new:,} {lot['unit']}.")
    if k == "write_off_expired":
        count, value = db.write_off_all_expired(conn, TODAY)
        return "success", f"Wrote off {n(count, 'expired lot')} worth {ui.fmt_money(value, cents=True)}."
    if k == "issue":
        r = item_row(p["item_id"])
        res = db.fulfill_request(conn, p["item_id"], p["qty"], p["ward"], p["date"], p["note"], p["req_id"])
        st.session_state["issue_req_id"] = str(uuid.uuid4())
        pick_text = ", ".join(f"lot {no} × {q}" for no, q in res["picks"])
        left = int(db.on_hand(conn, p["item_id"]))
        if res["short"]:
            return "error", (f"Only **{res['filled']:,} of {res['requested']:,} {r['unit']}** could be served to "
                             f"{p['ward']}. {res['short']:,} was **not available** and is logged as a stockout (and "
                             f"counts as demand). Take from shelf: {pick_text or 'nothing'}.")
        return "success", (f"Issued {p['qty']:,} × {r['name']} to {p['ward']}. Take from shelf: {pick_text}. "
                           f"On hand now: {left:,} {r['unit']}.")
    if k == "po_send":
        pu.update_draft(conn, p["order_no"], p["lines"], p["need_by"], p["notes"])
        pu.send_order(conn, p["order_no"])
        st.session_state["open_order"] = p["next_order"] or p["order_no"]
        return "success", (f"{p['order_no']} sent to {p['supplier']} via {pu.VENDORS[p['supplier']]['method']}. " +
                           (f"Next draft: {p['next_order']}." if p["next_order"] else
                            "No drafts left. Move the clock forward to see the vendors respond."))
    if k == "po_new_send":
        order_no = pu.create_order(conn, p["supplier"], p["lines"], p["need_by"], p["notes"])
        pu.send_order(conn, order_no)
        st.session_state.update(open_order=order_no, goto_view=PO_VIEW)
        return "success", f"{order_no} sent to {p['supplier']}. Move the clock forward to see the vendor respond."
    if k == "end_outage":
        events.end_outage(conn, p["supplier"])
        return "success", f"{p['supplier']} is back. New orders can go to it again."
    if k == "refuse_line":
        name = item_labels.get(p["item_id"], p["item_id"])
        db.cancel_po(conn, p["po_id"], "Refused at the dock")
        return "success", f"Line refused at the dock: {name} is no longer on order."
    if k == "po_delete":
        pu.cancel_order(conn, p["order_no"], "Draft deleted")
        if p.get("next_order"):
            st.session_state["open_order"] = p["next_order"]
        return "success", f"Draft {p['order_no']} deleted."
    if k == "po_cancel":
        pu.cancel_order(conn, p["order_no"], "Cancelled by buyer")
        return "success", f"{p['order_no']} cancelled."
    raise ValueError(f"Unknown action {k}")


def confirm_dialog():
    """Draw the confirmation for the pending action (call once, near the end of the run)."""
    p = st.session_state.get("pending_action")
    if not p:
        return
    try:
        spec = describe_action(p)
    except Exception as e:                    # the records changed underneath (e.g. after a reset)
        st.session_state.pop("pending_action", None)
        st.error(f"That action is no longer available: {e}")
        return

    def body():
        st.markdown(f"**{ui.md_safe(spec['title'])}**")
        st.markdown(":violet-badge[:material/science: Simulated event · fictional data]" if spec["simulated"]
                    else ":gray-badge[:material/info: Fictional data]")
        st.markdown("\n".join(f"- **{label}:** {ui.md_safe(value)}" for label, value in spec["facts"]))
        if spec.get("table") is not None and len(spec["table"]):
            st.dataframe(spec["table"], hide_index=True, width="stretch", height=min(300, 38 + 35 * len(spec["table"])))
        st.markdown(f"**What will happen.** {ui.md_safe(spec['effect'])}")
        if spec.get("blocked"):
            st.error(spec["blocked"], icon=":material/block:")
        c1, c2 = st.columns(2)
        c1.button("Cancel", key="confirm_no", on_click=cancel_pending, width="stretch")
        with c2.container(key="confirm_danger" if spec["danger"] else "confirm_safe"):
            go_ahead = st.button(spec["confirm"], key="confirm_yes", type="primary", width="stretch",
                                 disabled=bool(spec.get("blocked")))
        if go_ahead:
            current = st.session_state.pop("pending_action", None)       # claim it: it can run only once
            ran = st.session_state.setdefault("done_actions", set())
            if current is None or current["id"] != p["id"] or p["id"] in ran:
                st.rerun()
            ran.add(p["id"])
            try:
                level, message = apply_action(p)
            except db.StockError as e:
                level, message = "error", f"Nothing was changed: {e}"
            st.cache_data.clear()
            done(message, level)

    st.dialog("Please confirm", width="medium", on_dismiss=cancel_pending)(body)()



# ---------------------------------------------------------------------------
# KPIs page: is inventory management working, and is it getting better?
# ---------------------------------------------------------------------------
def pct(x, digits=1):
    return "n/a" if x is None or pd.isna(x) else f"{x:.{digits}%}"


if PAGE == "KPIs":
    page_header("Reports", "Key performance indicators: is inventory management working, and is it getting better?")
    PERIODS = {"Last 30 days": 30, "Last 90 days": 90, "Last 365 days": 365}
    period = st.segmented_control("Period", list(PERIODS), default="Last 90 days", required=True, key="kpi_period")
    k_start = TODAY - pd.Timedelta(days=PERIODS[period] - 1)
    k = kpis.compute(conn, k_start, TODAY)
    n_requests = conn.execute("SELECT COUNT(*) FROM demand_requests").fetchone()[0]
    NO_LEDGER = ("Needs stock movements recorded in the app. The stock ledger starts with the first issue, receipt "
                 "or simulated day; move the clock forward in Planning settings.")
    NO_DELIVERY = "No deliveries arrived in this period. Send purchase orders and move the clock forward."
    with st.container(border=True, key="card_kpi_ready"):
        ready = [k["fill_rate"] is not None, k["avg_inventory"] is not None, k["on_time"] is not None]
        st.markdown(f"**Data readiness: {sum(ready)} of 3 groups have data** for {ui.fmt_date(k_start)} to "
                    f"{ui.fmt_date(TODAY)}.")
        st.caption(
            f"Service uses daily usage and stockouts ({n(n_requests, 'request')} logged in the app). Money uses the "
            "stock ledger" + (f", which starts on {ui.fmt_date(k['inventory_since'])}" if k["inventory_since"]
                             else ", which has no movements yet") +
            ". Supply uses delivered purchase orders. Cards in gray cannot be calculated yet; hover the "
            ":material/help: icon to see why.")

    section("Service", "Are patients getting what they need?", "heart", "green")
    c = st.columns(4)
    kpi(c[0], "Fill rate", ui.fmt_pct(k["fill_rate"], 2), "check", "green",
        missing=None if k["fill_rate"] is not None else "No demand was recorded in this period.",
        help="Units served ÷ units requested. Target 98%+.")
    kpi(c[1], "Vital fill rate", ui.fmt_pct(k["fill_by_ved"]["V"], 2), "heart", "violet",
        missing=None if k["fill_by_ved"]["V"] is not None else "No demand for Vital items in this period.",
        help="Same, Vital items only. Target 99.5%+.")
    kpi(c[2], "Stockout events", f"{k['stockout_events']:,}", "alert", "red",
        help="Item-days on which a request could not be filled in full")
    kpi(c[3], "Vital stockout events", f"{k['vital_stockout_events']:,}", "alert", "amber",
        help="Stockout events for Vital items only")
    with st.expander("Measured fill rate from logged requests", icon=":material/fact_check:",
                     expanded=False):
        st.caption("Requests actually logged in this app (ward issues and simulated demand) since it was set up, "
                   "not the synthetic history. Compare with the predicted fill rate in Item detail, which comes "
                   "from the service level.")
        requests = pd.read_sql("SELECT * FROM demand_requests", conn)
        if requests.empty:
            st.info("No ward requests have been logged yet. Record them in Stock movements > Issue to ward, or run "
                    "the simulation; every request (served or short) is counted here.")
        else:
            measured = requests.groupby("item_id").agg(requests=("requested", "sum"),
                                                       served=("filled", "sum"), short=("short", "sum")).reset_index()
            measured = measured.merge(plan[["item_id", "name", "ved", "unit"]], on="item_id")
            measured["fill_rate"] = measured["served"] / measured["requests"]
            overall = requests["filled"].sum() / requests["requested"].sum()
            st.metric("Overall measured fill rate", ui.fmt_pct(overall),
                      help="Served ÷ requested across all logged requests.")
            st.dataframe(measured.sort_values("fill_rate")[["name", "ved", "unit", "requests", "served", "short",
                                                            "fill_rate"]], hide_index=True, width="stretch",
                         column_config={
                             "name": "Item", "ved": "VED", "unit": "Unit", "requests": "Requested", "served": "Served",
                             "short": "Short (stockouts)",
                             "fill_rate": st.column_config.ProgressColumn("Measured fill rate", format="percent",
                                                                          min_value=0, max_value=1)})

    section("Money", "How much is tied up, and how much is lost?", "dollar", "blue")
    c = st.columns(4)
    kpi(c[0], "Average inventory", ui.fmt_money(k["avg_inventory"]), "dollar", "blue",
        missing=None if k["avg_inventory"] else NO_LEDGER, help="Average dollar value on the shelf over the period")
    kpi(c[1], "Turns per year", ui.fmt_num(k["turns"]), "repeat", "violet",
        missing=None if k["turns"] else NO_LEDGER + " Turns also need issues to wards.",
        help="Yearly value issued ÷ average inventory. Higher = leaner. Hospital supplies often run 8-12.")
    kpi(c[2], "Days on hand", ui.fmt_num(k["days_on_hand"], 0), "calendar", "amber",
        missing=None if k["days_on_hand"] else NO_LEDGER + " Days on hand also need issues to wards.",
        help="How many days the average stock would last at the current usage rate")
    kpi(c[3], "Waste", ui.fmt_money(k["waste_total"]), "trash", "red",
        help="Written-off value (expiry, damage) plus stock pulled by recalls")
    if k["waste_total"]:
        parts = [f"{r}: {ui.fmt_money(v)}" for r, v in k["waste_by_reason"].items()]
        if k["recall_value"]:
            parts.append(f"Recalls: {ui.fmt_money(k['recall_value'])}")
        st.caption(ui.md_safe("Waste by reason: " + " · ".join(parts)))

    section("Supply", "Are vendors reliable?", "truck", "violet")
    c = st.columns(4)
    kpi(c[0], "On-time deliveries", ui.fmt_pct(k["on_time"], 0), "clock", "green",
        missing=None if k["on_time"] is not None else NO_DELIVERY, help="Arrived by the vendor's promised date")
    kpi(c[1], "Vendor fill rate", ui.fmt_pct(k["vendor_fill"]), "truck", "blue",
        missing=None if k["vendor_fill"] is not None else NO_DELIVERY,
        help="Units confirmed ÷ units ordered (backorders lower it)")
    kpi(c[2], "Orders rejected", f"{k['rejected_orders']:,}", "xcircle", "red",
        help="Rejected by a vendor during a supply disruption")
    kpi(c[3], "Backup vendor spend", ui.fmt_pct(k["backup_share"]), "users", "amber",
        missing=None if k["backup_share"] is not None else "No purchase orders were sent in this period.",
        help=f"Share of purchasing spend ({ui.fmt_money(k['spend'])}) placed with a backup vendor at a higher price")
    st.caption(f"{n(k['recalls'], 'recall')} and {n(k['outage_days'], 'vendor-disruption day')} in this period.")
    if not k["vendors"].empty:
        st.dataframe(k["vendors"], hide_index=True, width="stretch", column_config={
            "vendor": "Vendor", "deliveries": "Deliveries",
            "on_time": st.column_config.ProgressColumn("On time", format="percent", min_value=0, max_value=1),
            "avg_lead_time": st.column_config.NumberColumn("Avg lead time (days)", format="%.1f"),
            "fill_rate": st.column_config.ProgressColumn("Fill rate", format="percent", min_value=0, max_value=1),
            "rejected_orders": "Rejected orders"})

    section("Trend by week", "Is it getting better or worse?", "trend", "violet")
    wk = kpis.weekly(conn, k_start, TODAY)
    if wk.empty:
        empty_state("kpi_trend", "No activity in this period yet",
                    "Move the simulation clock forward (Planning settings > +7 days) to generate weekly results.")
    else:
        g1, g2 = st.columns(2)
        fr = wk.dropna(subset=["fill_rate"])
        fig = px.line(fr, x="week", y="fill_rate", markers=True, title="Fill rate by week",
                      labels={"week": "Week starting", "fill_rate": "Fill rate"})
        low = float(fr["fill_rate"].min()) if len(fr) else 0.9
        fig.update_traces(line_color=ui.COLORS["green"])
        fig.update_layout(yaxis_tickformat=".1%", yaxis_range=[max(0.0, min(0.9, low - 0.02)), 1.005], height=300,
                          margin=dict(t=40, b=10))
        g1.plotly_chart(fig, width="stretch")
        if len(fr):
            g1.caption(f"Chart summary: weekly fill rate ranged from {ui.fmt_pct(fr['fill_rate'].min())} to "
                       f"{ui.fmt_pct(fr['fill_rate'].max())}; the axis stops at 100%.")
        if "inventory_value" in wk and wk["inventory_value"].notna().any():
            iv = wk.dropna(subset=["inventory_value"])
            fig = px.line(iv, x="week", y="inventory_value", markers=True, title="Inventory value at week end",
                          labels={"week": "Week starting", "inventory_value": "Inventory value"})
            fig.update_traces(line_color=ui.COLORS["violet"])
            fig.update_layout(yaxis_tickprefix="$", yaxis_tickformat=",.0f", yaxis_rangemode="tozero", height=300,
                              margin=dict(t=40, b=10))
            g2.plotly_chart(fig, width="stretch")
            g2.caption(ui.md_safe(f"Chart summary: from {ui.fmt_money(iv['inventory_value'].iloc[0])} to "
                                  f"{ui.fmt_money(iv['inventory_value'].iloc[-1])} over {n(len(iv), 'week')}."))
        st.download_button("Download weekly results as CSV", wk.to_csv(index=False),
                           f"medstock_kpis_{k_start:%Y-%m-%d}_{TODAY:%Y-%m-%d}.csv", "text/csv",
                           icon=":material/download:", key="kpi_csv")
        st.caption("Try it: raise or lower the Vital service level in Planning settings, simulate a few weeks, and "
                   "watch fill rate and inventory value move in opposite directions. That is the trade-off "
                   "safety stock manages.")

# ---------------------------------------------------------------------------
# Recalls & disruptions page: when the supply chain goes wrong
# ---------------------------------------------------------------------------
if PAGE == "Recalls & disruptions":
    page_header("Recalls & vendor disruptions",
                "Simulated, fictional events. Start one to see how the reorder system reacts. Every action asks "
                "you to confirm first. Random events can also happen on their own (Planning settings > Random events).")
    st.markdown(":violet-badge[:material/science: Simulation · fictional data]")

    section("Active events", "What is affecting supply right now?", "alert", "red")
    c = st.columns(3)
    kpi(c[0], "Vendors disrupted now", len(active_outages), "factory", "red")
    kpi(c[1], "Recalls in the last 14 days", len(recalls_14d), "alert", "amber")
    kpi(c[2], "Value pulled by recalls", ui.fmt_money(recall_list["value_removed"].sum()) if len(recall_list) else "$0",
        "dollar", "violet", help="All recalls so far")
    if active_outages.empty and recalls_14d.empty:
        st.caption(":material/check_circle: No active disruptions and no recent recalls.")
    for o in active_outages.itertuples():
        affected = plan[plan["supplier"] == o.supplier]
        with st.container(border=True, key=f"card_outage_{o.outage_id}"):
            st.markdown(f"{ui.badge_md('Active')} **{o.supplier}** cannot supply until {ui.fmt_date(o.end_date)} "
                        f"({o.reason}).  \n{n(len(affected), 'item')} {'switches' if len(affected) == 1 else 'switch'} "
                        "to a backup vendor: " + ", ".join(f"{r.name} (now from {r.backup_supplier})"
                                                            for r in affected.head(5).itertuples())
                        + (f" and {len(affected) - 5} more." if len(affected) > 5 else "."))
            if st.button(f"{o.supplier} is supplying again", icon=":material/check_circle:", key=f"end_outage_{o.outage_id}",
                         help="Ends the disruption today. New orders go to this vendor again. You confirm first."):
                ask("end_outage", supplier=o.supplier, outage_id=int(o.outage_id))

    a, b = st.columns(2, gap="medium")
    with a.container(border=True, key="card_recall"):
        st.html(ui.section("Product recalls", "A lot is unsafe: pull it and trace it", "alert", "red"))
        st.caption("Every unit of the lot on the shelf is pulled, the wards that received it are listed, and "
                   "deliveries of that lot are refused.")
        lots_on_hand = lots[lots["qty"] > 0].merge(plan[["item_id", "name", "ved"]], on="item_id")
        lots_on_hand = lots_on_hand[~lots_on_hand["lot_no"].isin(recall_list["lot_no"])]
        with st.form("recall_form", border=False):
            lot_opts = list(dict.fromkeys(lots_on_hand["lot_no"]))
            lot_desc = {r.lot_no: f"{r.lot_no} · {r.name} ({r.ved}) · {int(r.qty):,} on hand · exp. {r.expiry_date:%b %Y}"
                        for r in lots_on_hand.itertuples()}
            lot_pick = st.selectbox("Lot to recall", lot_opts, format_func=lot_desc.get, key="recall_lot")
            f1, f2 = st.columns(2)
            cls = f1.selectbox("Recall class", list(events.RECALL_CLASSES), index=1,
                               format_func=events.RECALL_CLASSES.get, key="recall_class")
            reason = f2.selectbox("Reason", events.RECALL_REASONS, key="recall_reason")
            do_recall = st.form_submit_button("Review recall for this lot", icon=":material/warning:", type="primary",
                                              disabled=not lot_opts, key="recall_submit")
            do_random = st.form_submit_button("Simulate a random manufacturer recall", icon=":material/shuffle:",
                                              key="recall_random")
    with b.container(border=True, key="card_outage"):
        st.html(ui.section("Vendor disruptions", "A vendor cannot supply: orders move to backups", "factory", "amber"))
        st.caption(f"Orders sent to the vendor are rejected, and new orders go to each item's backup vendor at "
                   f"{pu.BACKUP_PREMIUM:.0%} higher price. Shipped orders still arrive.")
        with st.form("outage_form", border=False):
            o_vendor = st.selectbox("Vendor", list(pu.VENDORS), key="outage_vendor")
            f1, f2 = st.columns([1, 2])
            o_days = f1.number_input("Length (days)", 1, 90, 14, key="outage_days")
            o_reason = f2.selectbox("Reason", events.OUTAGE_REASONS, key="outage_reason")
            do_outage = st.form_submit_button("Review disruption", icon=":material/factory:", type="primary",
                                              key="outage_submit")
            do_random_outage = st.form_submit_button("Simulate a random disruption", icon=":material/shuffle:",
                                                     key="outage_random")
    if do_recall and lot_pick:
        ask("recall", lot_no=lot_pick, recall_class=cls, reason=reason, origin="Manual")
    if do_random:
        pick = events.pick_random_recall(conn, on_date=TODAY)       # chosen now, applied only after Confirm
        if pick:
            ask("recall", origin="Simulated notice", **pick)
        else:
            st.info("No lot on the shelf to recall.")
    if do_outage:
        ask("outage", supplier=o_vendor, days=int(o_days), reason=o_reason, origin="Manual")
    if do_random_outage:
        pick = events.pick_random_outage(conn, on_date=TODAY)
        if pick:
            ask("outage", origin="Simulated", **pick)
        else:
            st.info("Every vendor is already disrupted.")

    section("Event history", "Every recall and disruption so far", "history", "green")
    h1, h2 = st.tabs(["Recalls", "Vendor disruptions"])
    with h1:
        if recall_list.empty:
            st.caption("No recalls yet.")
        else:
            st.dataframe(recall_list[["date", "lot_no", "name", "ved", "recall_class", "reason", "qty_removed",
                                      "value_removed", "wards", "origin"]], hide_index=True, width="stretch",
                         column_config={"date": st.column_config.DateColumn("Date", format="MMM D, YYYY"),
                                        "lot_no": "Lot", "name": "Item", "ved": "VED", "recall_class": "Class",
                                        "reason": "Reason", "qty_removed": "Pulled from shelf",
                                        "value_removed": st.column_config.NumberColumn("Value lost", format="$%,.0f"),
                                        "wards": "Already issued to (notify)", "origin": "Source"})
            st.caption("Usable stock dropped, so a recalled item may now be Order now. Full movement history of any "
                       "lot: History > Lot trace.")
    with h2:
        if outage_list.empty:
            st.caption("No vendor disruptions yet.")
        else:
            ol = outage_list.assign(state=outage_list["state"].map(ui.plain_status))
            st.dataframe(styled(ol[["state", "supplier", "start_date", "end_date", "days", "reason", "origin"]], ["state"]),
                         hide_index=True, width="stretch", column_config={
                             "state": "Status", "supplier": "Vendor", "start_date": "From", "end_date": "Until",
                             "days": "Days", "reason": "Reason", "origin": "Source"})

# ---------------------------------------------------------------------------
# Purchasing page: vendor purchase orders, from draft to delivery (vendors are simulated)
# ---------------------------------------------------------------------------
def stage_bar(current):
    """The order's progress as a step tracker: done steps filled, the current step ringed."""
    if current == "CANCELLED":
        return '<span class="ms-cancel">Cancelled</span>'
    now = pu.STAGES.index(current)
    steps = []
    for i, name in enumerate(pu.STAGES):
        state = "done" if i < now else "now" if i == now else ""
        mark = "✓" if i < now else str(i + 1)
        steps.append(f'<div class="ms-step {state}"><i>{mark}</i><span>{pu.STAGE_LABELS[name].split(" (")[0]}</span></div>')
    return '<div class="ms-steps">' + "".join(steps) + "</div>"


def vendor_card(name):
    v = pu.VENDORS[name]
    return (f"**{name}**  \n{v['address']}  \nContact: {v['contact']} · {v['email']} · {v['phone']}  \n"
            f"Our account no. {v['account_no']} · Orders via **{v['method']}** · Terms {v['terms']}  \n"
            f"Ship via {v['ship_via']} · Quoted lead time **{v['quoted_days']} days** · "
            f"Minimum order \\${v['min_order']:,} · Free freight over \\${v['free_freight_over']:,} "
            f"(else \\${v['freight_fee']:,})")


def order_summary(supplier, subtotal):
    v = pu.VENDORS[supplier]
    fr = pu.freight(supplier, subtotal)
    st.markdown(f"Subtotal **\\${subtotal:,.2f}** · Freight \\${fr:,.2f} · **Total \\${subtotal + fr:,.2f}**")
    if 0 < subtotal < v["min_order"]:
        st.warning(f"Below {supplier}'s minimum order of \\${v['min_order']:,}. The vendor may reject it or charge "
                   "a small-order fee. Consider adding items that will need ordering soon (🟡).")
    elif fr and subtotal >= 0.5 * v["free_freight_over"]:
        st.caption(f"\\${v['free_freight_over'] - subtotal:,.0f} more and freight is free.")


if PAGE == "Purchasing":
    page_header("Purchasing", "One purchase order (PO) per vendor, one line per item. MedStock fills in quantities "
                              "and prices; you review, approve and send. Vendors are fictional and respond as the "
                              "simulation clock moves.")
    stage_counts = po_list["stage"].value_counts() if len(po_list) else pd.Series(dtype=int)
    m = st.columns(5)
    STAGE_HELP = {
        "Drafts to approve": "Prepared by you or MedStock but not approved. The vendor has not seen it, so it does "
                             "not count as on order.",
        "With the vendor": "Approved and sent. The vendor has received it and may have confirmed quantities and a "
                           "promised date.",
        "In transit": "The vendor shipped it and sent a ship notice with lots and expiry dates.",
        "At the dock": "Delivered and waiting to be received into stock.",
        "Late": "Past the vendor's promised date and not yet received."}
    kpi(m[0], "Drafts", int(stage_counts.get("DRAFT", 0)), "edit", "violet",
        help=STAGE_HELP["Drafts to approve"])
    kpi(m[1], "With vendor", int(stage_counts.get("SENT", 0) + stage_counts.get("CONFIRMED", 0)), "send", "blue",
        help=STAGE_HELP["With the vendor"])
    kpi(m[2], "In transit", int(stage_counts.get("SHIPPED", 0)), "truck", "green", help=STAGE_HELP["In transit"])
    kpi(m[3], "At the dock", int(stage_counts.get("ARRIVED", 0)), "box", "amber", help=STAGE_HELP["At the dock"])
    kpi(m[4], "Late", int(po_list["late"].sum()) if len(po_list) else 0, "clock", "red", help=STAGE_HELP["Late"])
    with st.expander("What the order stages mean", icon=":material/help:"):
        st.markdown("\n".join(f"- **{k}**: {v}" for k, v in STAGE_HELP.items()) +
                    "\n\nReview, approval and sending are separate steps: **Save changes** keeps a draft, **Review and "
                    "approve** shows the full order, and only **Approve and send** sends it. MedStock never sends "
                    "an order on its own unless you turn on fully automatic reordering in Planning settings.")

    BUY_VIEWS = ["Purchase orders", "New purchase order", "Vendors"]
    if "goto_view" in st.session_state:                 # switch view after creating a PO
        st.session_state["buy_view"] = st.session_state.pop("goto_view")
    buy_tabs = st.tabs(BUY_VIEWS, key="buy_view", on_change="rerun")
    buy_view = next((v for v, t in zip(BUY_VIEWS, buy_tabs) if t.open), BUY_VIEWS[0])   # only the open tab is drawn

    def show_new_po():
        st.session_state["goto_view"] = "New purchase order"

    with buy_tabs[BUY_VIEWS.index(buy_view)]:
        if buy_view == "Purchase orders":
            if po_list.empty:
                empty_state("po", "No purchase orders yet",
                            "Create one by hand, or prepare suggested orders (one draft per vendor) on the Dashboard.",
                            [("Review suggested orders", ":material/dashboard:", open_page, ("Dashboard",)),
                             ("Create purchase order", ":material/add_circle:", show_new_po, ())])
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
                        st.caption(f"{n(len(drafts_left), 'more draft')} waiting for approval: " +
                                   ", ".join(f"{o} ({label.at[o, 'supplier']})" for o in drafts_left))
                    h = pu.order_header(conn, order_no)
                    current = pu.stage(h, TODAY)
                    lines = pu.order_lines(conn, order_no)
                    st.html(stage_bar(current))

                    with st.container(border=True):
                        a, b = st.columns(2)
                        a.markdown("**Vendor**  \n" + vendor_card(h["supplier"]))
                        b.markdown(f"**Ship to**  \n{pu.HOSPITAL['name']}  \n{pu.HOSPITAL['dept']}  \n{pu.HOSPITAL['address']}")
                        b.markdown(f"PO **{order_no}** · created {h['created_date']} by {h['origin']}  \n"
                                   f"Need by: {h['need_by'] or 'n/a'}  \nNotes: {h['notes'] or 'n/a'}")

                        if current == "DRAFT":
                            if pu.active_outage(conn, h["supplier"], TODAY):
                                st.error(f"{h['supplier']} cannot supply right now: if you send this order it "
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
                            stored_need = date.fromisoformat(h["need_by"]) if h["need_by"] else None
                            need_by = c1.date_input("Need by", value=max(stored_need, TODAY) if stored_need   # a past date
                                                    else TODAY + pd.Timedelta(days=pu.VENDORS[h["supplier"]]["quoted_days"]),
                                                    min_value=TODAY, key=f"need_{order_no}", format="MM/DD/YYYY",
                                                    help="Moved to today if the saved date has already passed")
                            notes = c2.text_input("Notes to vendor", value=h["notes"] or "", key=f"notes_{order_no}")
                            b1, b2, b3 = st.columns(3)
                            clean_lines = [(str(i), int(q or 0)) for i, q in new_lines]
                            if b1.button("Review and approve", icon=":material/send:", type="primary", key=f"send_{order_no}"):
                                ask("po_send", order_no=order_no, supplier=h["supplier"], lines=clean_lines,
                                    need_by=need_by, notes=notes, next_order=drafts_left[0] if drafts_left else None)
                            if b2.button("Save changes", icon=":material/save:", key=f"save_{order_no}"):
                                _, err = run(pu.update_draft, order_no, new_lines, need_by, notes)
                                if not err:
                                    done(f"{order_no} saved (still a draft).")
                            if b3.button("Delete draft", icon=":material/delete:", key=f"del_{order_no}"):
                                ask("po_delete", order_no=order_no, supplier=h["supplier"],
                                    next_order=drafts_left[0] if drafts_left else None)
                        else:
                            acked = h["ack_date"] and h["ack_date"] <= TODAY.isoformat()
                            shipped = h["ship_date"] and h["ship_date"] <= TODAY.isoformat()
                            hidden = pd.Series(None, index=lines.index, dtype=object)
                            asn = {p: db.asn_lots(conn, p) for p in lines["po_id"]} if shipped else {}
                            show = lines.assign(              # only show what the vendor has told us so far
                                confirmed=lines["confirmed_qty"] if acked else hidden,
                                lot=[", ".join(l for l, _, _ in asn.get(p, [])) or None for p in lines["po_id"]]
                                if shipped else hidden,
                                expiry=[min((e for _, e, _ in asn.get(p, [])), default=None) for p in lines["po_id"]]
                                if shipped else hidden)
                            st.dataframe(show[["line_no", "item_id", "name", "unit", "qty", "confirmed", "unit_cost",
                                               "amount", "lot", "expiry", "status", "received_qty"]],
                                         hide_index=True, width="stretch", column_config={
                                             "line_no": "Line", "qty": "Ordered",
                                             "confirmed": st.column_config.NumberColumn(
                                                 "Confirmed", help="What the vendor confirmed it can supply (after acknowledgement)"),
                                             "unit_cost": st.column_config.NumberColumn("Unit price", format="$%.2f"),
                                             "amount": st.column_config.NumberColumn("Amount", format="$%,.2f"),
                                             "lot": st.column_config.TextColumn("Lots (ASN)", help="From the vendor's ship notice. One line can arrive as several lots."),
                                             "expiry": "Expiry (ASN)", "received_qty": "Received"})
                            order_summary(h["supplier"], float(lines["amount"].sum()))

                    st.markdown("**Vendor messages**")
                    for when, msg in pu.vendor_messages(conn, order_no, TODAY):
                        st.markdown(f"- **{when:%b %d}**: {msg}")
                    if current in ("SENT", "CONFIRMED", "SHIPPED"):
                        eta = h["arrive_date"] if current == "SHIPPED" else h["promised_date"]
                        st.caption(f"Next: {'delivery' if current == 'SHIPPED' else 'the vendor ships it'}. "
                                   f"Expected around {pd.Timestamp(eta):%b %d}. Use Next in the sidebar to jump ahead.")

                    c1, c2, c3 = st.columns(3)
                    if current == "ARRIVED":
                        if c1.button("Receive whole shipment (as per ASN)", icon=":material/inventory:", type="primary", key=f"recv_{order_no}"):
                            got, err = run(pu.receive_order, order_no)
                            if not err:
                                done(f"Received {order_no}: " + ", ".join(f"{n} × {q:,} (lot {l}, lead time {lt} d)"
                                                                        for n, q, l, lt in got))
                        c1.caption("Different quantity or lot on the boxes? Receive line by line in Stock movements.")
                    if current in ("SENT", "CONFIRMED"):
                        if c2.button("Cancel order", icon=":material/cancel:", key=f"cancel_{order_no}"):
                            ask("po_cancel", order_no=order_no, supplier=h["supplier"])
                    c3.download_button("Download PO document", pu.po_document_html(conn, order_no),
                                       f"{order_no}.html", "text/html", key=f"doc_{order_no}", icon=":material/download:",
                                       help="A printable purchase order (open it in your browser and print or save as PDF)")

        elif buy_view == "New purchase order":
            vendor_names = list(pu.VENDORS)
            red_counts = plan[plan["status"].str.startswith("🔴")].groupby("order_vendor").size()
            down = set(active_outages["supplier"])
            supplier = st.selectbox("Vendor", vendor_names, key="new_po_vendor",
                                    format_func=lambda v: f"{v} ({n(int(red_counts.get(v, 0)), 'item')} to order now)"
                                                          + (" · DISRUPTED" if v in down else ""))
            if supplier in down:
                st.error(f"{supplier} cannot supply right now. Orders sent to it will be rejected.")
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
            if b1.button("Review and approve", icon=":material/send:", type="primary", disabled=chosen.empty,
                         key="new_po_send"):
                ask("po_new_send", supplier=supplier, lines=[(str(i), int(q)) for i, q in lines_in],
                    need_by=need_by, notes=notes)
            if b2.button("Save as draft", icon=":material/save:", disabled=chosen.empty):
                order_no, err = run(pu.create_order, supplier, lines_in, need_by, notes)
                if not err:
                    st.session_state.update(open_order=order_no, goto_view=PO_VIEW)
                    done(f"Draft {order_no} saved. Approve it in Purchase orders.")

        else:
            st.subheader("Vendor directory")
            st.caption("Fictional vendors. In a real hospital this is the vendor master, usually with contract prices "
                       "negotiated by a group purchasing organization (GPO).")
            directory = pd.DataFrame([{"vendor": n, "contact": v["contact"], "email": v["email"], "phone": v["phone"],
                                       "orders via": v["method"], "terms": v["terms"], "ship via": v["ship_via"],
                                       "min order": v["min_order"], "free freight over": v["free_freight_over"],
                                       "items": int((plan["supplier"] == n).sum()),
                                       "backup for": int((plan["backup_supplier"] == n).sum()),
                                       "status": "Disrupted" if n in set(active_outages["supplier"]) else "Supplying"}
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


if PAGE == "Stock movements":
    page_header("Stock movements", "Record what physically happens in the storeroom. To order stock, use Purchasing.")
    MOVES = ["Issue to ward", "Receive delivery", "Write-off", "Cycle count"]
    move_tabs = st.tabs(MOVES, key="move_tab", on_change="rerun")
    action = next((t for t, tab in zip(MOVES, move_tabs) if tab.open), MOVES[0])   # only the open tab is drawn
    with move_tabs[MOVES.index(action)]:

        if action == "Issue to ward":
            st.caption("Picked earliest-expiry first (FEFO); expired lots are never issued. Anything requested but "
                       "not available is logged as a stockout and still counts as demand.")
            iid = pick_item("issue_item")
            r = item_row(iid)
            c1, c2, c3 = st.columns(3)
            ward = c1.selectbox("Department", db.WARDS, key="issue_ward")
            qty = c2.number_input(f"Quantity ({r['unit']})", min_value=1, step=1, value=1, key="issue_qty")
            c2.caption(f"Usable now: **{ui.fmt_int(r['usable'])} {r['unit']}** · on hand {ui.fmt_int(r['on_hand'])} · "
                       f"reorder point {ui.fmt_int(r['rop'])}")
            when = c3.date_input("Date", value=TODAY, max_value=TODAY, key="issue_date", format="MM/DD/YYYY")
            note = st.text_input("Note (optional)", key="issue_note", placeholder="e.g. requested by")
            if "issue_req_id" not in st.session_state:
                st.session_state["issue_req_id"] = str(uuid.uuid4())
            unusual = qty > r["usable"] or (r["d"] > 0 and qty > 10 * r["d"])   # more than usable, or > 10 days of use
            if st.button("Issue stock", type="primary", key="issue_submit"):
                if unusual:                       # confirm first; the dialog shows what can really be served
                    ask("issue", item_id=iid, qty=int(qty), ward=ward, date=when, note=note,
                        req_id=st.session_state["issue_req_id"])
                    res, err = None, True
                else:
                    res, err = run(db.fulfill_request, iid, qty, ward, when, note, st.session_state["issue_req_id"])
                if not err:
                    st.session_state["issue_req_id"] = str(uuid.uuid4())
                    pick_text = ", ".join(f"lot {no} × {q}" for no, q in res["picks"])
                    if res["short"]:
                        st.error(f"Only **{res['filled']:,} of {res['requested']:,} {r['unit']}** could be served to "
                                 f"{ward}. {res['short']:,} was **not available** and is logged as a stockout "
                                 f"(and counts as demand). Take from shelf: {pick_text or 'nothing'}.")
                    else:
                        left = r["usable"] - qty
                        warn = " Now at or below the reorder point." if left + r["on_order"] <= r["rop"] else ""
                        done(f"All {qty:,} × {r['name']} issued to {ward}. Take from shelf: {pick_text}. "
                             f"Usable now: {left:,} {r['unit']}.{warn}", "warning" if warn else "success")

        elif action == "Receive delivery":
            st.caption("Goods arrived at the dock. Check the boxes against the vendor's ship notice (ASN): quantity, "
                       "lot number and expiry date are pre-filled from it; change them if the boxes say otherwise. "
                       "The real lead time is saved, so the σL estimate keeps getting better.")
            at_dock = open_pos[open_pos["arrive_date"].isna() | (open_pos["arrive_date"] <= pd.Timestamp(TODAY))]
            if at_dock.empty:
                coming = open_pos["arrive_date"].dropna()
                st.info("Nothing is waiting at the receiving dock." + (
                    f" {n(open_pos['order_no'].nunique(), 'order')} on the way. Check Purchasing or press "
                    "Next in the sidebar to jump to the next delivery." if len(open_pos) else
                    " Order stock in Purchasing."))
            else:
                labels = {p.po_id: f"{p.order_no or p.po_id}"
                                   f"{f' line {p.line_no:.0f}' if pd.notna(p.line_no) else ''} · {item_labels[p.item_id]} · "
                                   f"{p.qty:,} outstanding"
                          for p in at_dock.itertuples()}
                po_id = st.selectbox("Delivery line", list(labels), format_func=labels.get)
                po = at_dock[at_dock["po_id"] == po_id].iloc[0]
                r = item_row(po["item_id"])
                outstanding = int(po["qty"])
                asn = db.asn_lots(conn, po_id)
                if sum(q for _, _, q in asn) != outstanding:      # partial receipt so far: one row for the rest
                    asn = asn[:1]
                    asn = [(asn[0][0], asn[0][1], outstanding)] if asn else []
                if not asn:
                    asn = [("", (TODAY + pd.Timedelta(days=int(r["shelf_life_days"]))).date(), outstanding)]
                when = st.date_input("Date received", value=TODAY, max_value=TODAY,
                                     min_value=po["order_date"].date(), key=f"recv_date_{po_id}")
                st.markdown("**Lots in this delivery.** One row per lot number on the boxes. Add a row if the vendor "
                            "sent more lots than the ship notice says; enter less than expected for a short delivery.")
                lot_table = st.data_editor(
                    pd.DataFrame(asn, columns=["lot_no", "expiry_date", "qty"]), num_rows="dynamic",
                    key=f"recv_lots_{po_id}", hide_index=True, width="stretch", column_config={
                        "lot_no": st.column_config.TextColumn("Lot number", required=True),
                        "expiry_date": st.column_config.DateColumn("Expiry date", required=True, format="YYYY-MM-DD"),
                        "qty": st.column_config.NumberColumn("Quantity", min_value=1, step=1, required=True)})
                lot_table = lot_table.dropna(how="all")
                entered = [(str(x.lot_no or ""), pd.Timestamp(x.expiry_date).date(), int(x.qty))
                           for x in lot_table.itertuples() if pd.notna(x.qty) and pd.notna(x.expiry_date)]
                qty = sum(q for _, _, q in entered)
                expiry = min((e for _, e, _ in entered), default=TODAY)
                st.caption(f"Receiving **{qty:,}** of {outstanding:,} outstanding in {n(len(entered), 'lot')}."
                           + (f" Pre-filled from the vendor's ship notice for {po['order_no']}." if pd.notna(po["asn_lot_no"])
                              else ""))
                if outstanding < int(po["ordered_qty"]):
                    st.caption(f"This line is a **partial receipt**: {outstanding:,} of {int(po['ordered_qty']):,} "
                               f"ordered units are still outstanding (vendor backorder or earlier short delivery). "
                               "What you enter now is added to what was already received.")
                no_conf = po["expected_date"] < pd.Timestamp(TODAY)
                if no_conf:
                    st.warning("This delivery is overdue. If it is really at the dock, receive it now; "
                               "otherwise chase the vendor (its ETA is no longer reliable).")
                # Smart check: can we use this lot before it expires, at today's usage rate?
                if r["d"] > 0 and expiry > TODAY:
                    days_to_use = (r["usable"] + qty) / r["d"]
                    days_left = (expiry - TODAY).days
                    if days_to_use > days_left:
                        waste = (r["usable"] + qty) - r["d"] * days_left
                        st.warning(f"At {r['d']:.1f} {r['unit']}/day it takes about {days_to_use:.0f} days to use "
                                   f"this delivery plus current stock, but this lot expires in {days_left} days. "
                                   f"About {min(waste, qty):,.0f} units may expire unused. Consider refusing it "
                                   f"or asking the vendor for a longer-dated lot.")
                note = st.text_input("Note (optional)", key="recv_note", placeholder="e.g. packing slip no.")
                b1, b2 = st.columns([1, 4])
                if b1.button("Receive", type="primary"):
                    lt, err = run(db.receive_lots, po_id, entered, when, note)
                    if not err:
                        done(f"Received {qty:,} × {r['name']} in {n(len(entered), 'lot')}. Actual lead time: {lt} days. "
                             f"On hand now: {int(db.on_hand(conn, po['item_id'])):,} {r['unit']}.")
                if b2.button("Refuse / cancel this line", key="refuse_line"):
                    ask("refuse_line", po_id=str(po_id), item_id=po["item_id"], qty=outstanding)

        elif action == "Write-off":
            st.caption("Stock that can no longer be used. A write-off is not demand, so it does not change the "
                       "forecast. You confirm before it is saved.")
            iid = pick_item("wo_item")
            r = item_row(iid)
            item_lots = lots[lots["item_id"] == iid]
            if item_lots.empty:
                st.info("This item has no stock.")
            else:
                lot_labels = {l.lot_id: f"Lot {l.lot_no} · {ui.expiry_phrase((l.expiry_date - pd.Timestamp(TODAY)).days)}"
                                        f" ({ui.fmt_date(l.expiry_date)}) · {l.qty:,} {r['unit']} left"
                              for l in item_lots.itertuples()}
                lot_id = st.selectbox("Lot", list(lot_labels), format_func=lot_labels.get, key=f"wo_lot_{iid}")
                lot = item_lots[item_lots["lot_id"] == lot_id].iloc[0]
                is_expired = lot["expiry_date"] <= pd.Timestamp(TODAY)
                c1, c2, c3 = st.columns(3)
                reason = c1.selectbox("Reason (required)", db.WRITE_OFF_REASONS, index=0 if is_expired else None,
                                      placeholder="Choose a reason", key=f"wo_r_{lot_id}")
                qty = c2.number_input(f"Quantity ({r['unit']})", min_value=1, step=1, max_value=int(lot["qty"]),
                                      value=int(lot["qty"]) if is_expired else 1, key=f"wo_qty_{lot_id}")
                c2.caption(f"{ui.fmt_int(lot['qty'])} {r['unit']} in this lot · value "
                           f"{ui.fmt_money(qty * r['unit_cost'], cents=True)}")
                when = c3.date_input("Date", value=TODAY, max_value=TODAY, key="wo_date", format="MM/DD/YYYY")
                note = st.text_input("Note (optional)", key="wo_note", placeholder="e.g. found damaged in receiving")
                if not reason:
                    st.caption(":material/info: Choose a reason to continue.")
                if st.button("Review write-off", type="primary", key="wo_submit", disabled=not reason):
                    ask("write_off_lot", lot_id=int(lot_id), qty=int(qty), reason=reason, date=when, note=note)

        else:
            st.caption("Count what is on the shelf, lot by lot. The system quantity stays hidden until you save "
                       "(a blind count), so it cannot influence the counter. Empty lots are listed too.")
            iid = pick_item("cc_item")
            cc_unit = item_row(iid)["unit"]
            item_lots = pd.read_sql("SELECT * FROM lots WHERE item_id = ? ORDER BY expiry_date, lot_id", conn,
                                    params=(iid,), parse_dates=["expiry_date", "received_date"])
            if item_lots.empty:
                st.info("The system has no lots for this item.")
            else:
                lot_labels = {l.lot_id: f"Lot {l.lot_no} · expires {ui.fmt_date(l.expiry_date)}"
                                        f"{' · empty' if l.qty == 0 else ''}"
                              for l in item_lots.itertuples()}
                lot_id = st.selectbox("Lot", list(lot_labels), format_func=lot_labels.get, key=f"cc_lot_{iid}")
                c1, c2 = st.columns(2)
                counted = c1.number_input(f"Counted quantity ({cc_unit})", min_value=0, step=1, value=0,
                                          key=f"cc_qty_{lot_id}")
                when = c2.date_input("Date", value=TODAY, max_value=TODAY, key="cc_date", format="MM/DD/YYYY")
                note = st.text_input("Note (optional)", key="cc_note", placeholder="e.g. counted by")
                if st.button("Save count", type="primary", key="cc_submit"):
                    lot_no = item_lots.loc[item_lots["lot_id"] == lot_id, "lot_no"].iloc[0]
                    diff, err = run(db.cycle_count, lot_id, counted, when, note)
                    if not err:
                        expected = int(counted) - int(diff)
                        left = int(db.on_hand(conn, iid))
                        done(f"Lot {lot_no}: counted {int(counted):,} {cc_unit}, the system expected {expected:,}. " +
                             ("The count matches." if diff == 0 else
                              f"Difference of {diff:+,} corrected; check for unrecorded issues or receipts.") +
                             f" Item on hand now: {left:,} {cc_unit}.", "success" if diff == 0 else "warning")

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
        st.caption("Details, vendor messages and tracking: Purchasing.")

# ---------------------------------------------------------------------------
# Forecast page: what will demand be, and how good is each method?
# ---------------------------------------------------------------------------
if PAGE == "Forecast":
    page_header("Demand forecast", "Which items will get busier, by how much, and how reliable each forecast is.")
    if fc_method == SIMPLE:
        st.warning("Reorder points currently use a simple average (Planning settings). The forecasts below are "
                   "shown for comparison only.")
    falling = outlook[outlook["change_90"] <= -0.15] if len(outlook) else outlook
    c = st.columns(4)
    kpi(c[0], "Rising 15%+", len(rising), "trend", "violet",
        help="Forecast daily use over the next 90 days is at least 15% above the last 30 days")
    kpi(c[1], "Vital items rising", int((rising["ved"] == "V").sum()) if len(rising) else 0, "heart", "red")
    kpi(c[2], "Falling 15%+", len(falling), "trend", "blue",
        help="Forecast daily use over the next 90 days is at least 15% below the last 30 days")
    kpi(c[3], "Items with a forecast", len(outlook), "check", "green",
        help="Items with enough history (about 4 months) to backtest the forecasting methods")
    if outlook.empty:
        st.info("Not enough usage history to build a seasonal outlook yet. Items with at least ~4 months of "
                "complete usage appear here; reorder points meanwhile use the simple average (d̄).")
    else:
        if len(rising):
            st.markdown(f"**{n(len(rising), 'item')}** {'is' if len(rising) == 1 else 'are'} forecast to be at least "
                        "15% busier over the next 90 days than in the last 30. Their reorder points already use the "
                        "forecast, so they are reordered earlier and in larger amounts.")
        FC_COLS = {
            "name": st.column_config.TextColumn("Item", width="medium"), "ved": "VED", "method": "Method",
            "last_30_days": st.column_config.NumberColumn("Last 30 days (units/day)", format="%.1f",
                                                          help="Average units used per day over the last 30 days"),
            "next_30_days": st.column_config.NumberColumn("Next 30 days (units/day)", format="%.1f",
                                                          help="Forecast average units per day over the next 30 days"),
            "next_90_days": st.column_config.NumberColumn("Next 90 days (units/day)", format="%.1f",
                                                          help="Forecast average units per day over the next 90 days"),
            "change_pct": st.column_config.NumberColumn("Change", format="%+.1f%%",
                                                        help="Next 90 days compared with the last 30 days"),
            "peak_month": st.column_config.DateColumn("Peak month", format="MMM YYYY"),
            "peak_rate": st.column_config.NumberColumn("Peak (units/day)", format="%.1f"),
        }
        section("Biggest increases", "Which items need attention first?", "trend", "violet")
        with st.container(border=True, key="toolbar_forecast"):
            g1, g2, g3 = st.columns([1.2, 1.4, 1.4])
            vital_only = g1.segmented_control("Items", ["All", "Vital only"], default="All", required=True,
                                              key="fc_vital")
            methods = g2.multiselect("Forecasting method", sorted(outlook["method"].unique()), key="fc_methods",
                                     placeholder="All methods")
            fc_sort = g3.selectbox("Sort by", ["Largest increase", "Largest decrease", "Busiest next 90 days"],
                                   key="fc_sort")
        ov = outlook.assign(change_pct=outlook["change_90"] * 100, ved=outlook["ved"])
        if vital_only == "Vital only":
            ov = ov[ov["ved"] == "V"]
        if methods:
            ov = ov[ov["method"].isin(methods)]
        sort_col, sort_up = {"Largest increase": ("change_90", False), "Largest decrease": ("change_90", True),
                             "Busiest next 90 days": ("next_90_days", False)}[fc_sort]
        ov = ov.sort_values(sort_col, ascending=sort_up)
        show_cols = ["name", "ved", "method", "last_30_days", "next_90_days", "change_pct", "peak_month"]
        if ov.empty:
            st.info("No items match these filters.")
        else:
            st.caption(f"Top {min(10, len(ov))} of {n(len(ov), 'item')}. Units are units per day, averaged over "
                       "the period.")
            st.dataframe(ov.head(10)[show_cols], hide_index=True, width="stretch", column_config=FC_COLS)
            with st.expander(f"All {n(len(ov), 'item')} in this view", icon=":material/table:"):
                st.dataframe(ov[["name", "ved", "method", "last_30_days", "next_30_days", "next_90_days",
                                 "change_pct", "peak_month", "peak_rate"]], hide_index=True, width="stretch",
                             column_config=FC_COLS)
                st.download_button("Download as CSV", ov.drop(columns=["change_pct"]).to_csv(index=False),
                                   "medstock_forecast.csv", "text/csv", icon=":material/download:", key="fc_csv")

    section("One item in detail", "Monthly history, the backtest and the next 12 months", "box", "blue")
    if not forecasts:
        st.info("No forecasts to show yet. The app needs at least 4 months of complete usage history for an "
                "item to run the backtest; reorder points still work on the simple average in the meantime.")
    else:
        fc_item = st.selectbox("Item", list(forecasts), format_func=item_labels.get, key="fc_item")
        f = forecasts[fc_item]
        hist = f["history"]
        fig = go.Figure()
        fig.add_scatter(x=hist.index, y=hist, name="Actual", mode="lines+markers", line=dict(color=ui.COLORS["navy"]))
        fig.add_scatter(x=hist.index, y=f["fitted"], name=f"{f['method']}: one-step forecast",
                        line=dict(dash="dot", color=ui.COLORS["amber"]))
        fig.add_scatter(x=f["future"].index, y=f["future"], name="Forecast (next 12 months)",
                        mode="lines+markers", line=dict(color=ui.COLORS["violet"], width=3))
        bt0 = hist.index[max(0, len(hist) - 12)]
        fig.add_vrect(x0=bt0, x1=hist.index[-1], fillcolor=ui.COLORS["blue"], opacity=0.07, line_width=0,
                      annotation_text="backtest period", annotation_position="top left")
        fig.update_layout(title=f"{item_labels[fc_item]}: average daily usage per month",
                          yaxis_title="Units per day", height=420, legend=dict(orientation="h", y=-0.15),
                          yaxis_rangemode="tozero")
        st.plotly_chart(fig, width="stretch")
        nxt = f["future"].iloc[:3]
        st.caption(f"Chart summary: actual use averaged {ui.fmt_num(hist.iloc[-3:].mean())} units/day over the last "
                   f"3 months; the {f['method']} forecast is {ui.fmt_num(nxt.mean())} units/day for the next 3 "
                   f"months, peaking at {ui.fmt_num(f['future'].iloc[:12].max())} in "
                   f"{pd.Timestamp(f['future'].iloc[:12].idxmax()):%B %Y}.")

        st.markdown("**Backtest accuracy, last 12 months** (error e = F − D, slide 270)")
        scores = f["scores"].reset_index()
        scores["chosen"] = scores["method"] == f["method"]
        st.dataframe(scores[["chosen", "method", "MAD", "MSE", "MAPE", "bias"]], hide_index=True, width="stretch",
                     column_config={
                         "chosen": st.column_config.CheckboxColumn("Used"), "method": "Method",
                         "MAD": st.column_config.NumberColumn(format="%.2f", help="Mean absolute deviation, units/day"),
                         "MSE": st.column_config.NumberColumn(format="%.2f"),
                         "MAPE": st.column_config.NumberColumn(format="percent"),
                         "bias": st.column_config.NumberColumn("Bias", format="%+.2f",
                                                               help="Average error. Above 0 means we over-forecast."),
                     })

    with st.expander("How forecasting works", icon=":material/school:"):
        st.markdown(
            "Each item's history is turned into a **monthly series of average daily usage**. MedStock runs the "
            "four methods from the course (slides 276-306) and **backtests** them: for each of the last 12 months "
            "it makes a one-step-ahead forecast using only the data available at the time, then compares it with "
            "what really happened. **Auto** uses the method with the lowest **MAD** for each item.")
        if forecasts:
            mad = f["scores"].loc[f["method"], "MAD"]
            st.markdown(f"""
**From forecast error to safety stock** ({item_labels[fc_item]})
- MAD of {f['method']} = **{mad:.2f}** units/day (monthly averages)
- σ of a month's average ≈ 1.25 × MAD = **{1.25 * mad:.2f}**
- One day's σd = that × √30.4 = **{f['sigma_daily']:.1f}**

This σd goes into SS = z·√(L̄σd² + d̄²σL²). Safety stock protects against what the forecast **cannot**
predict. Predictable swings like flu season are handled by the forecast itself.
""")
        if len(outlook):
            st.caption("Methods chosen by Auto: " + ", ".join(
                f"{m} × {c}" for m, c in outlook["method"].value_counts().items()))

# ---------------------------------------------------------------------------
# Expiry page: what is expiring, and what will we fail to use in time?
# ---------------------------------------------------------------------------
LOT_COLUMNS = {
    "name": st.column_config.TextColumn("Item", width="medium"), "lot_no": "Lot", "ved": "VED",
    "expiry_date": st.column_config.DateColumn("Expires", format="MMM D, YYYY"),
    "when": st.column_config.TextColumn("Expiry status", help="Days until expiry, in words"),
    "days_left": st.column_config.NumberColumn("Days left", format="%d"),
    "qty": st.column_config.NumberColumn("Qty", format="%d"),
    "projected_use": st.column_config.NumberColumn("Will be used", format="%.0f"),
    "projected_waste": st.column_config.NumberColumn("Will expire unused", format="%.0f"),
    "value": st.column_config.NumberColumn("Value", format="$%,.2f"),
    "waste_value": st.column_config.NumberColumn("Projected waste", format="$%,.2f"),
}


def with_expiry_text(df):
    """Adds 'when' (Expired 9 days ago / Expires in 12 days) next to the numeric days_left."""
    return df.assign(when=df["days_left"].map(ui.expiry_phrase))


if PAGE == "Expiry":
    page_header("Expiry management", "What has expired, what will expire before it is used, and what to do about it.")
    expired = lot_risk[lot_risk["days_left"] <= 0]
    at_risk = lot_risk[(lot_risk["days_left"] > 0) & (lot_risk["projected_waste"] > 0.5)]
    c = st.columns(4)
    kpi(c[0], "Expired on shelf", ui.fmt_money(expired["value"].sum()), "trash", "red",
        delta=n(len(expired), "lot"), delta_color="off", delta_arrow="off")
    kpi(c[1], "Expiring in 30 days or less",
        ui.fmt_money(lot_risk.loc[(lot_risk["days_left"] > 0) & (lot_risk["days_left"] <= 30), "value"].sum()),
        "expiry", "amber")
    kpi(c[2], "Expiring in 31-90 days",
        ui.fmt_money(lot_risk.loc[(lot_risk["days_left"] > 30) & (lot_risk["days_left"] <= 90), "value"].sum()),
        "calendar", "blue")
    kpi(c[3], "Projected waste", ui.fmt_money(at_risk["waste_value"].sum()), "alert", "violet",
        delta=n(len(at_risk), "lot"), delta_color="off", delta_arrow="off",
        help="Lots not yet expired that, at the forecast rate of use (earliest-expiry first), will expire before "
             "they are used. This is the overage cost Co of the newsvendor trade-off (slides 221-224).")

    section("1. Expired: remove from the shelf now", "MedStock never issues expired stock, but it should be "
            "removed and written off", "trash", "red")
    if expired.empty:
        st.success("No expired stock.", icon=":material/check_circle:")
    else:
        ex = with_expiry_text(expired.sort_values("expiry_date"))
        ev = st.dataframe(ex[["name", "lot_no", "expiry_date", "when", "qty", "value"]], hide_index=True,
                          width="stretch", column_config=LOT_COLUMNS, key="exp_table", on_select="rerun",
                          selection_mode="single-row")
        sel = ev.selection.rows if ev and hasattr(ev, "selection") else []
        b1, b2 = st.columns([1, 1])
        if sel:
            lot_row = ex.iloc[sel[0]]
            if b1.button(f"Write off lot {lot_row['lot_no']} ({ui.fmt_money(lot_row['value'], cents=True)})",
                         icon=":material/delete:", key="wo_one_expired", width="stretch"):
                ask("write_off_lot", lot_id=int(lot_row["lot_id"]), qty=int(lot_row["qty"]), reason="Expired",
                    date=TODAY, note="Expiry page")
        else:
            b1.caption(":material/touch_app: Select a row to write off one lot.")
        if b2.button(f"Write off all {len(expired)} expired lots (${expired['value'].sum():,.2f})",
                     icon=":material/delete_sweep:", key="wo_all_expired", width="stretch"):
            ask("write_off_expired", lot_ids=sorted(expired_lot_rows()["lot_id"].tolist()))

    section("2. At risk: will expire before it is used", "Projected with the forecast rate of use, earliest "
            "expiry first", "expiry", "amber")
    if at_risk.empty:
        st.success("At current usage rates every lot will be used before it expires.", icon=":material/check_circle:")
    else:
        with st.container(border=True, key="toolbar_expiry"):
            e1, e2 = st.columns(2)
            vital_only = e1.segmented_control("Items", ["All", "Vital only"], default="All", required=True,
                                              key="exp_vital")
            exp_sort = e2.selectbox("Sort by", ["Highest projected waste", "Soonest expiry"], key="exp_sort")
        ar = at_risk[at_risk["ved"] == "V"] if vital_only == "Vital only" else at_risk
        ar = ar.sort_values("waste_value", ascending=False) if exp_sort.startswith("Highest") \
            else ar.sort_values("expiry_date")
        if ar.empty:
            st.caption("No Vital items are at risk of expiring unused.")
        else:
            st.dataframe(with_expiry_text(ar)[["name", "ved", "lot_no", "expiry_date", "when", "qty", "projected_use",
                                               "projected_waste", "waste_value"]],
                         hide_index=True, width="stretch", column_config=LOT_COLUMNS)
        with st.expander("Recommended actions", icon=":material/lightbulb:"):
            st.markdown(
                "- **Transfer** the short-dated lot to the department that uses the most of it.\n"
                "- **Return or exchange** it with the vendor. Many accept returns 60 to 90 days before expiry.\n"
                "- **Pause reordering** the item until the short-dated lot is used up.\n"
                "- **Order smaller quantities** next time. MedStock already limits an order to what can be used in "
                "80% of the shelf life.")

    section("All lots by expiry", "Every lot on the shelf, soonest first", "list", "blue")
    band = st.multiselect("Show", ["Expired", "≤ 30 days", "31-90 days", "> 90 days"],
                          default=["Expired", "≤ 30 days", "31-90 days"], key="exp_band")
    show = with_expiry_text(lot_risk[lot_risk["expiry_band"].isin(band)].sort_values("expiry_date"))
    st.dataframe(show[["name", "lot_no", "expiry_date", "when", "qty", "value", "projected_waste"]],
                 hide_index=True, width="stretch", column_config=LOT_COLUMNS)

# ---------------------------------------------------------------------------
# History page: the ledger explains every change in stock
# ---------------------------------------------------------------------------
if PAGE == "History":
    page_header("Transaction history", "Every change in stock, with the reason. Filter it, export it, or trace a lot.")
    log = db.ledger(conn)
    acc, n_counts = db.record_accuracy(conn)
    c = st.columns(3)
    kpi(c[0], "Movements recorded", f"{len(log):,}", "history", "green")
    kpi(c[1], "Cycle counts", f"{n_counts:,}", "check", "blue")
    kpi(c[2], "Record accuracy", ui.fmt_pct(acc, 0), "gauge", "violet",
        missing=None if acc is not None else "Available after the first cycle count (Stock movements > Cycle count).",
        help="Share of cycle counts where the system quantity matched the shelf. Good practice: 97% or more.")
    if log.empty:
        empty_state("history", "No movements yet",
                    "Issues, receipts, write-offs, counts and recalls appear here once they are recorded in the app "
                    "or by the simulation clock.",
                    [("Record stock movement", ":material/swap_horiz:", open_page, ("Stock movements",))])
    else:
        lots_by_txn = pd.read_sql("SELECT tl.txn_id, l.lot_no FROM transaction_lots tl JOIN lots l USING (lot_id)", conn)
        lot_txt = lots_by_txn.groupby("txn_id")["lot_no"].agg(lambda x: ", ".join(dict.fromkeys(x)))
        log = log.assign(lots=log["txn_id"].map(lot_txt).fillna(""),
                         vendor=log["item_id"].map(plan.set_index("item_id")["supplier"]),
                         date=pd.to_datetime(log["date"]).dt.date)
        with st.container(border=True, key="toolbar_history"):
            f1, f2, f3 = st.columns(3)
            lo, hi = log["date"].min(), log["date"].max()
            dates = f1.date_input("Dates", value=(lo, hi), min_value=lo, max_value=hi, key="hist_dates",
                                  format="MM/DD/YYYY")
            item_opts = sorted(log["item_id"].unique())
            if st.session_state.get("hist_items"):          # e.g. "View history" for an item with no movements yet
                st.session_state["hist_items"] = [i for i in st.session_state["hist_items"] if i in item_opts]
            chosen = f2.multiselect("Item", item_opts, format_func=item_labels.get,
                                    key="hist_items", placeholder="All items")
            types = f3.multiselect("Movement type", sorted(log["type"].unique()), key="hist_types",
                                   placeholder="All types")
            f4, f5, f6 = st.columns(3)
            wards = f4.multiselect("Department", db.WARDS, key="hist_wards", placeholder="All departments",
                                   help="Issues to a ward record the department as the reference")
            vendors = f5.multiselect("Vendor", list(pu.VENDORS), key="hist_vendors", placeholder="All vendors",
                                     help="The item's usual vendor")
            lot_q = f6.text_input("Lot number", key="hist_lot", placeholder="e.g. L81739").strip()
        view = log
        if isinstance(dates, (tuple, list)) and len(dates) == 2:
            view = view[(view["date"] >= dates[0]) & (view["date"] <= dates[1])]
        if chosen:
            view = view[view["item_id"].isin(chosen)]
        if types:
            view = view[view["type"].isin(types)]
        if wards:
            view = view[view["reference"].isin(wards)]
        if vendors:
            view = view[view["vendor"].isin(vendors)]
        if lot_q:
            view = view[view["lots"].str.contains(lot_q, case=False, regex=False)]
        st.caption(f"Showing {view.shape[0]:,} of {len(log):,} movements, newest first.")
        st.dataframe(view[["date", "name", "type", "qty", "balance_after", "reference", "lots", "vendor", "note",
                           "txn_id"]], hide_index=True, width="stretch", column_config={
            "date": st.column_config.DateColumn("Date", format="MMM D, YYYY"), "name": "Item", "type": "Movement",
            "qty": st.column_config.NumberColumn("Quantity", format="%+d", help="Change in on-hand stock"),
            "balance_after": st.column_config.NumberColumn("On hand after", format="%d"),
            "reference": "Reference / department", "lots": "Lots", "vendor": "Vendor", "note": "Note", "txn_id": "#"})
        st.download_button(f"Download {view.shape[0]:,} movements as CSV", view.to_csv(index=False),
                           "medstock_transactions.csv", "text/csv", icon=":material/download:", key="hist_csv")

    section("Lot trace", "Where did every unit of one lot go? Used for recalls.", "search", "blue")
    with st.container(border=True, key="card_lot_trace"):
        lot_no = st.text_input("Lot number to trace", placeholder="e.g. L81739", key="trace_lot").strip()
        if lot_no:
            trace = db.lot_trace(conn, lot_no)
            if trace.empty:
                st.info(f"No movements recorded for lot {lot_no} yet (or it does not exist).")
            else:
                st.markdown(f"**{trace['name'].iloc[0]}**, lot {lot_no}, expires {ui.fmt_date(trace['expiry_date'].iloc[0])}. "
                            "Every movement in order:")
                st.dataframe(trace[["date", "type", "qty", "ward_or_reference"]], hide_index=True, width="stretch",
                             column_config={"date": "Date", "type": "Movement", "qty": st.column_config.NumberColumn(
                                 "Quantity", format="%+d"), "ward_or_reference": "Department / reference"})
                issued = trace[trace["type"] == "ISSUE"]
                if len(issued):
                    by_ward = issued.groupby("ward_or_reference")["qty"].sum().abs()
                    st.markdown("Issued to: " + ", ".join(f"**{w}** ({q:,})" for w, q in by_ward.items()))
        else:
            st.caption("Type a lot number from a box label, a recall notice or the movements list.")

# ---------------------------------------------------------------------------
# Item detail page: the math for one item, step by step
# ---------------------------------------------------------------------------
if PAGE == "Item detail":
    ids = list(plan["item_id"])
    if st.session_state.get("detail_item") not in ids:
        st.session_state["detail_item"] = ids[0]
    item_id = st.selectbox("Item", ids, format_func=item_labels.get, key="detail_item",
                           help="Type to search by name or ID")
    r = plan[plan["item_id"] == item_id].iloc[0]
    reorder_s, avail_s = ui.plain_status(r["status"]), ui.plain_status(r["availability_risk"])
    avail_s = "Enough stock" if avail_s == "OK" else avail_s
    st.header(r["name"])
    st.markdown(f"Reorder status {ui.badge_md(reorder_s)} · Availability {ui.badge_md(avail_s)}  \n"
                f"{r['item_id']} · {r['category']} · {r['unit']} at {ui.fmt_money(r['unit_cost'], cents=True)} · "
                f"VED {r['ved']} · ABC {r['abc']} · control category {r['control']}")
    item_lots = lot_risk[lot_risk["item_id"] == r["item_id"]].sort_values("expiry_date")
    next_exp = item_lots[item_lots["days_left"] > 0]["expiry_date"].min() if len(item_lots) else None
    if reorder_s == "OK" and avail_s != "Enough stock":
        why = (f"Reorder status counts the {ui.fmt_int(r['on_order'])} {r['unit']} already on order, so no new order "
               "is needed yet. Availability counts a delivery only on the day it is due, and the shelf is projected "
               "to run short before then. Check the open order's date, or expedite it." if r["on_order"] > 0 else
               f"Usable stock lasts about {ui.fmt_num(r['days_of_supply'])} days at the forecast rate, which is inside "
               f"the 30-day availability window, but it is still above the reorder point ({ui.fmt_int(r['rop'])}), so "
               "ordering is not due yet. The reorder point covers only the lead time plus safety stock. Expect this "
               "item to reach Order now soon; you can order early if the vendor is slow.")
        st.info(f"**Why OK and {avail_s} at the same time?** {why}", icon=":material/info:")

    TABS = ["Summary", "Stock", "Availability", "Ordering", "Expiry", "History", "Calculations"]
    tabs = st.tabs(TABS, key="detail_tab", on_change="rerun")
    tab = next((t for t, x in zip(TABS, tabs) if x.open), TABS[0])        # only the open tab is drawn
    with tabs[TABS.index(tab)]:
        if tab == "Summary":
            c = st.columns(4)
            kpi(c[0], "Usable stock", f"{ui.fmt_int(r['usable'])}", "box", "blue",
                help=f"{ui.fmt_int(r['on_hand'])} on the shelf, {ui.fmt_int(r['on_hand'] - r['usable'])} expired")
            kpi(c[1], "On order", ui.fmt_int(r["on_order"]), "truck", "green")
            kpi(c[2], "Days of supply", ui.fmt_num(r["days_of_supply"]) if np.isfinite(r["days_of_supply"]) else ui.MISSING,
                "clock", "amber", help="Usable stock ÷ forecast daily use")
            kpi(c[3], "Reorder point", ui.fmt_int(r["rop"]), "gauge", "violet",
                help="Order when usable plus on order reaches this")
            c = st.columns(4)
            kpi(c[0], "Suggested order", ui.fmt_int(r["order_qty"]), "cart", "violet",
                help="Brings usable plus on order up to the reorder point plus one order quantity")
            kpi(c[1], "Order value", ui.fmt_money(r["order_value"]), "dollar", "blue")
            kpi(c[2], "Lead time", f"{ui.fmt_num(r['L'])} days", "truck", "green",
                help=f"Average from {r['n_orders']:.0f} past orders. Vendor: {r['order_vendor']}")
            kpi(c[3], "Next expiry", ui.fmt_date(next_exp) if next_exp is not None and pd.notna(next_exp) else ui.MISSING,
                "expiry", "amber")
            st.markdown(f"**Next step** · vendor: {r['order_vendor']}" +
                        (" (backup, the usual vendor is disrupted)" if r["order_vendor"] != r["supplier"] else ""))
            todo = ("Order now: create a purchase order." if reorder_s == "Order now" else
                    "Plan an order within the week." if reorder_s == "Order soon" else
                    f"No order needed. Availability: {avail_s.lower()}.")
            st.caption(todo)
            b1, b2, b3, _ = st.columns(4)
            b1.button("Create purchase order", key="det_po", icon=":material/add_shopping_cart:", on_click=go_new_po,
                      args=(r["order_vendor"],), type="primary" if reorder_s != "OK" else "secondary", width="stretch")
            b2.button("Issue stock", key="det_issue", icon=":material/output:", on_click=go_issue, args=(r["item_id"],),
                      width="stretch")
            b3.button("View history", key="det_hist", icon=":material/history:", on_click=go_history,
                      args=(r["item_id"],), width="stretch")
        elif tab == "Stock":
            c = st.columns(3)
            kpi(c[0], "On the shelf", ui.fmt_int(r["on_hand"]), "box", "blue")
            kpi(c[1], "Expired (not usable)", ui.fmt_int(r["on_hand"] - r["usable"]), "trash", "red")
            kpi(c[2], "Inventory position", ui.fmt_int(r["position"]), "list", "violet",
                help="Usable plus on order: what the reorder status compares with the reorder point")
            st.markdown("**Lots on the shelf** (earliest expiry first; this is the order they are issued in)")
            if item_lots.empty:
                st.caption("No stock.")
            else:
                st.dataframe(with_expiry_text(item_lots)[["lot_no", "expiry_date", "when", "qty", "value"]],
                             hide_index=True, width="stretch", column_config=LOT_COLUMNS)
        elif tab == "Availability":
            if r["availability_risk"] != "🟢 OK" or r["unknown_eta"]:
                short_txt = ""
                if not pd.isna(r["shortage_date"]):
                    short_txt = (f" First day stock runs out: **{ui.fmt_date(r['shortage_date'])}**, projected "
                                 f"**{r['projected_short_units']:,.0f} units short** over the next 90 days.")
                eta_txt = " One of the open orders has **no reliable arrival date**." if r["unknown_eta"] else ""
                st.warning(f"{ui.badge_md(avail_s)}{short_txt}{eta_txt}", icon=":material/warning:")
            else:
                st.success("Usable stock is projected to last the next 30 days.", icon=":material/check_circle:")
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
                st.caption(f"Chart summary: {ui.fmt_num(hist['qty_used'].tail(30).mean())} units per day over the last "
                           f"30 days; forecast for the lead time {ui.fmt_num(r['d'], 2)} units per day.")
        elif tab == "Ordering":
            c = st.columns(4)
            kpi(c[0], "Order quantity (Q)", ui.fmt_int(r["q"]), "cart", "violet",
                help="EOQ, limited by what can be used in 80% of the shelf life")
            kpi(c[1], "Safety stock", ui.fmt_int(r["safety_stock"]), "heart", "green")
            kpi(c[2], "Reorder point", ui.fmt_int(r["rop"]), "gauge", "blue")
            kpi(c[3], "Predicted fill rate", ui.fmt_pct(r["fill_rate"], 2), "check", "amber",
                help="Theoretical: what the service level promises (slides 205-207). The measured fill rate is on "
                     "Reports.")
            st.caption(f"Vendor: {r['supplier']} (backup: {r['backup_supplier']}). Average lead time "
                       f"{ui.fmt_num(r['L'])} days, σL {ui.fmt_num(r['sL'])} days, from {r['n_orders']:.0f} past orders.")
            col_a, col_b = st.columns(2)
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
                                      xaxis_title="Order quantity Q", yaxis_title="$ per year", yaxis_tickprefix="$")
                    st.plotly_chart(fig, width="stretch")
                    st.caption(f"Chart summary: total yearly cost is lowest at Q = {ui.fmt_num(r['eoq'])}.")
            with col_b:
                lt = deliveries[deliveries["item_id"] == r["item_id"]]
                fig = px.bar(lt, x="order_date", y="lead_time_days", title="Vendor lead time per order",
                             labels={"order_date": "Order date", "lead_time_days": "Lead time (days)"})
                fig.add_hline(y=r["L"], line_dash="dash", annotation_text="average")
                st.plotly_chart(fig, width="stretch")
                if len(lt):
                    st.caption(f"Chart summary: lead times from {lt['lead_time_days'].min():.0f} to "
                               f"{lt['lead_time_days'].max():.0f} days across {n(len(lt), 'order')}.")
        elif tab == "Expiry":
            if item_lots.empty:
                st.caption("No stock.")
            else:
                st.dataframe(with_expiry_text(item_lots)[["lot_no", "expiry_date", "when", "qty", "projected_use",
                                                          "projected_waste"]],
                             hide_index=True, width="stretch", column_config=LOT_COLUMNS)
                st.caption(f"Shelf life {r['shelf_life_days']} days. Projected with the forecast rate of use, earliest "
                           "expiry first.")
        elif tab == "History":
            item_log = db.ledger(conn)
            item_log = item_log[item_log["item_id"] == r["item_id"]].head(20)
            if item_log.empty:
                empty_state("item_hist", "No movements recorded yet",
                            "Movements appear here once stock is issued, received, written off or counted in the app.",
                            [("Record stock movement", ":material/swap_horiz:", go_issue, (r["item_id"],))])
            else:
                st.dataframe(item_log[["date", "type", "qty", "balance_after", "reference", "note"]],
                             hide_index=True, width="stretch", column_config={
                                 "date": "Date", "type": "Movement", "qty": "Quantity", "balance_after": "On hand after",
                                 "reference": "Reference", "note": "Note"})
                st.button("Open full history", key="det_hist2", icon=":material/history:", on_click=go_history,
                          args=(r["item_id"],))
        else:
            st.caption("Show calculation and course formulas: every number on this page, worked out step by step.")
            st.markdown(f"""
**Step 1: Forecast demand and measure lead time from history**
- Demand method: **{r['method']}**
- {"Forecast daily demand during the next " + f"{math.ceil(r['L'])}" + " days (the lead time)" if fc_method != SIMPLE else "Average daily usage"} d̄ = **{r['d']:.2f}** units/day
- σd = **{r['sd']:.2f}** {"(from forecast errors: 1.25 × MAD × √30.4, see Forecast)" if fc_method != SIMPLE else f"(std. dev. of daily usage, last {lookback} days)"}
- Average lead time L̄ = **{r['L']:.1f}** days, σL = **{r['sL']:.1f}** days (from {r['n_orders']:.0f} past orders)
- Annual demand D = {"sum of the next 365 days of forecast" if fc_method != SIMPLE else "d̄ × 365"} = **{r['D']:,.0f}**

**Step 2: EOQ** (slide 188)  H = i × C = {r['holding_rate']:.0%} × \\${r['unit_cost']:,.2f} = \\${r['H']:,.2f}
- EOQ = √(2DS/H) = √(2 × {r['D']:,.0f} × {r['ordering_cost']} / {r['H']:.2f}) = **{r['eoq']:,.1f}**
- {"⚠️ Capped by shelf life: we can only use " + f"{r['q']:,.0f}" + " units in 80% of the shelf life (" + str(r['shelf_life_days']) + " days)." if r['q_limited_by_expiry'] else "Shelf life is not a constraint for this item."}
- One order lasts about **{r['cycle_days']:.0f} days**

**Step 3: Safety stock and reorder point** (slides 200-201)
- Service level {r['service_level']:.1%} gives z = **{r['z']:.3f}**
- DDLT = d̄ × L̄ = {r['d']:.2f} × {r['L']:.1f} = **{r['ddlt']:.1f}**
- σ_DDLT = √(L̄σd² + d̄²σL²) = √({r['L']:.1f}×{r['sd']:.2f}² + {r['d']:.2f}²×{r['sL']:.1f}²) = **{r['sigma_ddlt']:.1f}**
- SS = z × σ_DDLT = **{r['safety_stock']:.1f}**
- ROP = DDLT + SS = **{r['rop']:.1f}**

**Step 4: Predicted fill rate** (slides 205-207): 1 − σ_DDLT·L(z)/Q = **{r['fill_rate']:.3%}**
(the measured fill rate from logged requests is on Reports)
""")

# ---------------------------------------------------------------------------
# ABC-VED page: where should management attention go?
# ---------------------------------------------------------------------------
if PAGE == "ABC-VED analysis":
    page_header("ABC-VED analysis", "Where the money is (ABC) and what patients cannot do without (VED), combined "
                                    "into one control category per item.")
    abc_sorted = plan.sort_values("annual_value", ascending=False)
    total_value = abc_sorted["annual_value"].sum()
    a_items = plan[plan["abc"] == "A"]
    c = st.columns(3)
    kpi(c[0], "A items", f"{len(a_items):,}", "dollar", "violet",
        delta=f"{ui.fmt_pct(a_items['annual_value'].sum() / total_value if total_value else None, 0)} of annual value",
        delta_color="off", delta_arrow="off", help="The few items that make up most of the yearly spending")
    kpi(c[1], "Vital items", f"{int((plan['ved'] == 'V').sum()):,}", "heart", "red",
        help="A patient can be harmed if these run out")
    kpi(c[2], "Category I items", f"{int((plan['control'] == 'I').sum()):,}", "gauge", "green",
        help="Tight control: weekly review and the highest service level")
    st.caption("**ABC** (slides 213-215) ranks items by annual dollar value. **VED** ranks them by clinical "
               "criticality: Vital, Essential, Desirable. A cheap item like epinephrine is class C but Vital, so it "
               "still gets tight control.")

    with st.container(border=True, key="toolbar_abc"):
        g1, g2, g3, g4 = st.columns([2, 1, 1, 1.3])
        q = g1.text_input("Search", key="abc_search", placeholder="Item name or ID", icon=":material/search:")
        abc_f = g2.multiselect("ABC", ["A", "B", "C"], key="abc_f", placeholder="All")
        ved_f = g3.multiselect("VED", ["V", "E", "D"], key="ved_f", placeholder="All",
                               format_func={"V": "Vital", "E": "Essential", "D": "Desirable"}.get)
        top = g4.segmented_control("Chart shows", ["Top 20", "All"], default="Top 20", required=True, key="abc_top")
    fv = abc_sorted
    if q.strip():
        fv = fv[fv["name"].str.contains(q.strip(), case=False, regex=False)
                | fv["item_id"].str.contains(q.strip(), case=False, regex=False)]
    if abc_f:
        fv = fv[fv["abc"].isin(abc_f)]
    if ved_f:
        fv = fv[fv["ved"].isin(ved_f)]
    chart = fv.head(20) if top == "Top 20" else fv
    if chart.empty:
        st.info("No items match these filters.")
    else:
        short = chart["name"].where(chart["name"].str.len() <= 22, chart["name"].str[:21] + "…")
        fig = go.Figure()
        fig.add_bar(x=chart["item_id"], y=chart["annual_value"], name="Annual value ($)",
                    marker_color=chart["abc"].map({"A": ui.COLORS["violet"], "B": ui.COLORS["blue"], "C": "#B8BCD0"}),
                    customdata=np.stack([chart["name"], chart["abc"], chart["ved"]], axis=-1),
                    hovertemplate="<b>%{customdata[0]}</b> (%{x})<br>$%{y:,.0f} per year<br>"
                                  "ABC %{customdata[1]} · VED %{customdata[2]}<extra></extra>")
        fig.add_scatter(x=chart["item_id"], y=chart["cumulative_share"] * 100, name="Cumulative % of all spending",
                        yaxis="y2", mode="lines+markers", line=dict(color=ui.COLORS["amber"]),
                        hovertemplate="%{y:.1f}% of all spending<extra></extra>")
        fig.update_layout(title=f"Pareto chart of annual consumption value ({'top 20' if top == 'Top 20' else 'all'} "
                                f"of {n(len(fv), 'item')})",
                          xaxis=dict(tickmode="array", tickvals=chart["item_id"], ticktext=short,
                                     tickangle=-40 if len(chart) <= 30 else -90,
                                     showticklabels=len(chart) <= 40),
                          yaxis=dict(title="$ per year", tickprefix="$", tickformat=",.0f"),
                          yaxis2=dict(title="Cumulative share of spending", overlaying="y", side="right",
                                      range=[0, 105], tickvals=[0, 20, 40, 60, 80, 100], ticksuffix="%",
                                      showgrid=False),
                          height=480, legend=dict(orientation="h", y=1.08), margin=dict(t=80))
        st.plotly_chart(fig, width="stretch")
        st.caption(f"Chart summary: the top item, {chart['name'].iloc[0]}, accounts for "
                   f"{ui.fmt_money(chart['annual_value'].iloc[0])} a year. A items are "
                   f"{n(len(a_items), 'item')} with {ui.fmt_pct(a_items['annual_value'].sum() / total_value, 0)} of all "
                   "spending. Hover a bar for the full item name.")

    section("Control categories", "How tightly each item is managed", "grid", "violet")
    st.markdown("Each item gets a category from its ABC class and VED class together:\n"
                "- **Category I**: anything Vital, plus A items. These must never run out.\n"
                "- **Category II**: B and C items that are Essential, and B items that are Desirable.\n"
                "- **Category III**: cheap (C) items that are only Desirable.")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Matrix (number of items)**")
        matrix = pd.crosstab(plan["abc"], plan["ved"]).reindex(index=["A", "B", "C"], columns=["V", "E", "D"],
                                                               fill_value=0)
        matrix.index.name, matrix.columns.name = "ABC class", None
        st.dataframe(matrix.rename(columns={"V": "Vital", "E": "Essential", "D": "Desirable"}), width="stretch")
    with c2:
        st.markdown("**Control policy**")
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
        "abc": "ABC class", "items": "Items",
        "value": st.column_config.NumberColumn("Annual value", format="$%,.0f"),
        "share": st.column_config.NumberColumn("Share", format="percent")})

    section("All items", f"{n(len(fv), 'item')} in this view. Select one to open it.", "list", "blue")
    tv = fv[["name", "item_id", "abc", "ved", "control", "annual_value", "cumulative_share"]].reset_index(drop=True)
    ev = st.dataframe(tv, hide_index=True, width="stretch", key="abc_table", on_select="rerun",
                      selection_mode="single-row", column_config={
                          "name": "Item", "item_id": "ID", "abc": "ABC", "ved": "VED", "control": "Category",
                          "annual_value": st.column_config.NumberColumn("Annual value", format="$%,.0f"),
                          "cumulative_share": st.column_config.NumberColumn("Cumulative share", format="percent")})
    sel = ev.selection.rows if ev and hasattr(ev, "selection") else []
    if sel:
        st.button(f"Open {tv.iloc[sel[0]]['name']} in Item detail", key="abc_go", icon=":material/info:",
                  on_click=go_item_detail, args=(tv.iloc[sel[0]]["item_id"],), type="primary")

# ---------------------------------------------------------------------------
# Calculators page: free-form what-if tools (defaults are the slide examples)
# ---------------------------------------------------------------------------
CALC_DEFAULTS = {   # the course examples; "Reset to example" puts these back
    "EOQ": {"c_D": 1000.0, "c_S": 50.0, "c_C": 40.0, "c_i": 0.25},
    "Reorder point": {"c_d": round(1000 / 12, 3), "c_sd": round(50 / 12 ** 0.5, 3), "c_L": 0.2, "c_sL": 0.05,
                      "c_sl": 0.95},
    "Newsvendor": {"c_p": 4.0, "c_c": 2.0, "c_s": 0.5, "c_mu": 80.0, "c_sigma": 20.0},
}


def calc_problems(checks):
    """checks: [(ok, message)]. Shows every failed check next to the inputs; True if all inputs are valid."""
    bad = [m for ok, m in checks if not ok]
    for m in bad:
        st.error(m, icon=":material/error:")
    return not bad


if PAGE == "Calculators":
    page_header("Calculators", "Try the course models with your own numbers. Each starts from the worked example "
                               "on the slides.")
    for vals in CALC_DEFAULTS.values():
        for k, v in vals.items():
            st.session_state.setdefault(k, v)

    def reset_example(model):
        st.session_state.update(CALC_DEFAULTS[model])

    CALCS = ["EOQ", "Reorder point", "Newsvendor"]
    ctabs = st.tabs(["EOQ", "Reorder point (uncertain demand and lead time)", "Newsvendor (single period)"],
                    key="calc_tab", on_change="rerun")
    which = next((m for m, t in zip(CALCS, ctabs) if t.open), CALCS[0])
    with ctabs[CALCS.index(which)]:
        h1, h2 = st.columns([4, 1], vertical_alignment="center")
        h2.button("Reset to example", key=f"reset_{which}", icon=":material/restart_alt:", on_click=reset_example,
                  args=(which,), width="stretch")
        if which == "EOQ":
            h1.caption("Example from slide 188.")
            c1, c2, c3, c4 = st.columns(4)
            D = c1.number_input("Annual demand D (units per year)", key="c_D", step=100.0)
            S = c2.number_input("Ordering cost S ($ per order)", key="c_S", step=5.0, format="%.2f")
            C = c3.number_input("Unit cost C ($ per unit)", key="c_C", step=1.0, format="%.2f")
            i = c4.number_input("Holding rate i (per year, 0.25 = 25%)", key="c_i", step=0.01, format="%.3f")
            if calc_problems([(D > 0, "Annual demand D must be more than 0 units."),
                              (S > 0, "Ordering cost S must be more than $0."),
                              (C > 0, "Unit cost C must be more than $0."),
                              (0 < i <= 1, "Holding rate i must be between 0 and 1 (for example 0.25 for 25% a year).")]):
                Q = im.eoq(D, S, i * C)
                cost = im.total_annual_cost(Q, D, S, i * C, C)
                r1, r2, r3 = st.columns(3)
                r1.metric("EOQ", f"{ui.fmt_num(Q)} units")
                r2.metric("Total annual cost", ui.fmt_money(cost["total"], cents=True),
                          help="Purchasing + ordering + holding cost per year")
                r3.metric("Cycle time", f"{ui.fmt_num(im.cycle_time_days(Q, D))} days")
                with st.expander("Show formula and calculation", icon=":material/functions:"):
                    st.markdown(f"""
- H = i × C = {i:g} × \\${C:,.2f} = **\\${i * C:,.2f}** per unit per year
- EOQ = √(2DS / H) = √(2 × {D:,.0f} × {S:,.2f} / {i * C:,.2f}) = **{Q:,.1f} units**
- Ordering cost = D / Q × S = **\\${cost['ordering']:,.2f}**; holding cost = Q / 2 × H = **\\${cost['holding']:,.2f}**
- Purchasing cost = D × C = **\\${cost['purchasing']:,.2f}**; total = **\\${cost['total']:,.2f}** per year
- Cycle time = Q / D × 365 = **{im.cycle_time_days(Q, D):,.1f} days**
""")
        elif which == "Reorder point":
            h1.caption("Example from slide 203, in months (d̄ = 1000/12, σd = 50/√12). Use the same time unit for "
                       "demand and lead time.")
            c1, c2, c3, c4, c5 = st.columns(5)
            d = c1.number_input("Average demand d̄ (units per period)", key="c_d", format="%.3f")
            sd = c2.number_input("Demand std. dev. σd (units per period)", key="c_sd", format="%.3f")
            L = c3.number_input("Average lead time L̄ (periods)", key="c_L", format="%.3f")
            sL = c4.number_input("Lead time std. dev. σL (periods)", key="c_sL", format="%.3f")
            sl = c5.number_input("Service level (0.95 = 95%)", key="c_sl", format="%.4f")
            if calc_problems([(d > 0, "Average demand d̄ must be more than 0."),
                              (sd >= 0, "Demand std. dev. σd cannot be negative."),
                              (L > 0, "Average lead time L̄ must be more than 0."),
                              (sL >= 0, "Lead time std. dev. σL cannot be negative."),
                              (0.5 <= sl < 1, "Service level must be at least 0.5 and below 1 (for example 0.95).")]):
                res = im.reorder_point(d, sd, L, sL, sl)
                r1, r2, r3, r4 = st.columns(4)
                r1.metric("z", f"{res['z']:.3f}")
                r2.metric("Demand during lead time", f"{ui.fmt_num(res['ddlt'], 2)} units")
                r3.metric("Safety stock", f"{ui.fmt_num(res['safety_stock'], 2)} units")
                r4.metric("Reorder point", f"{ui.fmt_num(res['rop'], 2)} units")
                with st.expander("Show formula and calculation", icon=":material/functions:"):
                    st.markdown(f"""
- Service level {sl:.2%} gives z = **{res['z']:.3f}**
- DDLT = d̄ × L̄ = {d:,.3f} × {L:g} = **{res['ddlt']:,.2f}**
- σ_DDLT = √(L̄σd² + d̄²σL²) = √({L:g} × {sd:,.3f}² + {d:,.3f}² × {sL:g}²) = **{res['sigma_ddlt']:,.2f}**
- Safety stock = z × σ_DDLT = **{res['safety_stock']:,.2f}**
- Reorder point = DDLT + safety stock = **{res['rop']:,.2f}**
""")
        else:
            h1.caption("Example: Joe's Slop House (slides 228-231). Hospital uses: platelets (5-day shelf life), "
                       "seasonal flu vaccine, or a one-time stock-up before a winter storm.")
            c1, c2, c3, c4, c5 = st.columns(5)
            price = c1.number_input("Price or value ($ per unit)", key="c_p", format="%.2f")
            cost_ = c2.number_input("Cost ($ per unit)", key="c_c", format="%.2f")
            salvage = c3.number_input("Salvage value ($ per unit left over)", key="c_s", format="%.2f")
            mu = c4.number_input("Mean demand μ (units)", key="c_mu")
            sigma = c5.number_input("Demand std. dev. σ (units)", key="c_sigma")
            if calc_problems([(price > cost_, "Price must be higher than cost, or no order is worth placing."),
                              (cost_ > salvage, "Cost must be higher than the salvage value."),
                              (mu > 0, "Mean demand μ must be more than 0 units."),
                              (sigma > 0, "Demand std. dev. σ must be more than 0 units.")]):
                nv = im.newsvendor(price, cost_, salvage, mu, sigma)
                r1, r2, r3, r4 = st.columns(4)
                r1.metric("Cu / Co", f"{ui.fmt_money(nv['cu'], True)} / {ui.fmt_money(nv['co'], True)}",
                          help="Cost of one unit short / cost of one unit left over")
                r2.metric("Optimal service level", ui.fmt_pct(nv["service_level"]))
                r3.metric("Order quantity Q", f"{ui.fmt_num(nv['q'])} units")
                r4.metric("Expected profit", ui.fmt_money(nv["expected_profit"], cents=True))
                st.caption(f"Expected shortage {ui.fmt_num(nv['expected_shortage'], 2)} units · expected sales "
                           f"{ui.fmt_num(nv['expected_sales'], 2)} units · expected leftover "
                           f"{ui.fmt_num(nv['expected_excess'], 2)} units")
                with st.expander("Show formula and calculation", icon=":material/functions:"):
                    st.markdown(f"""
- Cu = price − cost = {price:,.2f} − {cost_:,.2f} = **{nv['cu']:,.2f}**; Co = cost − salvage = {cost_:,.2f} − {salvage:,.2f} = **{nv['co']:,.2f}**
- Optimal service level = Cu / (Cu + Co) = **{nv['service_level']:.2%}**, so z = **{nv['z']:.3f}**
- Q* = μ + zσ = {mu:,.1f} + {nv['z']:.3f} × {sigma:,.1f} = **{nv['q']:,.1f} units**
""")

confirm_dialog()

# icon tiles for every KPI card drawn on this page
st.html("<style>" + ui.kpi_css(KPI_TILES) + "".join(
    f'.st-key-{k} [data-testid="stMetricValue"]{{color:#9A9EB8 !important;}}' for k in MUTED_KPIS) + "</style>")
