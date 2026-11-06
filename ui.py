"""
ui.py: MedStock's visual building blocks, shared by the app and the homepage.

* COLORS: the palette from the approved design mockup.
* ICONS: line icons in the style of the open-source Lucide set (24x24, stroke only).
* icon_uri / tile_uri: turn an icon into an SVG data URI. Streamlit strips raw <svg> tags from
  st.html, and buttons only take emoji or Material icons, so custom icons are drawn through CSS
  background images or <img> tags instead.
* nav_css / app_css: the sidebar navigation and the card styling for the demo.
"""

import base64

COLORS = {
    "violet": "#6D4AFF", "blue": "#3B7BF6", "green": "#16A394", "red": "#E5534B", "amber": "#E59A1A",
    "gray": "#7A7F99", "navy": "#1B1F3B",
}
TINTS = {
    "violet": "#EEEAFF", "blue": "#E6EFFE", "green": "#E3F6F3", "red": "#FDECEB", "amber": "#FDF3E1",
    "gray": "#EFF0F5",
}

ICONS = {
    "dashboard": '<rect width="7" height="9" x="3" y="3" rx="1.5"/><rect width="7" height="5" x="14" y="3" rx="1.5"/><rect width="7" height="9" x="14" y="12" rx="1.5"/><rect width="7" height="5" x="3" y="16" rx="1.5"/>',
    "gauge": '<path d="m12 14 4-4"/><path d="M3.34 19a10 10 0 1 1 17.32 0"/>',
    "cart": '<circle cx="8" cy="21" r="1"/><circle cx="19" cy="21" r="1"/><path d="M2.05 2.05h2l2.66 12.42a2 2 0 0 0 2 1.58h9.78a2 2 0 0 0 1.95-1.57l1.65-7.43H5.12"/>',
    "swap": '<path d="M8 3 4 7l4 4"/><path d="M4 7h16"/><path d="m16 21 4-4-4-4"/><path d="M20 17H4"/>',
    "alert": '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    "trend": '<polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/>',
    "expiry": '<path d="M21 7.5V6a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h3.5"/><path d="M16 2v4"/><path d="M8 2v4"/><path d="M3 10h5"/><path d="M17.5 17.5 16 16.3V14"/><circle cx="16" cy="16" r="6"/>',
    "box": '<path d="m7.5 4.27 9 5.15"/><path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/>',
    "history": '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l4 2"/>',
    "grid": '<rect width="7" height="7" x="3" y="3" rx="1.5"/><rect width="7" height="7" x="14" y="3" rx="1.5"/><rect width="7" height="7" x="14" y="14" rx="1.5"/><rect width="7" height="7" x="3" y="14" rx="1.5"/>',
    "calculator": '<rect width="16" height="20" x="4" y="2" rx="2"/><path d="M8 6h8"/><path d="M16 14v4"/><path d="M16 10h.01"/><path d="M12 10h.01"/><path d="M8 10h.01"/><path d="M12 14h.01"/><path d="M8 14h.01"/><path d="M12 18h.01"/><path d="M8 18h.01"/>',
    "help": '<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><path d="M12 17h.01"/>',
    "heart": '<path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z"/><path d="M3.22 12H9.5l.5-1 2 4.5 2-7 1.5 3.5h5.27"/>',
    "dollar": '<path d="M12 2v20"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>',
    "clock": '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    "pie": '<path d="M21.21 15.89A10 10 0 1 1 8 2.83"/><path d="M22 12A10 10 0 0 0 12 2v10z"/>',
    "truck": '<path d="M14 18V6a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v11a1 1 0 0 0 1 1h2"/><path d="M15 18H9"/><path d="M19 18h2a1 1 0 0 0 1-1v-3.65a1 1 0 0 0-.22-.624l-3.48-4.35A1 1 0 0 0 17.52 8H14"/><circle cx="17" cy="18" r="2"/><circle cx="7" cy="18" r="2"/>',
    "users": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    "wrench": '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>',
    "file": '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M16 13H8"/><path d="M16 17H8"/><path d="M10 9H8"/>',
    "check": '<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>',
    "cap": '<path d="M22 10v6M2 10l10-5 10 5-10 5z"/><path d="M6 12v5c3 3 9 3 12 0v-5"/>',
    "flask": '<path d="M10 2v7.31"/><path d="M14 9.3V1.99"/><path d="M8.5 2h7"/><path d="M14 9.3a6.5 6.5 0 1 1-4 0"/><path d="M5.52 16h12.96"/>',
    "arrow": '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
    "home": '<path d="M15 21v-8a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v8"/><path d="M3 10a2 2 0 0 1 .709-1.528l7-5.999a2 2 0 0 1 2.582 0l7 5.999A2 2 0 0 1 21 10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "repeat": '<path d="m17 2 4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14"/><path d="m7 22-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/>',
    "calendar": '<rect width="18" height="18" x="3" y="4" rx="2"/><path d="M16 2v4"/><path d="M8 2v4"/><path d="M3 10h18"/>',
    "trash": '<path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/>',
    "send": '<path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/>',
    "xcircle": '<circle cx="12" cy="12" r="10"/><path d="m15 9-6 6"/><path d="m9 9 6 6"/>',
    "edit": '<path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
    "factory": '<path d="M2 20a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V8l-7 5V8l-7 5V4a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2Z"/><path d="M17 18h1"/><path d="M12 18h1"/><path d="M7 18h1"/>',
    "search": '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    "sparkles": '<path d="M9.94 14.06 7.5 21l-2.44-6.94L-1.88 11.62 5.06 9.18 7.5 2.24l2.44 6.94 6.94 2.44z" transform="translate(4.5 0) scale(.85)"/><path d="M19 3v4"/><path d="M21 5h-4"/><path d="M18 15v3"/><path d="M19.5 16.5h-3"/>',
    "list": '<path d="M3 6h.01"/><path d="M3 12h.01"/><path d="M3 18h.01"/><path d="M8 6h13"/><path d="M8 12h13"/><path d="M8 18h13"/>',
    "bell": '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
    "logout": '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><path d="M21 12H9"/>',
}


def data_uri(svg):
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


def icon_uri(name, color=COLORS["violet"], stroke=1.9):
    """A plain line icon."""
    return data_uri(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
                    f'stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round">{ICONS[name]}</svg>')


def tile_uri(name, color="violet", active=False):
    """The MedStock icon tile: a rounded square in a soft tint with a colored line icon.
    The active tile is solid violet with a white icon, like the logo."""
    if active:
        bg = ('<defs><linearGradient id="t" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#8B6CFF"/>'
              '<stop offset="1" stop-color="#5B3DF5"/></linearGradient></defs><rect width="32" height="32" rx="9" fill="url(#t)"/>')
        stroke = "#FFFFFF"
    else:
        bg = f'<rect width="32" height="32" rx="9" fill="{TINTS[color]}"/>'
        stroke = COLORS[color]
    return data_uri(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">{bg}'
                    f'<g transform="translate(6.5 6.5) scale(0.79)" fill="none" stroke="{stroke}" stroke-width="2.1" '
                    f'stroke-linecap="round" stroke-linejoin="round">{ICONS[name]}</g></svg>')


def img(name, color=COLORS["violet"], size=22, cls="ms-ico"):
    return f'<img class="{cls}" src="{icon_uri(name, color)}" width="{size}" height="{size}" alt="">'


# The demo's pages, in sidebar order: (title, icon, color).
PAGES = [
    ("Dashboard", "dashboard", "violet"),
    ("Inventory", "list", "blue"),
    ("Ask MedStock", "sparkles", "violet"),
    ("KPIs", "gauge", "blue"),
    ("Purchasing", "cart", "green"),
    ("Stock movements", "swap", "blue"),
    ("Recalls & disruptions", "alert", "red"),
    ("Forecast", "trend", "violet"),
    ("Expiry", "expiry", "amber"),
    ("Item detail", "box", "blue"),
    ("History", "history", "green"),
    ("ABC-VED analysis", "grid", "violet"),
    ("Calculators", "calculator", "green"),
    ("Help", "help", "gray"),
]


# Sidebar layout. Pages keep their internal titles (used in code and tests); some show a shorter
# menu label. Every page in PAGES that is not a main page is listed under "More".
MAIN_PAGES = ["Dashboard", "Inventory", "Purchasing", "Forecast", "Recalls & disruptions", "KPIs", "Ask MedStock"]
NAV_LABELS = {"Recalls & disruptions": "Alerts", "KPIs": "Reports"}
MORE_PAGES = [t for t, _, _ in PAGES if t not in MAIN_PAGES]


def nav_label(title):
    return NAV_LABELS.get(title, title)


def page_slug(title):
    """The page's name in the address bar: 'Recalls & disruptions' -> 'alerts', 'Item detail' -> 'item-detail'."""
    label = nav_label(title).lower()
    return "".join(ch if ch.isalnum() else "-" for ch in label).strip("-").replace("--", "-")


def page_from_slug(slug):
    """The page title for an address-bar name, or None if there is no such page."""
    return next((t for t, _, _ in PAGES if page_slug(t) == (slug or "").strip().lower()), None)


def nav_key(title):
    return "nav_" + "".join(ch if ch.isalnum() else "_" for ch in title.lower())


def nav_css(active, badges=None):
    """CSS for the sidebar menu: an icon tile before each button, a highlight on the open page and
    a red count badge where something needs attention."""
    rules = []
    for title, ic, color in PAGES:
        k = f".st-key-{nav_key(title)} button"
        rules.append(f'{k}::before{{background-image:url("{tile_uri(ic, color, title == active)}");}}')
        if title == active:
            rules.append(f"{k}{{background:{TINTS['violet']} !important;}}"
                         f"{k} p{{color:{COLORS['violet']} !important;font-weight:650 !important;}}")
        if badges and badges.get(title):
            rules.append(f'{k}::after{{content:"{int(badges[title])}";}}')
    return "\n".join(rules)


def kpi_css(cards):
    """cards: {container_key: (icon, color)}. Draws the colored icon tile on each KPI card."""
    return "\n".join(
        f'.st-key-{k} [data-testid="stMetric"]::before{{background-image:url("{tile_uri(ic, color)}");}}'
        for k, (ic, color) in cards.items())


def drill_css(cues):
    """cues: {drill button key: visible text}. The card's corner hint; screen readers use the button label."""
    return "".join(f'.st-key-{k} button::after{{content:"{cue}" / "";}}' for k, cue in cues.items())


APP_CSS = """
/* sidebar menu */
[data-testid="stSidebar"] [class*="st-key-nav_"] button{justify-content:flex-start;background:transparent;border:none;
  box-shadow:none;padding:.32rem .55rem;min-height:2.6rem;border-radius:12px;gap:0;}
[data-testid="stSidebar"] [class*="st-key-nav_"] button:hover{background:#F3F1FC;}
[data-testid="stSidebar"] [class*="st-key-nav_"] button > div{justify-content:flex-start;flex:1;}
[data-testid="stSidebar"] [class*="st-key-nav_"] button p{font-size:.95rem;color:#2B3050;font-weight:500;text-align:left;}
[data-testid="stSidebar"] [class*="st-key-nav_"] button::before{content:"";width:32px;height:32px;flex:none;
  margin-right:.75rem;background-size:contain;background-repeat:no-repeat;}
[data-testid="stSidebar"] [class*="st-key-nav_"] button::after{margin-left:auto;background:#E5534B;color:#fff;
  border-radius:999px;font-size:.72rem;font-weight:700;min-width:1.35rem;height:1.35rem;display:flex;
  align-items:center;justify-content:center;padding:0 .35rem;}
[data-testid="stSidebar"] [class*="st-key-nav_"]{margin-bottom:-.55rem;}
.st-key-nav_menu, .st-key-nav_more{gap:.15rem;}
[data-testid="stSidebar"] .st-key-nav_menu{margin-bottom:0;}   /* room between the last item's highlight and More */
.ms-menu-label{color:#7A7F99;font-size:.72rem;font-weight:700;letter-spacing:.12em;text-transform:uppercase;margin:.2rem 0 .1rem .55rem;}

/* dashboard cards and charts */
[class*="st-key-card_"]{background:#FFFFFF;border-radius:18px !important;border-color:#E7E4F5 !important;
  box-shadow:0 6px 18px rgba(43,32,120,.05);}
[class*="st-key-card_"] [data-testid="stMarkdownContainer"] p strong{font-size:1.02rem;color:#1B1F3B;}
[class*="st-key-alert_"]{border-bottom:1px solid #F0EEF8;padding:.35rem 0;}
[class*="st-key-alert_"]:last-child{border-bottom:none;}
.ms-alert{display:flex;gap:.75rem;align-items:flex-start;}
.ms-alert img{flex:none;}
.ms-alert b{display:block;color:#1B1F3B;font-size:.92rem;line-height:1.3;}
.ms-alert span{display:block;color:#6B7090;font-size:.82rem;line-height:1.4;margin-top:.1rem;}
[class*="st-key-alert_"] button{padding:.2rem .8rem;min-height:2rem;font-size:.85rem;}

/* responsive card rows (app.card_row): equal-height cards that wrap instead of squeezing */
[class*="st-key-row_"]{align-items:stretch;}
[class*="st-key-row_"] > *{min-width:0;}
.st-key-row_kpi > *{flex:1 1 200px;}
.st-key-row_stage > *{flex:1 1 170px;}
.st-key-row_supply > *{flex:1 1 240px;}
.st-key-row_chart1 > *, .st-key-row_chart2 > *{flex:1 1 380px;}

/* simulation card in the sidebar */
.st-key-sim_card{background:#F7F6FD;border:1px solid #E7E4F5;border-radius:16px;padding:.9rem .85rem .8rem;}
.st-key-sim_card h3{font-size:1rem !important;padding:0 !important;}

/* type scale: page title > section title > card label; numbers bold but not shouting */
.block-container{padding-top:2.2rem;}
.block-container h2{font-size:1.85rem !important;font-weight:750 !important;letter-spacing:-.02em;color:#1B1F3B;}
.block-container h3{font-size:1.12rem !important;font-weight:650 !important;color:#1B1F3B;}
[data-testid="stCaptionContainer"]{color:#6B7090;}

/* section header: icon tile, title, one-line question */
.ms-sh{display:flex;align-items:center;gap:.8rem;margin:1.6rem 0 .7rem;}
.ms-sh img{width:38px;height:38px;flex:none;}
.ms-sh b{display:block;font-size:1.08rem;font-weight:650;color:#1B1F3B;line-height:1.25;}
.ms-sh span{display:block;font-size:.88rem;color:#6B7090;}
.st-key-sim_card .ms-sh{margin:0 0 .3rem;}
.st-key-sim_card .ms-sh b{font-size:.98rem;}
.st-key-sim_card .ms-sh span{font-size:.84rem;color:#4A4F6A;}

/* metric cards */
[data-testid="stMetric"]{background:#FFFFFF;border:1px solid #E7E4F5;border-radius:16px;padding:.95rem 1.1rem 1rem;
  box-shadow:0 6px 18px rgba(43,32,120,.05);position:relative;}
[class*="st-key-kpi_"] [data-testid="stMetric"]{padding-right:3.6rem;}
[class*="st-key-kpi_"] [data-testid="stMetric"]::before{content:"";position:absolute;top:.85rem;right:.9rem;width:36px;height:36px;
  background-size:contain;background-repeat:no-repeat;}
[data-testid="stMetricLabel"] p{font-size:.84rem !important;font-weight:500 !important;color:#6B7090 !important;}
[data-testid="stMetricValue"]{font-size:1.65rem !important;font-weight:700 !important;color:#1B1F3B;line-height:1.25;}
[data-testid="stMetricDelta"]{font-size:.8rem;}

/* clickable KPI cards (app.drill_card): an invisible full-card button over the metric, with a short visible
   cue in the bottom-right corner. Its label (with the count) is kept for screen readers only. */
[class*="st-key-kpi_"]:has([class*="st-key-drill_"]){position:relative;}
[class*="st-key-drill_"]{position:absolute !important;inset:0;z-index:1;width:auto !important;margin:0 !important;}
[class*="st-key-drill_"] .stButton, [class*="st-key-drill_"] .stButton > div{width:100%;height:100%;}
[class*="st-key-drill_"] button{width:100%;height:100%;min-height:0;background:transparent !important;border:none;
  box-shadow:none !important;border-radius:16px;padding:0 1rem .9rem 0;display:flex;align-items:flex-end;
  justify-content:flex-end;cursor:pointer;color:#5B3DF5;}
[class*="st-key-drill_"] button > div{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);
  clip-path:inset(50%);white-space:nowrap;}
[class*="st-key-drill_"] button::after{font-size:.8rem;font-weight:600;color:#5B3DF5;line-height:1.2;
  padding:.18rem .55rem;border-radius:999px;background:#F1EDFF;white-space:nowrap;}
[class*="st-key-drill_"] button:focus-visible{outline:none;}
[class*="st-key-kpi_"]:has([class*="st-key-drill_"]) [data-testid="stMetric"]{
  transition:border-color .15s ease, box-shadow .15s ease, transform .08s ease;}
[class*="st-key-kpi_"]:has([class*="st-key-drill_"] button:hover) [data-testid="stMetric"]{
  border-color:#B9A8FF;box-shadow:0 10px 24px rgba(91,61,245,.14);}
[class*="st-key-kpi_"]:has([class*="st-key-drill_"] button:focus-visible) [data-testid="stMetric"]{
  outline:3px solid #7C5CFF;outline-offset:2px;}
[class*="st-key-kpi_"]:has([class*="st-key-drill_"] button:active) [data-testid="stMetric"]{
  transform:translateY(1px);background:#F7F5FF;}
[class*="st-key-kpi_"]:has([class*="st-key-drill_on_"]) [data-testid="stMetric"]{
  border-color:#7C5CFF;box-shadow:0 0 0 1px #7C5CFF, 0 6px 18px rgba(91,61,245,.12);background:#F5F2FF;}
[class*="st-key-drill_on_"] button::after{background:#5B3DF5;color:#FFFFFF;}
[class*="st-key-kpi_"]:has([class*="st-key-drill_"]) [data-testid="stMetricLabel"] [data-testid="stTooltipHoverTarget"]{
  position:relative;z-index:2;}
[data-testid="stExpander"] details{background:#FFFFFF;border-radius:14px;}
[data-testid="stForm"]{background:#FFFFFF;border-radius:16px;}

/* purchase order progress */
.ms-steps{display:flex;align-items:flex-start;margin:.4rem 0 1.2rem;}
.ms-step{flex:1;display:flex;flex-direction:column;align-items:center;position:relative;text-align:center;}
.ms-step::before{content:"";position:absolute;top:13px;left:-50%;width:100%;height:3px;background:#E7E4F5;z-index:0;}
.ms-step:first-child::before{display:none;}
.ms-step.done::before,.ms-step.now::before{background:#6D4AFF;}
.ms-step i{width:28px;height:28px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-style:normal;
  font-size:.8rem;font-weight:700;background:#FFFFFF;border:2px solid #D9D5EE;color:#9A9EB8;position:relative;z-index:1;}
.ms-step.done i{background:#6D4AFF;border-color:#6D4AFF;color:#fff;}
.ms-step.now i{border-color:#6D4AFF;color:#6D4AFF;box-shadow:0 0 0 5px #EEEAFF;}
.ms-step span{font-size:.8rem;color:#9A9EB8;margin-top:.45rem;line-height:1.25;}
.ms-step.done span{color:#4A4F6A;}
.ms-step.now span{color:#1B1F3B;font-weight:650;}
/* confirmation dialog: the destructive Confirm button is red; the safe one stays violet */
.st-key-confirm_danger button{background:#C2413A !important;border-color:#C2413A !important;color:#fff !important;}
.st-key-confirm_danger button:hover{background:#A8342E !important;border-color:#A8342E !important;}
.st-key-confirm_danger button:disabled{background:#E9B7B3 !important;border-color:#E9B7B3 !important;}
.ms-cancel{display:inline-block;background:#FDECEB;color:#C2413A;border-radius:999px;padding:.25rem .8rem;font-weight:600;font-size:.85rem;}
"""


# Solid medical icons for big feature tiles (64x64). White shapes on the violet gradient; {p} is the
# violet used for details cut into the white (crosses, keys, hands). Drawn for MedStock.
SOLID = {
    "clipboard": '<rect x="13" y="12" width="38" height="46" rx="7" fill="#fff"/>'
                 '<rect x="23" y="6" width="18" height="11" rx="3.5" fill="#fff" opacity=".6"/>'
                 '<rect x="29" y="20" width="6" height="17" rx="1.6" fill="{p}"/><rect x="23.5" y="25.5" width="17" height="6" rx="1.6" fill="{p}"/>'
                 '<rect x="21" y="43" width="22" height="3.4" rx="1.7" fill="{p}" opacity=".35"/>'
                 '<rect x="21" y="49.5" width="14" height="3.4" rx="1.7" fill="{p}" opacity=".35"/>',
    "truck": '<rect x="4" y="16" width="35" height="27" rx="5" fill="#fff"/>'
             '<path d="M39 23h10.5a3 3 0 0 1 2.3 1.1l7.2 8.6a3 3 0 0 1 .7 1.9V41a2 2 0 0 1-2 2H39Z" fill="#fff" opacity=".6"/>'
             '<path d="M43 27h6l5 6H43Z" fill="{p}" opacity=".45"/>'
             '<rect x="19" y="21.5" width="5.5" height="16" rx="1.5" fill="{p}"/><rect x="13.75" y="26.75" width="16" height="5.5" rx="1.5" fill="{p}"/>'
             '<circle cx="16" cy="46" r="7" fill="#fff"/><circle cx="16" cy="46" r="2.6" fill="{p}"/>'
             '<circle cx="49" cy="46" r="7" fill="#fff"/><circle cx="49" cy="46" r="2.6" fill="{p}"/>',
    "bottle": '<rect x="15" y="6" width="24" height="9" rx="2.5" fill="#fff" opacity=".6"/>'
              '<rect x="11" y="15" width="32" height="43" rx="7" fill="#fff"/>'
              '<rect x="24" y="25" width="6" height="18" rx="1.6" fill="{p}"/><rect x="18" y="31" width="18" height="6" rx="1.6" fill="{p}"/>'
              '<circle cx="46" cy="45" r="15" fill="{p}"/><circle cx="46" cy="45" r="11.5" fill="#fff"/>'
              '<path d="M46 38.5V45l4.5 3" fill="none" stroke="{p}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>',
    "beacon": '<rect x="11" y="48" width="42" height="9" rx="3.5" fill="#fff" opacity=".6"/>'
              '<path d="M17 48V35a15 15 0 0 1 30 0v13Z" fill="#fff"/>'
              '<rect x="29.25" y="29" width="5.5" height="15" rx="1.5" fill="{p}"/><rect x="24.5" y="33.75" width="15" height="5.5" rx="1.5" fill="{p}"/>'
              '<g stroke="#fff" stroke-width="3.6" stroke-linecap="round"><path d="M32 5v7"/><path d="M12.5 12.5l5 5"/>'
              '<path d="M51.5 12.5l-5 5"/><path d="M4 30h7"/><path d="M53 30h7"/></g>',
    "heart": '<path d="M32 56 9.5 34.2A13.5 13.5 0 0 1 32 15.6a13.5 13.5 0 0 1 22.5 18.6Z" fill="#fff"/>'
             '<path d="M14 35h9l3.5-6 5 13 4.5-10 2.5 3H50" fill="none" stroke="{p}" stroke-width="3.4" '
             'stroke-linecap="round" stroke-linejoin="round"/>',
    "calculator": '<rect x="13" y="5" width="38" height="54" rx="8" fill="#fff"/>'
                  '<rect x="19" y="11" width="26" height="12" rx="3" fill="{p}" opacity=".35"/>'
                  '<g fill="{p}" opacity=".6"><rect x="19" y="29" width="7" height="6" rx="2"/><rect x="28.5" y="29" width="7" height="6" rx="2"/>'
                  '<rect x="19" y="38.5" width="7" height="6" rx="2"/><rect x="28.5" y="38.5" width="7" height="6" rx="2"/>'
                  '<rect x="19" y="48" width="7" height="6" rx="2"/><rect x="28.5" y="48" width="7" height="6" rx="2"/></g>'
                  '<rect x="38" y="29" width="7" height="25" rx="2" fill="{p}"/>',
}


def solid_uri(name, accent="#6A4BFA"):
    return data_uri(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">{SOLID[name].format(p=accent)}</svg>')


def section(title, question, icon_name, color):
    """A section header with an icon tile: title on top, the question it answers below in gray."""
    return (f'<div class="ms-sh"><img src="{tile_uri(icon_name, color)}" alt=""><div><b>{title}</b>'
            f'<span>{question}</span></div></div>')


# ---------------------------------------------------------------------------
# Status labels: one wording, color and icon for each state, used on every page.
# The planning code still produces labels such as "🔴 Order now"; these helpers only change how they
# are shown, never how they are calculated.
# ---------------------------------------------------------------------------
STATUS = {                        # label: (badge color, Material icon)
    "No usable stock": ("red", "block"),
    "Shortage risk": ("red", "error"),
    "Order now": ("red", "shopping_cart"),
    "Shortage watch": ("orange", "visibility"),
    "Order soon": ("orange", "schedule"),
    "Enough stock": ("green", "check_circle"),
    "OK": ("green", "check_circle"),
    "Expired": ("red", "event_busy"),
    "Expiring soon": ("orange", "hourglass_bottom"),
    "Active": ("red", "error"),
    "Planned": ("orange", "schedule"),
    "Ended": ("gray", "check_circle"),
    "Late": ("red", "schedule"),
}
# Primary status on the Inventory page: the more urgent of an item's two statuses, in this order.
PRIMARY_ORDER = ["No usable stock", "Shortage risk", "Order now", "Shortage watch", "Order soon", "OK"]
BADGE_CSS = {"red": ("#FDECEB", "#B42318"), "orange": ("#FDF3E1", "#8A5300"), "green": ("#E3F6F3", "#0B6B5F"),
             "gray": ("#EFF0F5", "#4A4F6A"), "violet": ("#EEEAFF", "#5B3DF5"), "blue": ("#E6EFFE", "#1D4FBF")}


def plain_status(label):
    """'🔴 Shortage risk' -> 'Shortage risk' (text only; no meaning carried by color or emoji)."""
    text = str(label).strip()
    return text.split(" ", 1)[1] if text[:1] in "🔴🟡🟢⚪" and " " in text else text


def primary_status(reorder_status, availability):
    """The single status shown first for an item: the more urgent of reorder status and availability."""
    found = [plain_status(reorder_status), plain_status(availability).replace("Enough stock", "OK")]
    return min(found, key=lambda s: PRIMARY_ORDER.index(s) if s in PRIMARY_ORDER else len(PRIMARY_ORDER))


def badge_md(label):
    """A compact status badge for st.markdown: icon + text on a tinted background."""
    text = plain_status(label)
    color, icon = STATUS.get(text, ("gray", "info"))
    return f":{color}-badge[:material/{icon}: {text}]"


def status_style(label):
    """Cell style for a status in a table (pandas Styler): tinted background, dark text, label kept."""
    color = STATUS.get(plain_status(label), ("gray", ""))[0]
    bg, fg = BADGE_CSS[color]
    return f"background-color:{bg};color:{fg};font-weight:600"


# ---------------------------------------------------------------------------
# Display formatting. Values keep full precision in calculations and storage; these only format them.
# ---------------------------------------------------------------------------
MISSING = "—"


def _missing(x):
    try:
        return x is None or x != x                      # None or NaN
    except (TypeError, ValueError):
        return False


def fmt_int(x):
    """Whole units: 1,234."""
    return MISSING if _missing(x) else f"{round(float(x)):,}"


def fmt_num(x, digits=1):
    """A measured quantity such as days or units per day: 3.2."""
    return MISSING if _missing(x) else f"{float(x):,.{digits}f}"


def fmt_pct(x, digits=1, signed=False):
    """A share (0.153) as a percentage: 15.3% (or +15.3% when signed)."""
    return MISSING if _missing(x) else f"{float(x):{'+' if signed else ''}.{digits}%}"


def fmt_money(x, cents=False):
    """US dollars: $12,345, or $12,345.67 when cents matter."""
    if _missing(x):
        return MISSING
    v = float(x)
    return ("-" if v < 0 else "") + (f"${abs(v):,.2f}" if cents else f"${abs(v):,.0f}")


def fmt_date(d):
    """Nov 4, 2026."""
    if _missing(d):
        return MISSING
    import pandas as pd
    t = pd.Timestamp(d)
    return f"{t:%b} {t.day}, {t.year}"


def expiry_phrase(days_left):
    """Days until expiry in words: 'Expired 9 days ago', 'Expires today', 'Expires in 12 days'."""
    if _missing(days_left):
        return MISSING
    d = int(days_left)
    if d < 0:
        return f"Expired {-d} day{'s' if d != -1 else ''} ago"
    if d == 0:
        return "Expires today"
    return f"Expires in {d} day{'s' if d != 1 else ''}"


def md_safe(text):
    """Escape dollar signs for st.markdown / st.caption / st.success, which would otherwise read the text
    between two amounts ("$1,200 to $900") as a math formula."""
    return str(text).replace("\\$", "$").replace("$", "\\$")


def badge_text(count):
    """The number on the notification badge: '' when there is nothing, '99+' above 99."""
    count = int(count or 0)
    return "" if count <= 0 else "99+" if count > 99 else str(count)


def notifications_label(count):
    """What a screen reader hears for the notification bell: the exact number, even above 99 where the
    visual badge (badge_text) stops at "99+"."""
    count = int(count or 0)
    return "Open notifications, none active" if count <= 0 else f"Open notifications, {count} active"


def bell_css(count):
    """The bell button: a line icon in a white tile, plus a red count badge only when count > 0. The button
    text (notifications_label) stays available to screen readers but is visually hidden."""
    css = (".st-key-bell_btn button{width:40px;height:40px;min-height:40px;padding:0;border-radius:12px;"
           "background:#FFFFFF;border:1px solid #E7E4F5;position:relative;overflow:visible;}"
           ".st-key-bell_btn button:hover{background:#F3F1FC;border-color:#D9D3F5;}"
           ".st-key-bell_btn button:focus-visible{outline:2px solid #6D4AFF;outline-offset:2px;}"
           ".st-key-bell_btn button p{position:absolute !important;width:1px;height:1px;margin:-1px;padding:0;"
           "overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0;}"
           f'.st-key-bell_btn button::before{{content:"";width:22px;height:22px;flex:none;background:url("{icon_uri("bell", COLORS["navy"], 2)}") '
           "center/contain no-repeat;}"
           ".st-key-menu_top{justify-content:space-between;align-items:center;padding-right:.2rem;}")
    text = badge_text(count)
    if text:
        css += (f'.st-key-bell_btn button::after{{content:"{text}";position:absolute;top:-7px;right:-7px;'
                "min-width:20px;height:20px;padding:0 5px;border-radius:999px;background:#D93B32;color:#FFFFFF;"
                "font-size:.7rem;font-weight:700;line-height:16px;text-align:center;border:2px solid #FFFFFF;"
                "box-sizing:border-box;}")
    return css
