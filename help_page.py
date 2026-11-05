"""
help_page.py: the in-app Help page.

Short, task-focused help in tabs. The complete manual (docs/USER_GUIDE.md) is still available at the
bottom. Status wording here must match ui.STATUS and the thresholds in planning.py.
"""

from pathlib import Path

import streamlit as st

import ui

GUIDE = Path(__file__).parent / "docs" / "USER_GUIDE.md"


def _status_table(rows):
    st.markdown("| Status | What it means | What to do |\n|---|---|---|\n" + "\n".join(
        f"| {ui.badge_md(label)} | {meaning} | {todo} |" for label, meaning, todo in rows))


def render(open_page):
    """Draw the Help page. open_page(title) is the menu callback, used by the shortcut buttons."""
    st.header("Help")
    st.caption("How to use MedStock, what the statuses mean, and how to restart the demo. MedStock is a "
               "learning project with fictional data; it is not clinical software.")

    tabs = st.tabs(["Getting started", "Statuses", "Daily workflows", "Simulation", "Formulas",
                    "About the data", "Reset the demo"])

    with tabs[0]:
        st.subheader("Getting started")
        st.markdown(
            "1. **Dashboard** shows what needs attention today: items to order, Vital items at risk, "
            "fill rate and inventory value, plus the most urgent items.\n"
            "2. **Inventory** lists all items. Search, use a quick view such as *Order now*, and select a row "
            "to open its details.\n"
            "3. **Purchasing** holds purchase orders. Drafts wait for you to review and approve them; nothing "
            "is sent to a vendor without your approval.\n"
            "4. **Planning settings** (sidebar) holds the simulation clock and the policy settings.\n"
            "5. Everything else (Stock movements, Expiry, Item detail, History, ABC-VED, Calculators) is under "
            "**More** in the sidebar.")
        st.markdown("**Good to know**")
        st.markdown(
            "- The address bar shows the open page (for example `?page=help`). Reloading the browser signs you "
            "out, because sign-in lasts for one browser session. After you sign in again, you return to the "
            "same page.\n"
            "- Actions that cannot be undone, and every simulated event, ask you to confirm first. The "
            "confirmation lists exactly what will change.")
        c1, c2, c3 = st.columns(3)
        c1.button("Open Dashboard", key="help_go_dash", on_click=open_page, args=("Dashboard",),
                  icon=":material/dashboard:", width="stretch")
        c2.button("Open Inventory", key="help_go_inv", on_click=open_page, args=("Inventory",),
                  icon=":material/list:", width="stretch")
        c3.button("Open Purchasing", key="help_go_buy", on_click=open_page, args=("Purchasing",),
                  icon=":material/shopping_cart:", width="stretch")

    with tabs[1]:
        st.subheader("Reorder status: is it time to place an order?")
        st.caption("Based on the inventory position: usable stock plus stock already on order.")
        _status_table([
            ("Order now", "Usable plus on order is at or below the reorder point.", "Order today."),
            ("Order soon", "It will reach the reorder point within about 7 days at the current rate of use.",
             "Plan the order."),
            ("OK", "Enough stock and orders to cover the reorder point.", "Nothing."),
        ])
        st.subheader("Availability: will usable stock last?")
        st.caption("Projected day by day over the next 90 days, using stock earliest-expiry first and counting "
                   "deliveries only on the day they are due.")
        _status_table([
            ("No usable stock", "A Vital item has nothing usable on the shelf.", "Act now: expedite or borrow."),
            ("Shortage risk", "Stock runs out within 7 days.", "Expedite, or check the open order's date."),
            ("Shortage watch", "Stock runs out within 8 to 30 days.", "Make sure an order arrives in time."),
            ("Enough stock", "No shortage projected in the next 30 days.", "Nothing."),
        ])
        st.subheader("Why an item can be OK and at risk at the same time")
        st.markdown(
            "Reorder status counts stock that is **on order**. Availability only counts a delivery on the day "
            "it is **due**. If an order is already placed but arrives after the shelf runs empty, the item is "
            f"{ui.badge_md('OK')} for ordering and {ui.badge_md('Shortage watch')} or "
            f"{ui.badge_md('Shortage risk')} for availability. The Inventory page shows the more urgent of the "
            "two as the item's **Status**.")
        st.subheader("Other labels")
        st.markdown(
            "- **VED**: clinical importance. **V**ital (harm if it runs out), **E**ssential, **D**esirable.\n"
            "- **ABC**: share of annual spending. **A** items are the few that make up about 70% of spending.\n"
            "- **Usable**: on hand minus expired lots. Expired stock is never issued.\n"
            f"- {ui.badge_md('Expired')} and {ui.badge_md('Expiring soon')} on the Expiry page; "
            f"{ui.badge_md('Late')} on purchase orders past the vendor's promised date.")

    with tabs[2]:
        st.subheader("Dashboard and Inventory")
        st.markdown(
            "1. On the **Dashboard**, read the four cards and the urgent items table.\n"
            "2. Press **Prepare draft purchase orders** to create one draft per vendor. This only creates drafts.\n"
            "3. Use **Inventory** to search for an item, filter by status, and export the full list as CSV.")
        st.subheader("Purchasing")
        st.markdown(
            "1. Open **Purchasing > Purchase orders**. Drafts are listed first.\n"
            "2. Check the quantities, change them if needed, and press **Save changes**.\n"
            "3. Press **Review and approve**. A summary of lines, total and vendor opens; press **Approve and "
            "send** to send it.\n"
            "4. The simulated vendor acknowledges, ships and delivers as the clock moves. Orders that arrive "
            "wait at the dock until you receive them.")
        st.subheader("Stock movements")
        st.markdown(
            "- **Issue to ward**: stock leaves the storeroom, picked earliest-expiry first. Anything requested "
            "but not available is logged as a stockout and still counts as demand.\n"
            "- **Receive delivery**: check the boxes against the vendor's ship notice (quantity, lot, expiry).\n"
            "- **Write-off**: expired, damaged, recalled or lost stock. A reason is required, and you confirm "
            "before it is saved. A write-off is not demand.\n"
            "- **Cycle count**: count a lot without seeing the system quantity (a blind count). The result "
            "shows what the system expected and corrects any difference.")

    with tabs[3]:
        st.subheader("The simulation clock")
        st.markdown(
            "Open **Planning settings** in the sidebar.\n\n"
            "- **+1 day**, **+7 days** and **Next delivery** move the hospital forward. Each simulated day the "
            "wards use stock, vendors respond to orders, deliveries arrive and reordering runs as you set it.\n"
            "- **Automatic reordering**: off, create drafts for you to approve, or send orders automatically.\n"
            "- **Random events**: when on, the simulation can start a recall or a vendor disruption on its own.\n"
            "- **Service levels** by criticality and the **forecast method** change how reorder points are "
            "calculated.\n\n"
            "On the **Alerts** page you can also start a recall or a vendor disruption yourself, or simulate a "
            "random one. Each is a fictional event, and you confirm it before anything changes.")

    with tabs[4]:
        st.subheader("Formula glossary")
        st.caption("The formulas come from the course (slide numbers refer to the course deck). Item detail "
                   "shows each one worked out for a single item.")
        st.markdown(
            "| Term | Formula | Meaning |\n|---|---|---|\n"
            "| EOQ | √(2DS / H) | Order size with the lowest yearly ordering plus holding cost (slide 188) |\n"
            "| H | i × C | Yearly holding cost per unit: holding rate times unit cost |\n"
            "| DDLT | d̄ × L̄ | Expected demand during the lead time |\n"
            "| σ_DDLT | √(L̄σd² + d̄²σL²) | Uncertainty of demand during the lead time (slides 200-201) |\n"
            "| Safety stock | z × σ_DDLT | Cushion for busy days and late deliveries |\n"
            "| Reorder point | DDLT + safety stock | Order when usable plus on order reaches this |\n"
            "| Fill rate | 1 − σ_DDLT × L(z) / Q | Share of demand served from the shelf (slides 205-207) |\n"
            "| Newsvendor | P(D ≤ Q*) = Cu / (Cu + Co) | One-time order for short-lived stock (slides 217-231) |\n"
            "| MAD | average of the absolute forecast errors | How far off a forecast method is |")

    with tabs[5]:
        st.subheader("About the data")
        st.markdown(
            "MedStock is a supply chain portfolio and learning project. The hospital, its 150 items, the "
            "usage history and the four vendors are **fictional**, and all amounts are in US dollars. Vendor "
            "responses, recalls and disruptions are **simulated**.\n\n"
            "The app has not been validated for clinical use or real purchasing decisions. Treat its numbers as "
            "a demonstration of the methods, not as advice.")

    with tabs[6]:
        st.subheader("Reset or restart the demo")
        st.markdown(
            "- **Start over with fresh sample data**: open **Planning settings** in the sidebar, tick "
            "**I want to erase everything**, then press **Reset to fresh sample data**. This erases every "
            "simulated movement, order and event, and sets the clock back to the real date.\n"
            "- **Undo one action**: MedStock keeps a permanent ledger, so single actions are not undone. Correct "
            "a wrong quantity with a cycle count, or end a vendor disruption early on the Alerts page.\n"
            "- **On the live demo**, all visitors share one database, and it resets to sample data when the "
            "server restarts.")

    with st.expander("Full user guide", icon=":material/menu_book:"):
        if GUIDE.exists():
            st.markdown(GUIDE.read_text(encoding="utf-8"))
        else:
            st.info("The user guide (docs/USER_GUIDE.md) was not found.")
