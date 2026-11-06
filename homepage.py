"""
homepage.py: the public portfolio page (no database access).

Layout follows the approved design mockup: top strip, navigation, hero with photo, feature row,
"What it does" photo cards, stats band, how a day works, course vs. my work, scope, roadmap,
call to action and footer. Photos live in static/home/ and are served by Streamlit's static file
serving (see .streamlit/config.toml). Icons are small inline SVGs (Lucide style) turned into
data URIs, because st.html strips raw <svg> tags.
"""

import html
from pathlib import Path

import streamlit as st

import ui

GITHUB = "https://github.com/Wendylj-Bai/medstock"
IMG = "app/static/home/"
DEMO_LINK = "?open=demo"          # app.py turns this into "show the sign-in / demo"


def _esc(s):
    return html.escape(str(s), quote=True)


_data_uri = ui.data_uri


LOGO = _data_uri((Path(__file__).parent / "assets" / "logo.svg").read_text(encoding="utf-8"))

def icon(name, color="#6D4AFF", size=22, cls="ms-ico"):
    return ui.img(name, color, size, cls)


# ---------------------------------------------------------------------------
# Content (plain, first person, no dashes; see AGENTS.md writing rules)
# ---------------------------------------------------------------------------

_HIGHLIGHTS = [
    ("cart", "#6D4AFF", "#EEEAFF", "Reorder planning", "When to order each item and how much."),
    ("trend", "#16A394", "#E3F6F3", "Forecasting", "Four methods tested, the most accurate one used per item."),
    ("alert", "#E5534B", "#FDECEB", "Recalls and outages", "Pull recalled lots and switch to backup vendors."),
    ("pie", "#E59A1A", "#FDF3E1", "KPIs", "Fill rate, turns, waste and on-time delivery."),
]

_TOOLS = [
    ("clipboard", "Dashboard", "What to order today, what is running low and what needs a look."),
    ("truck", "Purchasing", "One order per vendor. Simulated vendors confirm, ship, run late or come up short."),
    ("bottle", "Expiry", "Earliest-expiring stock goes out first, with a warning before lots expire."),
    ("heart", "ABC-VED priorities", "Ranks items by spending and by clinical importance, so Vital items get the most protection."),
    ("calculator", "Calculators", "EOQ, safety stock and the newsvendor model, with the math shown."),
]

def _item_count():
    """Counted from the sample catalog, so the homepage never goes stale (no database access here)."""
    f = Path(__file__).parent / "data" / "items.csv"
    return max(sum(1 for _ in f.open(encoding="utf-8")) - 1, 0) if f.exists() else 150


ITEM_COUNT = _item_count()
AI_LOOKUPS = 7   # Ask MedStock's read-only tools; test_homepage checks this matches assistant.TOOLS

_STATS = [("box", str(ITEM_COUNT), "Medical supplies"), ("users", "4", "Fictional vendors"),
          ("wrench", str(len(ui.PAGES)), "Planning tools"), ("search", str(AI_LOOKUPS), "Read-only AI lookups")]

_PROBLEMS = [
    ("Running out", "Critical items like IV fluids and insulin can't wait for a late delivery."),
    ("Expiring stock", "Items with a short shelf life get thrown away when they're ordered in bulk."),
    ("Scattered information", "Usage, deliveries, lot numbers and stock counts often live in separate places."),
]

_STEPS = [
    ("Wards use stock", "Requests are filled from the shelf. Anything that can't be filled is logged as a stockout."),
    ("The plan updates", "Forecasts and service levels set new reorder points for every item."),
    ("Orders go out", "Items at or below their reorder point are drafted into purchase orders for approval."),
    ("Deliveries arrive", "Received lots, counts and write-offs feed into the next day's plan."),
]

_COURSE_SHORT = [("cap", "EOQ, safety stock and reorder points from the course"),
                 ("trend", "Forecasting methods and error measures from the course"),
                 ("flask", "Lots, recalls and vendors from my own research"),
                 ("clock", "The simulation clock is my own design")]

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
    ("Lots and expiry", "First-expired-first-out picking, expiry waste projection, 90-day shortage risk, lot tracing, and deliveries that arrive as several lots."),
    ("Purchasing workflow", "Draft, approval, vendor confirmation, ship notice and receiving, modeled on the EDI 850, 855 and 856 messages hospitals use."),
    ("Simulation clock", "Generates daily demand and vendor behavior, so a reorder policy can be tested over weeks in a few seconds."),
    ("Supply risk", "Lot recalls, vendor outages and switching to a backup vendor."),
    ("Reporting", "The KPI page, weekly trends, forecast backtesting, sign-in and this homepage."),
    ("Agentic AI foundation", "Ask MedStock is a tool-using, read-only supply-chain assistant. It investigates questions with seven governed lookups, checks every figure against the evidence and logs every answer."),
]

_STACK = ["Python", "Streamlit", "SQLite", "Pandas", "NumPy", "SciPy", "Plotly", "External AI model"]

# Ask MedStock on the homepage: what you can ask, and what it does and does not do
ASK_QUESTIONS = [
    "Which Vital items are most at risk of running out?",
    "What should I order today, and why?",
    "Are any vendors disrupted or late right now?",
    "How are we doing on fill rate and waste over the last 90 days?",
]
_ASK_FACTS = [
    ("search", "Looks it up, then answers.", "It checks the reorder plan, item details, KPIs, supply risks, purchase "
     "orders and lot history, often several of them, before it answers."),
    ("check", "Every figure is checked.", "Numbers in an answer are compared with what the lookups returned, and "
     "every answer is logged with the lookups behind it."),
    ("alert", "Read-only.", "It explains and advises. It cannot place orders, change stock or resolve alerts; it "
     "tells you which page does that."),
]

_AGENTS = [
    ("Ask MedStock", "Built", "Answers questions about stock, purchasing and supply risk",
     "Selects from seven read-only tools, checks figures against returned evidence and records every run"),
    ("Inventory Impact Agent", "Coming later",
     "Determines which items, lots and services are affected by a shortage, recall or vendor outage",
     "Reviews usable stock, lots, expiry, Vital status, demand, open orders and projected days of supply"),
    ("Sourcing Agent", "Coming later", "Finds practical replacement supply options",
     "Reviews vendors, active disruptions, open purchase orders, lead times, backup sources and estimated cost"),
    ("Recovery Planner Agent", "Coming later", "Turns separate findings into one reviewable response",
     "Combines the impact and sourcing reports, resolves conflicts and prepares an evidence-backed recovery proposal"),
]

_NEXT = [
    ("Policy comparison", "Running two inventory policies over the same simulated period and comparing the results. A "
     "Policy Analyst agent could later explain the trade-offs."),
    ("Ward supply rooms", "Par levels and transfers between the central storeroom and the wards."),
    ("Coordinated Supply Recovery Team", "Three specialist agents investigating shortages, recalls and vendor outages "
     "together, then preparing one evidence-backed recovery proposal for a person to approve. No agent can directly "
     "change inventory or send an order."),
]

# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------

CSS = """
:root{--ms-violet:#6D4AFF;--ms-violet-2:#5B3DF5;--ms-navy:#1B1F3B;--ms-text:#4A4F6A;--ms-muted:#7A7F99;
  --ms-line:#E7E4F5;--ms-lav:#F7F6FD;--ms-lav-2:#EEEAFF;}
.block-container{padding-top:3.6rem !important;max-width:1240px !important;}
.ms{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,Helvetica,Arial,sans-serif;color:var(--ms-navy);line-height:1.6;}
.ms *{box-sizing:border-box;}
.ms a{text-decoration:none;}
/* in-page links: the page scrolls inside stMain, under Streamlit's 60px top bar */
[data-testid="stMain"]{scroll-behavior:smooth;}
.ms-sec,#top{scroll-margin-top:156px;}
/* the navigation stays pinned under Streamlit's top bar while the page scrolls */
[data-testid="stElementContainer"]:has(.ms-nav){position:sticky;top:3.75rem;z-index:999;}
.ms-nav{box-shadow:0 10px 26px rgba(43,32,120,.10) !important;}
.ms h1,.ms h2,.ms h3{color:var(--ms-navy);letter-spacing:-.02em;margin:0;padding:0;}
.ms p{color:var(--ms-text);margin:0;}
.ms-ico{display:block;}

/* top strip and navigation */
.ms-strip{background:var(--ms-navy);color:#fff;border-radius:14px 14px 0 0;padding:.45rem 1.4rem;display:flex;
  justify-content:space-between;font-size:.8rem;}
.ms-strip span{color:#D9DBF0;}
.ms-nav{background:#fff;border:1px solid var(--ms-line);border-radius:16px;box-shadow:0 6px 18px rgba(43,32,120,.05);
  padding:.85rem 1.4rem;display:flex;align-items:center;gap:1.6rem;}
.ms-brand{display:flex !important;align-items:center;gap:.6rem;font-weight:800;font-size:1.35rem;color:var(--ms-navy) !important;}
.ms-brand img{width:38px;height:38px;}
.ms-links{display:flex;gap:1.5rem;margin-left:auto;}
.ms-links a{color:var(--ms-text) !important;font-size:.92rem;font-weight:500;padding:.3rem 0;white-space:nowrap;}
@media (max-width:1100px){.ms-links{display:none;} .ms-nav .ms-btn-out{margin-left:auto;}}
.ms-links a.on{color:var(--ms-violet) !important;border-bottom:2px solid var(--ms-violet);}
.ms-links a:hover{color:var(--ms-violet) !important;}
.ms-btn-out{display:inline-flex;align-items:center;gap:.45rem;border:1.5px solid var(--ms-violet);color:var(--ms-violet) !important;
  border-radius:10px;padding:.5rem 1rem;font-weight:600;font-size:.92rem;background:#fff;white-space:nowrap;}
.ms-btn-out:hover{background:var(--ms-lav-2);}

/* hero */
.ms-hero-text{padding:3.2rem 0 0 .4rem;}
.ms-hero-text h1{font-size:clamp(2.2rem,4.4vw,3.3rem);line-height:1.08;font-weight:800;}
.ms-hero-text h1 em{font-style:normal;color:var(--ms-violet);}
.ms-hero-text .lede{font-size:1.12rem;margin:1.2rem 0 1.6rem;max-width:34rem;}
.ms-hero-note strong{color:var(--ms-navy);font-weight:600;}
.ms-hero-note img{margin-top:.15rem;flex:none;}
.ms-hero-note{display:flex;align-items:flex-start;gap:.55rem;color:var(--ms-muted);font-size:.9rem;margin:1.4rem 0 0 .4rem;}
.ms-hero-pic{position:relative;margin-top:1.2rem;}
.ms-hero-pic img.photo{width:100%;height:440px;object-fit:cover;border-radius:22px;display:block;}
.ms-float{position:absolute;left:-28px;bottom:34px;background:#fff;border-radius:16px;padding:.9rem 1.1rem;
  box-shadow:0 18px 40px rgba(43,32,120,.16);min-width:220px;}
.ms-float small{color:var(--ms-muted);font-size:.78rem;display:block;}
.ms-float b{font-size:1.7rem;color:var(--ms-navy);}
.ms-float .tag{font-size:.72rem;color:var(--ms-violet);font-weight:600;}
.st-key-hero_buttons{gap:.8rem;padding-left:.4rem;}
.st-key-open_demo button{background:linear-gradient(135deg,#7C5CFF,#5B3DF5) !important;color:#fff !important;border:none !important;
  border-radius:10px !important;padding:.62rem 1.3rem !important;font-weight:600 !important;box-shadow:0 10px 22px rgba(91,61,245,.28);}
.st-key-open_demo button:hover{filter:brightness(1.07);}
.st-key-open_demo button p{color:#fff !important;font-size:.98rem !important;}

/* sections */
.ms-sec{margin:4.2rem 0 0;}
.ms-eyebrow{color:var(--ms-violet);font-size:.78rem;font-weight:700;letter-spacing:.14em;text-transform:uppercase;margin:0 0 .4rem;}
.ms-sec h2{font-size:clamp(1.55rem,2.6vw,2.05rem);font-weight:750;line-height:1.2;}
.ms-head{display:flex;justify-content:space-between;align-items:flex-end;gap:1rem;margin-bottom:1.4rem;}
.ms-link{color:var(--ms-violet) !important;font-weight:600;font-size:.92rem;display:inline-flex;align-items:center;gap:.35rem;white-space:nowrap;}
.ms-intro{max-width:70ch;margin:.6rem 0 0;}

/* highlight row */
.ms-high{background:#fff;border:1px solid var(--ms-line);border-radius:20px;box-shadow:0 14px 34px rgba(43,32,120,.07);
  display:grid;grid-template-columns:repeat(4,1fr);margin-top:2.4rem;}
.ms-high>div{padding:1.5rem 1.4rem;border-left:1px solid var(--ms-line);}
.ms-high>div:first-child{border-left:none;}
.ms-high h3{font-size:1.06rem;margin:.9rem 0 .25rem;}
.ms-high p{font-size:.9rem;}
.ms-dot{width:48px;height:48px;border-radius:14px;display:flex;align-items:center;justify-content:center;
  background:linear-gradient(140deg,#8B6CFF,#5B3DF5);box-shadow:0 8px 18px rgba(91,61,245,.25);}

/* tool cards */
.ms-tools{display:grid;grid-template-columns:repeat(5,1fr);gap:1rem;}
.ms-tool{background:#fff;border:1px solid var(--ms-line);border-radius:16px;overflow:hidden;display:flex;flex-direction:column;}
.ms-tool-art{height:150px;position:relative;overflow:hidden;display:flex;align-items:center;justify-content:center;
  background:linear-gradient(140deg,#8B6CFF 0%,#5B3DF5 100%);}
.ms-tool-art::before,.ms-tool-art::after{content:"";position:absolute;border-radius:50%;background:#fff;opacity:.10;}
.ms-tool-art::before{width:150px;height:150px;right:-55px;top:-65px;}
.ms-tool-art::after{width:90px;height:90px;left:-30px;bottom:-45px;}
.ms-tool-art img{position:relative;z-index:1;filter:drop-shadow(0 10px 18px rgba(30,10,120,.28));transition:transform .2s ease;}
.ms-tool:hover .ms-tool-art img{transform:translateY(-3px) scale(1.03);}
.ms-tool-body{padding:1rem 1.05rem 1.1rem;}
.ms-tool h3{font-size:1.02rem;margin-bottom:.3rem;}
.ms-tool p{font-size:.86rem;}
.ms-more{margin:1.4rem 0 0;color:var(--ms-muted);font-size:.9rem;}

/* stats band */
.ms-stats{background:linear-gradient(120deg,#7C5CFF,#5B3DF5);border-radius:20px;display:grid;grid-template-columns:repeat(4,1fr);
  padding:1.6rem 1rem;margin-top:4rem;}
.ms-stats>div{display:flex;align-items:center;gap:1rem;justify-content:center;border-left:1px solid rgba(255,255,255,.22);}
.ms-stats>div:first-child{border-left:none;}
.ms-stats b{color:#fff;font-size:2rem;line-height:1;display:block;}
.ms-stats span{color:#E4DEFF;font-size:.9rem;}

/* problems and steps */
.ms-two{display:grid;grid-template-columns:1fr 1fr;gap:2.4rem;align-items:start;}
.ms-list{list-style:none;padding:0;margin:1.2rem 0 0;}
.ms-list li{display:flex;gap:.75rem;padding:.55rem 0;color:var(--ms-text);}
.ms-list li img{margin-top:.2rem;flex:none;}
.ms-list strong{color:var(--ms-navy);}
.ms-steps{display:grid;grid-template-columns:1fr 1fr;gap:.9rem;counter-reset:s;}
.ms-step{background:#fff;border:1px solid var(--ms-line);border-radius:16px;padding:1.1rem 1.2rem;position:relative;}
.ms-step::before{counter-increment:s;content:counter(s);position:absolute;top:1rem;right:1.1rem;width:28px;height:28px;border-radius:50%;
  background:var(--ms-lav-2);color:var(--ms-violet);font-weight:700;font-size:.85rem;display:flex;align-items:center;justify-content:center;}
.ms-step h3{font-size:1rem;margin-bottom:.3rem;padding-right:2rem;}
.ms-step p{font-size:.88rem;}

/* workflow diagram frames */
.st-key-flow_frame iframe,.st-key-agentic_frame iframe{border:1px solid var(--ms-line);border-radius:20px;background:#fff;
  box-shadow:0 14px 34px rgba(43,32,120,.07);}
/* below desktop the agent diagram scales with width, so the frame and Streamlit's wrapper (fixed at 700px)
   follow the diagram's shape instead of reserving empty space */
@media (max-width:1100px){
  .st-key-agentic_frame [data-testid="stElementContainer"]{height:auto !important;flex:0 0 auto !important;}
  .st-key-agentic_frame iframe{height:auto !important;aspect-ratio:16/9;min-height:220px;max-height:700px;}
}

/* Agentic AI portfolio */
.ms-agent-lede{max-width:76ch;}
.ms-agent-principles{display:grid;grid-template-columns:repeat(3,1fr);gap:.8rem;margin:1.3rem 0 1.5rem;}
.ms-agent-principles>div{background:var(--ms-lav-2);border:1px solid #DED7FF;border-radius:14px;padding:.9rem 1rem;}
.ms-agent-principles b{display:block;color:var(--ms-navy);font-size:.9rem;margin-bottom:.2rem;}
.ms-agent-principles span{display:block;color:var(--ms-text);font-size:.83rem;line-height:1.45;}
.ms-agent-table{width:100%;border:1px solid var(--ms-line);border-radius:18px;border-spacing:0;overflow:hidden;background:#fff;
  box-shadow:0 6px 18px rgba(43,32,120,.04);}
.ms-agent-table th{text-align:left;background:var(--ms-lav);color:var(--ms-muted);font-size:.75rem;letter-spacing:.06em;
  text-transform:uppercase;padding:.8rem 1rem;border-bottom:1px solid var(--ms-line);}
.ms-agent-table td{vertical-align:top;color:var(--ms-text);font-size:.86rem;line-height:1.45;padding:1rem;border-bottom:1px solid var(--ms-line);}
.ms-agent-table tr:last-child td{border-bottom:none;}
.ms-agent-table td:first-child{color:var(--ms-navy);font-weight:700;white-space:nowrap;}
.ms-agent-status{display:inline-block;border-radius:999px;padding:.2rem .55rem;font-size:.72rem;font-weight:700;white-space:nowrap;}
.ms-agent-status.built{background:#E2F7EF;color:#08775B;}
.ms-agent-status.planned{background:#FFF2D9;color:#9B5A00;}
.ms-agent-team{max-width:80ch;margin:1rem 0 0;color:var(--ms-text);font-size:.92rem;line-height:1.55;}
.ms-agent-note{max-width:76ch;margin:.6rem 0 0;color:var(--ms-muted);font-size:.86rem;line-height:1.5;}

/* course and my work */
.ms-course{display:grid;grid-template-columns:.95fr 1.05fr;background:var(--ms-lav-2);border-radius:22px;overflow:hidden;}
.ms-course img.photo{width:100%;height:100%;min-height:380px;object-fit:cover;display:block;}
.ms-course>div{padding:2.4rem 2.4rem;}
.ms-btn{display:inline-flex;align-items:center;gap:.45rem;background:linear-gradient(135deg,#7C5CFF,#5B3DF5);color:#fff !important;
  border-radius:10px;padding:.6rem 1.15rem;font-weight:600;font-size:.92rem;margin:1.2rem 0 .6rem;}
.ms-cols{display:grid;grid-template-columns:1fr 1fr;gap:1.4rem;margin-top:1.6rem;}
.ms-cols h3{font-size:1.02rem;margin-bottom:.7rem;display:flex;align-items:center;gap:.5rem;}
.ms-mini{background:#fff;border:1px solid var(--ms-line);border-radius:14px;padding:.85rem 1rem;margin-bottom:.6rem;}
.ms-mini b{color:var(--ms-navy);font-size:.94rem;}
.ms-mini p{font-size:.86rem;}

/* stack, scope, next */
.ms-chips{display:flex;flex-wrap:wrap;gap:.5rem;margin-top:1rem;}
.ms-chip{background:#fff;border:1px solid var(--ms-line);color:var(--ms-navy);border-radius:999px;padding:.35rem .95rem;font-size:.86rem;font-weight:600;}
.ms-next{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:1rem;margin-top:1.2rem;}
.ms-next>div{background:#fff;border:1px solid var(--ms-line);border-radius:16px;padding:1.1rem 1.15rem;}
.ms-next h3{font-size:.98rem;margin-bottom:.3rem;}
.ms-next p{font-size:.86rem;}

/* call to action and footer */
.ms-cta{background:linear-gradient(120deg,#7C5CFF,#5B3DF5);border-radius:20px;padding:1.6rem 2rem;display:flex;align-items:center;gap:1.6rem;margin-top:4.2rem;}
.ms-cta .circle{width:64px;height:64px;border-radius:50%;background:#fff;display:flex;align-items:center;justify-content:center;flex:none;}
.ms-cta h2{color:#fff;font-size:1.5rem;}
.ms-cta p{color:#E4DEFF;font-size:.92rem;}
.ms-cta a{margin-left:auto;border:1.5px solid #fff;color:#fff !important;border-radius:10px;padding:.6rem 1.2rem;font-weight:600;
  display:inline-flex;align-items:center;gap:.45rem;white-space:nowrap;}
.ms-cta a:hover{background:rgba(255,255,255,.12);}
.ms-foot{display:grid;grid-template-columns:1.6fr 1fr 1fr 1fr;gap:1.6rem;margin-top:3rem;padding:0 .4rem;}
.ms-foot h4{font-size:.92rem;color:var(--ms-navy);margin:0 0 .6rem;}
.ms-foot a,.ms-foot span{display:block;color:var(--ms-text) !important;font-size:.88rem;padding:.15rem 0;}
.ms-foot a:hover{color:var(--ms-violet) !important;}
.ms-foot p{font-size:.88rem;margin-top:.7rem;max-width:30ch;}
.ms-bottom{display:flex;justify-content:space-between;border-top:1px solid var(--ms-line);margin:2rem 0 1rem;padding:1rem .4rem 0;
  color:var(--ms-muted);font-size:.82rem;}

/* Ask MedStock section */
.ms-ask-card{background:#fff;border:1px solid var(--ms-line);border-radius:20px;padding:1.4rem 1.5rem;box-shadow:0 6px 18px rgba(43,32,120,.05);}
.ms-ask-card .lbl{font-size:.78rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--ms-muted);margin:0 0 .6rem;}
.ms-q{display:flex;gap:.6rem;align-items:flex-start;background:var(--ms-lav-2);color:var(--ms-navy);border-radius:14px 14px 14px 4px;
  padding:.6rem .85rem;margin:.5rem 0;font-size:.92rem;line-height:1.45;}
.ms-q img{flex:none;margin-top:.15rem;}
.ms-ask-note{font-size:.82rem;color:var(--ms-muted);margin:.9rem 0 0;}
@media (max-width:900px){
  .ms-links{display:none;} .ms-nav .ms-btn-out{margin-left:auto;}
  .ms-high,.ms-stats{grid-template-columns:1fr 1fr;} .ms-stats>div{border-left:none;padding:.6rem 0;}
  .ms-high>div:nth-child(3){border-left:none;} .ms-high>div{border-top:1px solid var(--ms-line);}
  .ms-tools{grid-template-columns:1fr 1fr;} .ms-next{grid-template-columns:1fr 1fr;}
  .ms-two,.ms-course,.ms-cols{grid-template-columns:1fr;} .ms-foot{grid-template-columns:1fr 1fr;}
  .ms-agent-principles{grid-template-columns:1fr;}
  .ms-float{left:12px;bottom:12px;} .ms-hero-pic img.photo{height:300px;} .ms-hero-text{padding-top:1.6rem;}
  .ms-cta{flex-wrap:wrap;} .ms-cta a{margin-left:0;}
}
@media (max-width:560px){
  .ms-high,.ms-stats,.ms-tools,.ms-next,.ms-steps,.ms-foot{grid-template-columns:1fr;}
  .ms-high>div{border-left:none;} .ms-strip span:last-child{display:none;}
  .ms-agent-table,.ms-agent-table tbody,.ms-agent-table tr,.ms-agent-table td{display:block;width:100%;}
  .ms-agent-table thead{display:none;}
  .ms-agent-table tr{padding:.8rem 1rem;border-bottom:1px solid var(--ms-line);}
  .ms-agent-table tr:last-child{border-bottom:none;}
  .ms-agent-table td{border:0;padding:.28rem 0;white-space:normal !important;}
  .ms-agent-table td::before{content:attr(data-label);display:block;color:var(--ms-muted);font-size:.7rem;font-weight:700;
    letter-spacing:.05em;text-transform:uppercase;margin-bottom:.1rem;}
}
"""

# ---------------------------------------------------------------------------
# HTML pieces
# ---------------------------------------------------------------------------

def _top():
    return f"""<div class="ms">
  <nav class="ms-nav" id="top">
    <a class="ms-brand" href="#top"><img src="{LOGO}" alt="">MedStock</a>
    <div class="ms-links">
      <a class="on" href="#top">Home</a><a href="#what">What it does</a><a href="#ask">Ask MedStock</a><a href="#agentic">Agentic AI</a>
      <a href="#course">Course and my work</a><a href="#next">Roadmap</a>
    </div>
    <a class="ms-btn-out" href="{DEMO_LINK}" target="_self">Open the demo {icon('arrow', size=16)}</a>
  </nav>
</div>"""


HERO_TEXT = """<div class="ms ms-hero-text">
  <h1>Hospital supply planning,<br><em>tested day by day.</em></h1>
  <p class="lede">A hospital supply room inventory planner I built to put my supply chain coursework into
     practice. It tracks """ + str(ITEM_COUNT) + """ medical supplies, tells you what to order and how much, and lets you
     fast-forward time to see whether those decisions hold up.</p>
</div>"""


def _hero_pic():
    return f"""<div class="ms ms-hero-pic">
  <img class="photo" src="{IMG}hero.jpg" alt="A tidy hospital supply room">
  <div class="ms-float"><small>Fill rate</small><b>98.7%</b>
    <img src="{_spark()}" width="190" height="34" alt="" style="display:block;margin:.2rem 0">
    <span class="tag">Example from a simulated month</span></div>
</div>"""


def _spark():
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 190 34">'
           '<defs><linearGradient id="f" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#6D4AFF" stop-opacity=".25"/>'
           '<stop offset="1" stop-color="#6D4AFF" stop-opacity="0"/></linearGradient></defs>'
           '<path d="M2 26 L22 22 L40 25 L60 17 L80 20 L100 13 L120 16 L140 9 L160 12 L188 4 L188 34 L2 34 Z" fill="url(#f)"/>'
           '<path d="M2 26 L22 22 L40 25 L60 17 L80 20 L100 13 L120 16 L140 9 L160 12 L188 4" fill="none" stroke="#6D4AFF" '
           'stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/></svg>')
    return _data_uri(svg)


def _hero_note():
    return (f'<div class="ms ms-hero-note">{icon("cap", "#7A7F99", 20)}<span><strong>Supply chain portfolio '
            f'project by Wendyl Jaca.</strong> Built for my Supply Chain Management course at the University of '
            f'Portland. All data is fictional, and the demo is invite-only.</span></div>')


def _body():
    highlights = "".join(
        f'<div><div class="ms-dot">{icon(ic, "#FFFFFF")}</div><h3>{_esc(t)}</h3><p>{_esc(d)}</p></div>'
        for ic, col, bg, t, d in _HIGHLIGHTS)
    tools = "".join(
        f'<div class="ms-tool"><div class="ms-tool-art"><img src="{ui.solid_uri(ic)}" width="78" height="78" alt=""></div>'
        f'<div class="ms-tool-body"><h3>{_esc(t)}</h3><p>{_esc(d)}</p></div></div>'
        for ic, t, d in _TOOLS)
    stats = "".join(f'<div>{icon(ic, "#FFFFFF", 34)}<div><b>{v}</b><span>{_esc(lbl)}</span></div></div>'
                    for ic, v, lbl in _STATS)
    problems = "".join(f'<li>{icon("alert", "#E5534B", 18)}<span><strong>{_esc(t)}.</strong> {_esc(d)}</span></li>'
                       for t, d in _PROBLEMS)
    steps = "".join(f'<div class="ms-step"><h3>{_esc(t)}</h3><p>{_esc(d)}</p></div>' for t, d in _STEPS)
    course_short = "".join(f'<li>{icon(ic, "#6D4AFF", 18)}<span>{_esc(t)}</span></li>' for ic, t in _COURSE_SHORT)
    course = "".join(f'<div class="ms-mini"><b>{_esc(t)}</b><p>{_esc(d)}</p></div>' for t, d in _COURSE)
    ext = "".join(f'<div class="ms-mini"><b>{_esc(t)}</b><p>{_esc(d)}</p></div>' for t, d in _EXTENSIONS)
    chips = "".join(f'<span class="ms-chip">{_esc(x)}</span>' for x in _STACK)
    nxt = "".join(f'<div><h3>{_esc(t)}</h3><p>{_esc(d)}</p></div>' for t, d in _NEXT)
    return f"""<div class="ms">
  <div class="ms-high">{highlights}</div>

  <section class="ms-sec" id="what">
    <div class="ms-head"><div><p class="ms-eyebrow">What it does</p><h2>One supply room, every decision</h2></div>
      <a class="ms-link" href="{GITHUB}/blob/main/docs/USER_GUIDE.md" target="_blank">See the user guide {icon('arrow', size=16)}</a></div>
    <div class="ms-tools">{tools}</div>
    <p class="ms-more">Also in the app: stock movements, item detail with the calculation behind every number, and a
       full transaction history you can export.</p>
  </section>

  <div class="ms-stats">{stats}</div>
<!--ASK-->

  <section class="ms-sec" id="how">
    <div class="ms-two">
      <div><p class="ms-eyebrow">The problem</p><h2>Why hospital inventory is hard</h2>
        <p class="ms-intro">A supply room has to avoid two opposite mistakes. Run short on IV fluids or insulin and
           patient care suffers. Overstock slow-moving items and they expire on the shelf. On top of that, lead
           times vary by vendor and demand changes with the season.</p>
        <ul class="ms-list">{problems}</ul></div>
      <div><p class="ms-eyebrow">How it works</p><h2>A simulated day</h2>
        <p class="ms-intro" style="margin-bottom:1.2rem">Press a button and the hospital moves forward one day.</p>
        <div class="ms-steps">{steps}</div></div>
    </div>
  </section>

  <!--DIAGRAM-->
  <section class="ms-sec" id="course">
    <div class="ms-course">
      <img class="photo" src="{IMG}storeroom.jpg" alt="A storeroom staff member scanning a box">
      <div><p class="ms-eyebrow">Course and my work</p><h2>What came from class and what I added</h2>
        <p class="ms-intro">The formulas come from the Inventory Management and Forecasting units of my Supply Chain
           Management course at the University of Portland. The hospital setting and everything built around the
           formulas is my own research.</p>
        <a class="ms-btn" href="{GITHUB}/blob/main/docs/BUILD_LOG.md" target="_blank">Read the build log {icon('arrow', '#FFFFFF', 16)}</a>
        <ul class="ms-list">{course_short}</ul></div>
    </div>
    <div class="ms-cols">
      <div><h3>{icon('cap', size=20)}From the course</h3>{course}</div>
      <div><h3>{icon('flask', size=20)}My additions</h3>{ext}</div>
    </div>
  </section>

  <section class="ms-sec">
    <div class="ms-two">
      <div><p class="ms-eyebrow">Built with</p><h2>Open tools, checkable math</h2>
        <p class="ms-intro">Each screen can show the calculation behind its numbers, so you can check why an item was
           flagged instead of taking it on faith.</p><div class="ms-chips">{chips}</div></div>
      <div><p class="ms-eyebrow">Scope and limits</p><h2>What this is and isn't</h2>
        <ul class="ms-list">
          <li>{icon('check', size=18)}<span><strong>Synthetic data.</strong> The hospital, its usage history and all four vendors are made up.</span></li>
          <li>{icon('check', size=18)}<span><strong>A learning project.</strong> It isn't clinical software and hasn't been used in a real hospital.</span></li>
        </ul></div>
    </div>
  </section>

  <section class="ms-sec" id="next">
    <p class="ms-eyebrow">Roadmap</p><h2>What's next</h2>
    <p class="ms-intro">MedStock is a work in progress. These are the next things I plan to build.</p>
    <div class="ms-next">{nxt}</div>
  </section>

  <div class="ms-cta">
    <div class="circle"><img src="{LOGO}" width="40" height="40" alt=""></div>
    <div><h2>See it run on simulated days</h2><p>The demo is invite-only. Ask me for access.</p></div>
    <a href="{DEMO_LINK}" target="_self">Open the demo {icon('arrow', '#FFFFFF', 16)}</a>
  </div>

  <footer class="ms-foot">
    <div><a class="ms-brand" href="#top"><img src="{LOGO}" alt="">MedStock</a>
      <p>A hospital supply inventory planner, built as a supply chain portfolio project.</p></div>
    <div><h4>Explore</h4><a href="#what">What it does</a><a href="#agentic">Agentic AI</a><a href="#how">How it works</a><a href="#next">Roadmap</a></div>
    <div><h4>Docs</h4><a href="{GITHUB}/blob/main/docs/USER_GUIDE.md" target="_blank">User guide</a>
      <a href="{GITHUB}/blob/main/docs/HOW_IT_WORKS.md" target="_blank">How it works</a>
      <a href="{GITHUB}/blob/main/docs/BUILD_LOG.md" target="_blank">Build log</a></div>
    <div><h4>Project</h4><a href="{GITHUB}" target="_blank">Source code on GitHub</a><span>Built with Python and Streamlit</span></div>
  </footer>
  <div class="ms-bottom"><span>MedStock is a learning project. Not clinical software.</span><span>All data is fictional.</span></div>
</div>"""


def _ask_section():
    facts = "".join(f'<li>{icon(ic, size=18)}<span><strong>{_esc(t)}</strong> {_esc(d)}</span></li>'
                    for ic, t, d in _ASK_FACTS)
    questions = "".join(f'<div class="ms-q">{icon("sparkles", size=16)}<span>{_esc(q)}</span></div>'
                        for q in ASK_QUESTIONS)
    return f"""<div class="ms"><section class="ms-sec" id="ask">
    <div class="ms-two">
      <div><p class="ms-eyebrow">Ask MedStock: AI assistant</p><h2>Ask a question, get an answer from the data</h2>
        <p class="ms-intro">Ask about stock risks, what to reorder, Vital items, vendor disruptions, recalls or
           performance. Ask MedStock provides AI-powered supply-chain analysis using MedStock's governed, read-only
           tools. It looks up the answer in the app's fictional data, then shows what it checked.</p>
        <ul class="ms-list">{facts}</ul></div>
      <div class="ms-ask-card"><p class="lbl">Questions you can ask</p>{questions}
        <p class="ms-ask-note">Answers come only from MedStock's fictional data. Don't enter real patient, hospital or
           personal information.</p></div>
    </div>
  </section></div>"""


def _agentic_section():
    rows = "".join(
        f'<tr><td data-label="Agent">{_esc(name)}</td>'
        f'<td data-label="Status"><span class="ms-agent-status {"built" if status == "Built" else "planned"}">{_esc(status)}</span></td>'
        f'<td data-label="Problem it helps solve">{_esc(problem)}</td>'
        f'<td data-label="How it works">{_esc(how)}</td></tr>'
        for name, status, problem, how in _AGENTS)
    return f"""<div class="ms"><section class="ms-sec" id="agentic">
      <p class="ms-eyebrow">Agentic AI</p><h2>Agentic AI for governed supply-chain decisions</h2>
      <p class="ms-intro ms-agent-lede">MedStock combines deterministic supply-chain planning with a tool-using AI
        layer. Today, Ask MedStock investigates inventory, purchasing and supply-risk questions using governed,
        read-only tools. The next phase adds a coordinated team of specialist agents that can investigate
        disruptions and prepare recovery proposals, while people retain approval and MedStock's validated functions
        perform every change.</p>
      <div class="ms-agent-principles">
        <div><b>The engine calculates</b><span>Forecasts, reorder points, suggested quantities and stock balances remain deterministic and checkable.</span></div>
        <div><b>Agents investigate and coordinate</b><span>Agents divide the work, use governed tools and exchange structured evidence instead of relying on free-form conversations.</span></div>
        <div><b>People keep authority</b><span>Proposed actions wait for approval. Tool calls, agent handoffs, corrections, decisions and outcomes are recorded.</span></div>
      </div>
      <table class="ms-agent-table" aria-label="MedStock agents and their status">
        <thead><tr><th>Agent</th><th>Status</th><th>Problem it helps solve</th><th>How it works</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
      <p class="ms-agent-team">The Inventory Impact Agent and Sourcing Agent can investigate the same event in
        parallel. The Recovery Planner Agent combines their structured findings into one proposal. Deterministic
        checks validate the quantities and constraints before a person can approve anything.</p>
      <div class="ms-head" style="margin-top:2rem"><div><p class="ms-eyebrow">Coordinated agent workflow</p>
        <h2>How MedStock's agent team works</h2>
        <p class="ms-intro">Trace today's read-only question path and the planned team workflow for shortages,
          recalls and vendor disruptions. Calculations, validation, approval and database changes remain outside
          the AI model.</p>
        <p class="ms-agent-note">The Case Coordinator is not another AI agent. It manages the case ID, parallel work,
          retries, structured handoffs and duplicate prevention.</p></div>
        <a class="ms-link" href="{IMG}agentic-workflow.html?theme=light" target="_blank">Open full screen {icon('arrow', size=16)}</a></div>
    </section></div>"""


def open_demo():
    st.session_state["view"] = "demo" if st.session_state.get("user") else "login"


def open_ask():
    """Ask MedStock from the homepage: straight there when signed in, otherwise via sign-in."""
    st.session_state["page"] = "Ask MedStock"
    st.session_state["view"] = "demo" if st.session_state.get("user") else "login"


def render_homepage():
    st.html("<style>" + CSS + "</style>")
    st.html(_top())
    left, right = st.columns([1.02, 1], gap="large")
    with left:
        st.html(HERO_TEXT)
        with st.container(horizontal=True, key="hero_buttons"):
            st.button("Explore the inventory demo", key="open_demo", icon=":material/arrow_forward:",
                      icon_position="right", on_click=open_demo)
            st.html('<div class="ms"><a class="ms-btn-out" href="#how" style="padding:.62rem 1.2rem">How it works</a></div>')
        st.html(_hero_note())
    with right:
        st.html(_hero_pic())
    before, after = _body().split("<!--DIAGRAM-->")
    top, middle = before.split("<!--ASK-->")
    st.html(top + "</div>")
    st.html(_ask_section())
    signed_in = bool(st.session_state.get("user"))
    with st.container(horizontal=True, key="ask_cta", vertical_alignment="center"):
        st.button("Open Ask MedStock" if signed_in else "Sign in to try Ask MedStock", key="open_ask",
                  icon=":material/auto_awesome:", on_click=open_ask, type="primary")
        st.caption("You're signed in." if signed_in else "Invite-only, like the rest of the demo.")
    st.html(_agentic_section())
    with st.container(key="agentic_frame"):
        st.iframe("/" + IMG + "agentic-workflow.html?theme=light&embed=1", height=700)
    st.html('<div class="ms">' + middle + "</div>")
    st.html(f"""<div class="ms"><section class="ms-sec" id="flow">
      <div class="ms-head"><div><p class="ms-eyebrow">Workflow</p><h2>How a day flows through MedStock</h2>
        <p class="ms-intro">From a ward's request to a delivery at the dock, plus the two things that can
           go wrong along the way. Zoom, search or click a step to trace it.</p></div>
        <a class="ms-link" href="{IMG}workflow.html?theme=light" target="_blank">Open full screen {icon('arrow', size=16)}</a></div>
    </section></div>""")
    with st.container(key="flow_frame"):
        st.iframe("/" + IMG + "workflow.html?theme=light&embed=1", height=700)
    st.html('<div class="ms">' + after)
