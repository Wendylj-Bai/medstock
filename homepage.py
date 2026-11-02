import html

import streamlit as st


def _esc(s):
    return html.escape(str(s), quote=True)


CSS = """
.medi-root{box-sizing:border-box;max-width:1160px;margin:0 auto;background:#f6f5f0;color:#16222f;
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  line-height:1.6;padding:3.2rem 5%;border-radius:20px;border:1px solid #e4e1d6;}
.medi-root *{box-sizing:border-box;}
.medi-root h1{color:#0b2a4a;font-size:clamp(2rem,4.5vw,3.1rem);line-height:1.15;letter-spacing:-.02em;margin:.6rem 0 1rem;font-weight:700;}
.medi-root h2{color:#0b2a4a;font-size:clamp(1.4rem,2.6vw,1.9rem);margin:0 0 .4rem;letter-spacing:-.01em;font-weight:700;}
.medi-root h3{color:#0b2a4a;font-size:1.05rem;margin:0 0 .4rem;font-weight:650;}
.medi-root p{color:#32445a;}
.medi-eyebrow{color:#b57b1e;font-size:.78rem;font-weight:700;letter-spacing:.16em;text-transform:uppercase;margin:0;}
.medi-lede{max-width:72ch;font-size:1.08rem;margin:0 0 1.6rem;}
.medi-section{margin:3.4rem 0 0;}
.medi-section>p{max-width:72ch;}
.medi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:1rem;margin-top:1.1rem;}
.medi-card{background:#ffffff;border:1px solid #e4e1d6;border-radius:14px;padding:1.1rem 1.2rem;}
.medi-card>p{font-size:.95rem;margin:0;}
.medi-workflow{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:.9rem;margin:1.4rem 0 .6rem;}
.medi-wcard{background:#ffffff;border:1px solid #e4e1d6;border-top:3px solid #0e7c7b;border-radius:12px;padding:.9rem 1rem;}
.medi-wcard p{font-size:.92rem;margin:0;}
.medi-illustrative{color:#8a6d2f;font-size:.8rem;font-weight:600;margin:.4rem 0 1.4rem;}
.medi-caption{color:#5b6b7d;font-size:.9rem;margin:1.2rem 0 0;}
.medi-steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(215px,1fr));gap:1rem;margin-top:1.1rem;counter-reset:step;}
.medi-step{background:#ffffff;border:1px solid #e4e1d6;border-radius:14px;padding:1.1rem 1.2rem;position:relative;}
.medi-step::before{counter-increment:step;content:counter(step) ".";position:absolute;top:.8rem;right:1rem;color:#0e7c7b;font-weight:700;font-size:1.3rem;}
.medi-step>p{font-size:.93rem;margin:0;}
.medi-chips{display:flex;flex-wrap:wrap;gap:.55rem;margin-top:1rem;}
.medi-chip{background:#dbeceb;color:#0b5c5b;border-radius:999px;padding:.35rem .9rem;font-size:.88rem;font-weight:600;}
.medi-scope{list-style:none;padding:0;margin:1.1rem 0 0;}
.medi-scope li{padding:.55rem 0 .55rem 1.4rem;position:relative;max-width:76ch;}
.medi-scope li::before{content:"";position:absolute;left:0;top:1.05rem;width:.55rem;height:.55rem;border-radius:50%;background:#b57b1e;}
.medi-note{background:#ffffff;border:1px solid #e4e1d6;border-left:4px solid #0e7c7b;border-radius:10px;padding:.9rem 1.1rem;margin:1.2rem 0 0;max-width:80ch;}
.medi-subhead{font-size:1.05rem;margin:1.6rem 0 .6rem;color:#0e7c7b;}
.medi-footer{margin:3.6rem 0 0;padding-top:1.2rem;border-top:1px solid #e4e1d6;color:#5b6b7d;font-size:.9rem;}
.st-key-open_demo{display:flex;justify-content:center;}
.st-key-open_demo button{border-radius:999px;padding:.65rem 2rem;font-weight:600;font-size:1.02rem;
  background:#0e7c7b;color:#ffffff;border:none;box-shadow:0 8px 18px rgba(14,124,123,.28);}
.st-key-open_demo button:hover{background:#0b6463;}
@media (max-width:720px){.medi-root{padding:2.2rem 6%;}
  .medi-grid,.medi-workflow,.medi-steps{grid-template-columns:1fr;}}
"""

_PROBLEMS = [
    ("Running out", "Critical items like IV fluids and insulin can't wait for a late delivery."),
    ("Expiring stock", "Items with a short shelf life get thrown away when they're ordered in bulk."),
    ("Scattered information", "Usage, deliveries, lot numbers and stock counts often live in separate places."),
]

_FEATURES = [
    ("Reorder planning", "Calculates a reorder point and order quantity for every item and flags what to order now or soon."),
    ("Demand forecasting", "Tests four forecasting methods on past usage and uses the most accurate one for each item."),
    ("Lot and expiry tracking", "Issues the earliest-expiring stock first and warns before lots expire."),
    ("Purchasing", "Groups suggested orders into one purchase order per vendor. Simulated vendors confirm, ship, run late or come up short."),
    ("Recalls and vendor outages", "Pull a recalled lot off the shelf, or take a vendor offline and watch orders move to a backup supplier."),
    ("KPIs", "Fill rate, stockouts, inventory turns, days on hand, waste and on-time delivery, week by week."),
    ("ABC-VED priorities", "Ranks items by spending (ABC) and by clinical importance (VED) to decide where attention goes."),
    ("Full history", "Every issue, receipt, write-off and stock count is logged and can be exported."),
]

_STEPS = [
    ("Wards use stock", "Requests are filled from the shelf. Anything that can't be filled is logged as a stockout."),
    ("The plan updates", "Forecasts and service levels set new reorder points for every item."),
    ("Orders go out", "Items at or below their reorder point are drafted into purchase orders for approval."),
    ("Deliveries arrive", "Received lots, counts and write-offs feed into the next day's plan."),
]

_COURSE = [
    ("EOQ and total cost", "Economic order quantity, ordering vs. holding cost, sensitivity."),
    ("Safety stock and reorder point", "Uncertain demand and lead time, service level, the (Q, R) policy."),
    ("Fill rate and loss function", "Expected units short per order cycle and the resulting fill rate."),
    ("ABC classification", "Ranking items by annual usage value."),
    ("Newsvendor model", "One-time purchases with overage and underage costs."),
    ("Demand forecasting", "Moving average, exponential smoothing, Holt, Winters, and error measures (MAD, MSE, MAPE)."),
]

_EXTENSIONS = [
    ("Healthcare setting", "VED criticality, service levels set by criticality, and order sizes limited by shelf life."),
    ("Lots and expiry", "First-expired-first-out picking, expiry waste projection, 90-day shortage risk and lot tracing."),
    ("Purchasing workflow", "Draft, approval, vendor confirmation, ship notice and receiving, modeled on the EDI 850, 855 and 856 messages hospitals use."),
    ("Simulation clock", "Generates daily demand and vendor behavior, so a reorder policy can be tested over weeks in a few seconds."),
    ("Supply risk", "Lot recalls, vendor outages and switching to a backup vendor."),
    ("Reporting", "The KPI page, weekly trends, forecast backtesting, sign-in and this homepage."),
]

_STACK = ["Python", "Streamlit", "SQLite", "Pandas", "NumPy", "SciPy", "Plotly"]

_SCOPE = [
    ("Synthetic data", "The hospital, its usage history and all four vendors are made up."),
    ("A learning project", "It isn't clinical software and hasn't been used in a real hospital."),
    ("Next phase", "AI assistance is planned but not built yet."),
]

HERO = """<div class="medi-root">
  <p class="medi-eyebrow">Supply chain portfolio project</p>
  <h1>MedStock</h1>
  <p class="medi-lede">A hospital supply room inventory planner I built to put my supply chain coursework into practice.</p>
  <p>It tracks 30 medical supplies from four fictional vendors, tells you what to order and how much,
     and lets you fast-forward time to see whether those decisions hold up.</p>
</div>"""


def _cards(items):
    return "\n".join(f'<div class="medi-card"><h3>{_esc(t)}</h3><p>{_esc(d)}</p></div>'
                     for t, d in items)


def _list_items(items):
    return "\n".join(f"<li><strong>{_esc(t)}.</strong> {_esc(d)}</li>" for t, d in items)


def _steps(items):
    return "\n".join(f'<div class="medi-step"><h3>{_esc(t)}</h3><p>{_esc(d)}</p></div>'
                     for t, d in items)


def _chips(items):
    return "\n".join(f'<span class="medi-chip">{_esc(x)}</span>' for x in items)


def _body():
    return f"""<div class="medi-root">
  <section class="medi-section">
    <h2>Why hospital inventory is hard</h2>
    <p>A supply room has to avoid two opposite mistakes. Run short on IV fluids or insulin and patient
       care suffers. Overstock slow-moving items and they expire on the shelf. On top of that, lead
       times vary by vendor and demand changes with the season.</p>
    <ul class="medi-scope">
{_list_items(_PROBLEMS)}
    </ul>
  </section>

  <section class="medi-section">
    <h2>What it does</h2>
    <div class="medi-grid">
{_cards(_FEATURES)}
    </div>
  </section>

  <section class="medi-section">
    <h2>How a simulated day works</h2>
    <div class="medi-steps">
{_steps(_STEPS)}
    </div>
  </section>

  <section class="medi-section">
    <h2>What came from class and what I added</h2>
    <p>The formulas come from the Inventory Management and Forecasting units of my Supply Chain
       Management course at the University of Portland. The hospital setting and everything built
       around the formulas is my own research.</p>
    <h3 class="medi-subhead">From the course</h3>
    <div class="medi-grid">
{_cards(_COURSE)}
    </div>
    <h3 class="medi-subhead">My additions</h3>
    <div class="medi-grid">
{_cards(_EXTENSIONS)}
    </div>
  </section>

  <section class="medi-section">
    <h2>Built with</h2>
    <p>Each screen can show the calculation behind its numbers, so you can check why an item was
       flagged instead of taking it on faith.</p>
    <div class="medi-chips">
{_chips(_STACK)}
    </div>
  </section>

  <section class="medi-section">
    <h2>Scope and limits</h2>
    <ul class="medi-scope">
{_list_items(_SCOPE)}
    </ul>
  </section>

  <footer class="medi-footer">MedStock is a supply chain portfolio project built with Python and Streamlit.</footer>
</div>"""


def render_homepage():
    st.html("<style>" + CSS + "</style>")
    st.html(HERO)
    if st.button("Explore the inventory demo", key="open_demo"):
        st.session_state["view"] = "demo" if st.session_state.get("user") else "login"
        st.rerun()
    st.caption("The demo is invite-only and needs a sign-in. All data in it is made up.")
    st.html(_body())
