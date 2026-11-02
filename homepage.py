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
    ("Shortages", "High-value consumables run out exactly when they are needed most."),
    ("Expiry and overstock", "Slow-moving items sit on the shelf until they expire and get written off."),
    ("Fragmented visibility", "Requests, receipts, lots and counts live in different places, so nobody sees the full picture."),
]

_FEATURES = [
    ("FEFO lot tracking", "Stock leaves the shelf by first-expiry, first-out, and every lot stays traceable."),
    ("Demand forecasting", "Several methods are backtested against recent usage so each forecast is chosen by evidence."),
    ("Replenishment recommendations", "Reorder points and order quantities flag what to order today, this week, or later."),
    ("Simulated purchasing", "Purchase orders go to simulated suppliers, and shipments, partial deliveries and backorders return."),
    ("Recalls and vendor disruptions", "Recall a lot or take a vendor offline, then watch stock get pulled, orders get rejected, and backup vendors take over."),
    ("KPI tracking", "Fill rate, stockouts, inventory turns, days on hand, waste and vendor reliability, tracked week by week."),
    ("ABC-VED prioritization", "Annual usage value (ABC) and clinical criticality (VED) help prioritize inventory control."),
    ("Movement history and counts", "Issues, receipts, write-offs and physical counts log every change for review."),
]

_STEPS = [
    ("Demand is recorded", "Every ward issue logs what was requested, what was served, and what was left short."),
    ("The plan is built", "Forecasts, service levels and ABC-VED classes turn history into expected usage and priority."),
    ("Ordering and delivery", "Reorder logic suggests purchase orders; vendors respond with shipments and backorders."),
    ("Reality is recorded", "Receipts, counts and write-offs close the loop, so theory can be checked against what happened."),
]

_COURSE = [
    ("EOQ and total cost", "Economic order quantity, ordering vs. holding cost, sensitivity."),
    ("Safety stock and reorder point", "Uncertain demand and lead time, service level, the (Q, R) policy."),
    ("Fill rate and loss function", "Expected units short per cycle and the resulting fill rate."),
    ("ABC classification", "Ranking items by annual usage value."),
    ("Newsvendor model", "One-time purchases with overage and underage costs."),
    ("Demand forecasting", "Moving average, exponential smoothing, Holt, Winters, and error measures (MAD, MSE, MAPE)."),
]

_EXTENSIONS = [
    ("Healthcare adaptation", "VED criticality, service levels by criticality, ABC-VED matrix, shelf-life caps."),
    ("Lots and expiry", "FEFO picking, expiry-waste projection, 90-day availability risk, lot tracing."),
    ("Purchasing workflow", "Vendor POs with approval, acknowledgement, ship notice and receiving, modeled on EDI 850/855/856."),
    ("Simulation", "A clock that generates daily demand and vendor behavior to test reorder policies over weeks."),
    ("Supply risk", "Lot recalls, vendor disruptions and automatic switch to backup vendors."),
    ("Measurement", "KPIs and weekly trends, method backtesting, plus the sign-in and portfolio homepage."),
]

_STACK = ["Python", "Streamlit", "SQLite", "Pandas", "NumPy", "SciPy", "Plotly"]

_SCOPE = [
    ("Synthetic data and simulated suppliers", "Nothing here purchases from a real vendor or moves real stock."),
    ("A learning tool, not clinical software", "Decisions and numbers are illustrative, not production-ready."),
    ("Future phases are off", "AI assistance is planned, but not enabled in this demo."),
]

HERO = """<div class="medi-root">
  <p class="medi-eyebrow">Supply chain / Portfolio project</p>
  <h1>MedStock</h1>
  <p class="medi-lede">Better inventory decisions. Better prepared care.</p>
  <p>MedStock is a hands-on demo of a hospital supply room's inventory. It turns inventory
     theory into operational decisions: what to order, when, how much, and how to spot the
     items that need attention before they run out or expire.</p>
</div>"""


def _cards(items):
    return "\n".join(f'<div class="medi-card"><h3>{_esc(t)}</h3><p>{_esc(d)}</p></div>'
                     for t, d in items)


def _list_items(items):
    return "\n".join(f"<li>{_esc(t)} &mdash; {_esc(d)}</li>" for t, d in items)


def _steps(items):
    return "\n".join(f'<div class="medi-step"><h3>{_esc(t)}</h3><p>{_esc(d)}</p></div>'
                     for t, d in items)


def _chips(items):
    return "\n".join(f'<span class="medi-chip">{_esc(x)}</span>' for x in items)


def _body():
    return f"""<div class="medi-root">
  <section class="medi-section">
    <h2>The problem</h2>
    <p>Hospital supplies are managed between two failures: run out of something critical, or
       let a slow mover expire. Neither shows up in the same place as the ordering history.</p>
    <ul class="medi-scope">
{_list_items(_PROBLEMS)}
    </ul>
  </section>

  <section class="medi-section">
    <h2>What MedStock does</h2>
    <p>Eight capabilities work together so the inventory tells staff what needs attention.</p>
    <div class="medi-grid">
{_cards(_FEATURES)}
    </div>
  </section>

  <section class="medi-section">
    <h2>From demand to decision</h2>
    <p>Recorded movements feed planning models; simulated outcomes help test their assumptions.</p>
    <div class="medi-steps">
{_steps(_STEPS)}
    </div>
    <p class="medi-illustrative">Illustrative workflow used inside the demo.</p>
  </section>

  <section class="medi-section">
    <h2>Course foundation and my extensions</h2>
    <p>The core models come from the Inventory Management and Forecasting lessons of my Supply Chain
       Management course at the University of Portland. Everything that turns them into a working
       hospital system is my own research and design beyond the course.</p>
    <h3 class="medi-subhead">From the course</h3>
    <div class="medi-grid">
{_cards(_COURSE)}
    </div>
    <h3 class="medi-subhead">My research and extensions</h3>
    <div class="medi-grid">
{_cards(_EXTENSIONS)}
    </div>
  </section>

  <section class="medi-section">
    <h2>Built to make the reasoning visible</h2>
    <p>Every recommendation can be compared with what actually happened: the plan shows the
       theoretical coverage from the models, while measured fill rates and stockouts show the
       observed outcome, so the assumptions stay checkable.</p>
    <div class="medi-chips">
{_chips(_STACK)}
    </div>
  </section>

  <section class="medi-section">
    <h2>Project scope</h2>
    <ul class="medi-scope">
{_list_items(_SCOPE)}
    </ul>
    <p class="medi-note">This is a self-study portfolio project about managing hospital supply
       inventory. The data inside the demo is synthetic, and all vendor activity is simulated
       locally. Nothing is connected to a real hospital or supplier.</p>
  </section>

  <footer class="medi-footer">MedStock &mdash; hospital supply inventory demo, built with Python and
    Streamlit. Core models from a University of Portland supply chain management course; the
    extensions are independent research.</footer>
</div>"""


def render_homepage():
    st.html("<style>" + CSS + "</style>")
    st.html(HERO)
    if st.button("Explore the inventory demo", key="open_demo"):
        st.session_state["view"] = "demo" if st.session_state.get("user") else "login"
        st.rerun()
    st.caption("The demo requires sign-in; access is by invitation. All data inside it is synthetic.")
    st.html(_body())
