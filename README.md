# MedStock: hospital supply inventory planner

MedStock is a web app for running the supply room of a (fictional) US hospital. I built it to put
the Inventory Management and Forecasting units of my Supply Chain Management course at the
University of Portland into practice, then kept going to learn how real hospital supply systems
handle purchasing, expiry, recalls and vendor problems.

It tracks 150 medical supplies in six categories from four fictional vendors. For each item it works out when to
reorder and how much, and a simulation clock lets you run the hospital forward day by day to see
whether those decisions hold up. All data is synthetic and all amounts are in USD.

## What it does

- **Reorder planning.** Reorder point, safety stock and order quantity for every item, with a daily
  list of what to order now and what to order soon.
- **Forecasting.** Four forecasting methods are tested on past usage, and each item uses the one
  that would have been most accurate.
- **Lots and expiry.** Stock is issued earliest-expiry first, and the app warns about lots that will
  expire before they can be used.
- **Purchasing.** Suggested orders are grouped into one purchase order per vendor. After approval,
  the simulated vendor confirms, ships, sometimes runs late and sometimes comes up short.
- **Recalls and vendor outages.** Recall a lot and it's pulled from the shelf and refused at the dock.
  Take a vendor offline and new orders go to each item's backup vendor at a higher price.
- **KPIs.** Fill rate, stockouts, inventory turns, days on hand, waste and on-time delivery, with
  weekly trends.
- **Ask MedStock (AI).** An assistant that answers questions with the app's own numbers. It looks
  things up through read-only tools, so it can explain and advise but cannot change anything. Every
  answer is logged with its provider, model, tokens and estimated cost and checked for figures that
  did not come from the data. It runs on Google Gemini by default (free tier), with Anthropic Claude as
  an option; the free tier is only for this fictional data.
- **Sign-in.** The homepage is public. The demo itself is invite-only.

## What came from class and what I added

The formulas come from the course. Slide numbers refer to the course deck.

| From the course | Where it shows up |
|---|---|
| EOQ, total cost, sensitivity (slides 183-190) | Item detail: order quantity and cost curve |
| Uncertain demand and lead time (197-204) | Safety stock and reorder point for every item |
| Fill rate and loss function (205-211) | Fill rate per item |
| ABC classification (213-215) | ABC-VED page |
| Newsvendor model (217-231) | Calculators page (platelets, flu vaccine, winter-storm stock-up) |
| Overage cost (221-224) | Expiry tab: projected waste from short-dated lots |
| Forecasting methods and error measures (259-306) | Forecast page |

Everything below is my own research and design, beyond the course.

| My additions | Where it shows up |
|---|---|
| VED criticality, service level by criticality, ABC-VED control matrix | Sidebar, ABC-VED page |
| Order quantities capped by shelf life | Reorder plan |
| Lots, earliest-expiry-first picking, multi-lot deliveries, expiry waste projection, 90-day shortage risk | Dashboard, Expiry page |
| Forecast backtesting with automatic method choice per item | Forecast page |
| Purchase order workflow modeled on EDI 850/855/856, vendor scorecard | Purchasing page |
| Simulation clock with random demand, lead times and backorders | Sidebar |
| Lot recalls, vendor outages, backup vendors | Recalls & disruptions page |
| KPI page with weekly trends | KPIs page |
| Portfolio homepage and sign-in | Homepage |
| AI assistant with read-only tools, a provider adapter (Gemini or Claude), audit log, usage caps and a check for made-up figures | Ask MedStock page |

## Running it locally

You need Python 3.13.

```bash
git clone https://github.com/Wendylj-Bai/medstock.git
cd medstock
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run app.py        # opens http://localhost:8501
```

The first run builds the database (`data/medstock.db`) from the sample CSV files. To start over,
use **Simulation settings > Reset to fresh sample data** in the sidebar.

**Sign-in accounts** live in `.streamlit/secrets.toml`, which is never committed. Only a salted
PBKDF2 hash of each password is stored. To add an account, run `.venv/bin/python auth.py add <username>`
and paste the line it prints into that file. On Streamlit Community Cloud, paste the same
`[auth.users]` section into the app's Secrets settings. This is a simple gate for a demo, with no
user roles or per-user audit trail.

**Ask MedStock** needs `GEMINI_API_KEY = "your-key-here"` at the top of `.streamlit/secrets.toml`
(on Streamlit Community Cloud: Manage app > Settings > Secrets). The rest of the app works without
it. Provider, model and limits are optional settings described in [AI Design](docs/AI_DESIGN.md).

**Tests:** `.venv/bin/python -m pytest`. The formula tests use the worked examples from the course
as expected values, and every test runs on a temporary database.

## Documentation

- [User Guide](docs/USER_GUIDE.md): how to use the app day to day (also in the app's Help page)
- [How It Works](docs/HOW_IT_WORKS.md): formulas, data model and design decisions
- [Build Log](docs/BUILD_LOG.md): how the project was built, what broke and what I changed
- [AI Design](docs/AI_DESIGN.md): how AI agents are added, with guardrails and an evaluation plan
- [AGENTS.md](AGENTS.md): guide for collaborators and AI coding assistants (architecture, rules, roadmap)

## Files

| File | What it does |
|---|---|
| `inventory_math.py` | The formulas: EOQ, safety stock, reorder point, loss function, fill rate, newsvendor, ABC |
| `forecasting.py` | Moving average, exponential smoothing, Holt, Winters, and backtesting |
| `planning.py` | Turns usage and delivery history into the reorder plan |
| `db.py` | SQLite storage and the rules for every stock movement |
| `purchasing.py` | Purchase orders and the simulated vendors |
| `simulation.py` | The simulation clock |
| `events.py` | Recalls, vendor outages and backup vendors |
| `kpis.py` | KPI calculations and weekly trends |
| `auth.py`, `homepage.py` | Sign-in and the public homepage |
| `app.py` | The Streamlit interface |
| `generate_sample_data.py` | Creates the synthetic hospital data in `data/` |
| `test_*.py` | Automated tests |

## Scope

This is a learning project. The hospital, its usage history and the vendors are made up, and it
isn't clinical software.

## What's next

MedStock is still growing. Planned next steps:

- Comparing two inventory policies side by side over the same simulated period
- Ward supply rooms with par levels, on top of the central storeroom
- AI agents beyond Ask MedStock: a buyer agent that proposes orders for approval, a disruption
  responder and a policy analyst (see [docs/AI_DESIGN.md](docs/AI_DESIGN.md))
