# MedStock: hospital supply inventory planner

A portfolio project that turns the Inventory Management and Forecasting lessons of my Supply
Chain Management course (University of Portland) into a working web app for a US hospital
supply room (all amounts in USD), then extends them with my own research into how real
hospital supply systems work.

**What comes from where:** the formulas and models (EOQ, safety stock, reorder point, fill rate,
ABC, newsvendor, forecasting methods) come from the course lessons; slide numbers below refer to
the course deck. Everything listed under *Personal research and extensions* is my own work
beyond the course.

## Portfolio homepage

New sessions open a public project overview (`homepage.py`) explaining the inventory
problems, capabilities, workflow, technology, and limitations. **Explore the inventory
demo** opens the application; **Back to project home** returns to the overview.
The homepage does not open the database. Demo actions still update the saved local data.

## Sign-in

The homepage is public; the demo requires sign-in (`auth.py`). Accounts are kept in
`.streamlit/secrets.toml`, which is private and listed in `.gitignore`. Only a salted
PBKDF2 hash of each password is stored. To add an account:

```bash
.venv/bin/python auth.py add <username>   # asks for the password, prints the line to paste
```

On Streamlit Community Cloud, paste the `[auth.users]` section into the app's **Secrets** settings.
This is a simple access gate for a demo, not hospital-grade security (no roles or audit by user).
AI integration is not implemented yet.

Homepage navigation and database-free rendering are covered by `test_homepage.py`.
App tests explicitly use temporary databases and clear Streamlit caches between tests.

## Documentation

- [User Guide](docs/USER_GUIDE.md): how to use the app day to day (also in the app's 📖 Help tab)
- [How It Works](docs/HOW_IT_WORKS.md): formulas, slide references, data model, design decisions

## Run it

```bash
cd "Inventory Managment"
.venv/bin/streamlit run app.py          # opens http://localhost:8501
.venv/bin/python -m pytest -v           # check formulas against slide examples
.venv/bin/python generate_sample_data.py   # regenerate the sample data
```

First time on a new computer:
`python3.13 -m venv .venv && .venv/bin/pip install -r requirements.txt`

## Files

| File | What it does |
|---|---|
| `inventory_math.py` | All formulas: EOQ, safety stock, ROP, loss function, fill rate, newsvendor, ABC |
| `test_inventory_math.py` | Checks the formulas against the professor's worked examples |
| `db.py` | SQLite database (`data/medstock.db`): lots with expiry, FEFO issue, receive, purchase orders, write-off, cycle count, ledger, lot trace |
| `test_db.py` | Checks the stock movement rules (no over-issuing, lead time recorded, ...) |
| `forecasting.py` | Moving average, exponential smoothing, Holt, Winters; backtest with MAD/MSE/MAPE/bias |
| `test_forecasting.py` | Checks the forecasting methods against the professor's examples (slides 272-306) |
| `planning.py` | Measures demand and lead time from history and builds the reorder plan |
| `purchasing.py` | Vendor purchase orders (one per vendor, many lines), simulated vendor responses, scorecard |
| `simulation.py` | The simulation clock: daily demand, deliveries, automatic reordering |
| `test_purchasing.py` | Checks the purchase order lifecycle and the simulation |
| `events.py` | Lot recalls and vendor disruptions, with automatic switch to backup vendors |
| `kpis.py` | KPIs: fill rate, stockouts, inventory turns, days on hand, waste, vendor reliability, weekly trends |
| `test_events.py` | Checks recalls, disruptions, backup vendors and the KPI arithmetic |
| `auth.py` / `homepage.py` | Sign-in gate and public portfolio homepage (`test_homepage.py`) |
| `app.py` | The Streamlit web app (dashboard, KPIs, purchasing, stock movements, recalls & disruptions, forecast, expiry, item detail, ABC-VED, calculators) |
| `generate_sample_data.py` | Creates fake but realistic hospital data in `data/` |

## From the course: lecture → app mapping

| Lecture topic | Where in the app |
|---|---|
| EOQ, total cost, sensitivity (183-190) | Item detail: order quantity and cost curve |
| Forecasting (259-306) | 📈 Forecast tab: Auto picks the lowest-MAD method per item; the forecast drives d̄, D and σd |
| Uncertain demand and lead time (197-204) | Safety stock and reorder point for every item |
| Fill rate, loss function (205-211) | Fill rate metric per item |
| ABC (213-215) | ABC-VED tab |
| Newsvendor (217-231) | Calculators tab (platelets, flu vaccine, winter-storm stock-up) |
| Overage cost Co (221-224) | ⏳ Expiry tab: projected waste from short-dated lots |

## Personal research and extensions (beyond the course)

| Extension | Where in the app |
|---|---|
| VED criticality, service level by criticality, ABC-VED control matrix | Sidebar, ABC-VED tab |
| Order quantities capped by shelf life | Reorder plan |
| Lots with expiry, FEFO picking, expiry-waste projection, 90-day availability risk | Dashboard, ⏳ Expiry |
| Forecast method backtesting and automatic selection per item | 📈 Forecast |
| Vendor purchase orders: draft, approval, acknowledgement, ship notice, receiving (modeled on EDI 850/855/856), vendor scorecard | 🛒 Purchasing |
| Simulation clock with random demand, vendor lead times and backorders | Sidebar |
| Lot recalls, vendor disruptions, backup vendors | 🚨 Recalls & disruptions |
| KPIs and weekly trends | 📊 KPIs |
| Portfolio homepage and sign-in | Homepage |

## Data

Your stock movements are saved in `data/medstock.db`. It is created automatically from the
CSV files the first time the app runs. **To start over with fresh sample data**, use the sidebar:
Simulation settings → 🔄 Reset to fresh sample data.
