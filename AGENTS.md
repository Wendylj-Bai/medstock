# Guide for AI assistants and collaborators

Read this before changing anything. It covers what the project is, how the code fits together,
the rules that keep it working, and what is planned next. For the formulas, see
[docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md). For how a user works the app, see
[docs/USER_GUIDE.md](docs/USER_GUIDE.md).

## 1. The project in short

MedStock is a Streamlit web app that runs the supply room of a fictional US hospital: 150 items,
four fictional vendors, all amounts in USD. It started as a way to apply the Inventory Management
and Forecasting units of a Supply Chain Management course (University of Portland), then grew into
a fuller system through the owner's own research.

- **Owner:** a master's student. Comfortable reading Python but not a full-time developer. Explain
  changes in plain language, and say what you changed and why.
- **Purpose:** a public portfolio piece and a learning tool. It is not clinical software.
- **Status:** working and live, and still evolving. Nothing is "final".
- **Live app:** Streamlit Community Cloud, deployed from `main` of
  https://github.com/Wendylj-Bai/medstock. **Every push to `main` redeploys the live app.**

## 2. Before you start: working rules

1. **One assistant at a time.** Two assistants once edited this project at the same time, and a
   test run wiped the owner's real data. If someone else may have been working, run `git status` and
   `git log` first, and read any file before editing it.
2. **Back up the real database before risky work.** Copy `data/medstock.db` somewhere safe first.
   It holds the owner's simulated history and is not in git.
3. **Tests must never open the real database.** `conftest.py` makes any test that tries fail. Use
   `tmp_path`. Never weaken or remove that guard.
4. **Never commit `.streamlit/secrets.toml`** and never write the sign-in username or password in
   code, docs, commits or the homepage. Credentials are shared privately by the owner.
5. **Ask before pushing to `main`**, since it changes the live site. Commit only when asked.
6. **Keep vendors and data fictional**, and keep the "synthetic data" disclosure on the homepage.
7. **Credit honestly.** The formulas come from the course. Everything else is the owner's own
   extension. The homepage and README both have a section on this, so keep it accurate when adding
   features.
8. **Run the full test suite before you say a change is done**, and report failures as they are.
9. **Add an entry to [docs/BUILD_LOG.md](docs/BUILD_LOG.md)** for each feature or notable fix:
   what was built, what went wrong, and the decision. Keep it short and in the owner's first-person voice.

## 3. Run, test, deploy

```bash
python3.13 -m venv .venv && .venv/bin/pip install -r requirements.txt   # first time only
.venv/bin/streamlit run app.py          # http://localhost:8501
.venv/bin/python -m pytest -q           # 77 tests, about 100 seconds
.venv/bin/python auth.py add <name>     # create a sign-in account (prints a line for secrets.toml)
```

- **Python 3.13**, Streamlit 1.66, pandas 3.x, SQLite in WAL mode. Exact versions are pinned in
  `requirements.txt`.
- **Local:** if no database exists, the app builds `data/medstock.db` from the CSVs in `data/`.
- **Streamlit Cloud:** the same thing happens there. Its file system is temporary, so the live
  database resets to sample data whenever the app restarts. Sign-in accounts are pasted into the
  app's Secrets settings on Streamlit Cloud.
- **After a schema change, restart the local server.** The connection is cached with
  `st.cache_resource`, and migrations only run when a connection opens.

## 4. How the code fits together

```
data/*.csv ──► db.py (SQLite, stock rules, clock) ◄── every action in app.py
                  │
                  ├─► planning.py + inventory_math.py + forecasting.py ──► reorder plan (one row per item)
                  ├─► purchasing.py (POs, simulated vendors, backup vendors)
                  ├─► events.py (recalls, vendor outages)
                  └─► kpis.py (KPIs rebuilt from the ledger)
simulation.py moves the clock: vendor news ► receive ► daily demand ► auto-reorder
app.py draws the screens; homepage.py and auth.py gate them
```

| File | Responsibility | Key functions |
|---|---|---|
| `inventory_math.py` | Pure formulas, no data access | EOQ, z, σ_DDLT, safety stock, ROP, loss function, fill rate, newsvendor, ABC |
| `forecasting.py` | MA, exponential smoothing, Holt, Winters, backtesting | `forecast_all` |
| `planning.py` | One decision row per item | `build_plan`, `availability_risks`, `project_expiry` |
| `db.py` | Storage, clock, every stock movement | `connect`, `today`/`set_today`, `issue`, `fulfill_request`, `receive`, `write_off`, `cycle_count`, `lot_trace`, `atomic` |
| `purchasing.py` | Vendor master, PO lifecycle, vendor behavior | `create_order`, `send_order`, `receive_order`, `draft_suggested_orders`, `process_vendor_responses`, `order_vendors`, `stage` |
| `events.py` | Recalls and vendor outages | `recall_lot`, `random_recall`, `start_outage`, `end_outage`, `random_outage` |
| `kpis.py` | KPIs and weekly trends | `compute`, `weekly`, `inventory_value_by_day` |
| `simulation.py` | The clock | `advance` |
| `auth.py` | Sign-in with salted PBKDF2 hashes from Streamlit secrets | `render_login`, `verify`, `hash_password` |
| `homepage.py` | Public portfolio page (no database access) | `render_homepage` |
| `app.py` | All screens: 12 pages plus the sidebar | |
| `ui.py` | Palette, icon set (Lucide-style line icons and solid feature icons), sidebar menu and card CSS | `PAGES`, `nav_css`, `kpi_css`, `tile_uri`, `solid_uri` |

**Pages** are listed once, in `ui.PAGES` (title, icon, color). The sidebar menu is built from it
and only the open page is drawn: each page is an `if PAGE == "...":` block in `app.py`, so a page
must never rely on a variable created inside another page's block
(`test_every_sidebar_page_opens_without_errors` checks this). Tests open a page with
`open_page(at, "Forecast")` in `test_app.py`.

**Page flow in `app.py`:** `view` in session state is `home`, `login` or `demo`. The demo only
renders when `st.session_state["user"]` is set. Each page load: connect, close vendor-rejected
orders, load data, build the plan (cached forecast), then draw the open page. Actions call `done(msg)`,
which stores a toast and reruns the page.

## 5. Data model (SQLite, `data/medstock.db`)

| Table | Holds |
|---|---|
| `items` | Item master: cost, VED, shelf life, `supplier` (primary), `backup_supplier` |
| `lots` | The stock itself: one row per batch with lot number, expiry and quantity left |
| `asn_lots` | The lots a vendor's ship notice announced for each PO line (one line can be several lots) |
| `usage` | Daily demand history, **including unmet demand**, so forecasts see true demand |
| `deliveries` | Completed receipts with the real lead time (feeds σL) |
| `po_headers` | One purchase order per vendor, with the dates of the vendor's response and `vendor_note` |
| `purchase_orders` | PO lines: DRAFT, OPEN, RECEIVED or CANCELLED, with confirmed qty and ASN lot/expiry |
| `transactions` / `transaction_lots` | The ledger. Every movement and which lots it touched. Never deleted |
| `demand_requests` | Ward requests: requested, filled, short (idempotent by `request_id`) |
| `stockouts` | Demand that could not be filled |
| `cycle_counts` | Physical counts vs. system quantity |
| `recalls` / `vendor_outages` | Supply risk events |
| `settings` | The simulation clock (`today`) |

New columns are added in `db._migrate`, which runs on every connect. Existing databases must keep
working, so add columns with `ALTER TABLE` there and never assume a fresh database.

## 6. Rules the code depends on (invariants)

- **On hand is never stored.** It is always `SUM(lots.qty)`. Change stock only through `db.py`
  functions, inside `db.atomic(conn)`, and always write a ledger row with `db._ledger`.
- **FEFO:** issues take the earliest-expiring usable lot first and never pick an expired lot.
- **Write-offs and recalls are losses, not demand.** They must never go into `usage`. Unmet demand
  *does* go into `usage` (and `stockouts`).
- **The clock:** "today" is `db.today(conn)`, not `date.today()`. Movements cannot be dated in the
  future or before an item's latest movement.
- **On order** counts only sent lines (not drafts). After the vendor acknowledges, the confirmed
  quantity is used, minus what has been received.
- **Vendor behavior is decided when a PO is sent**, from a random generator seeded by the PO number
  (`purchasing._rng`), and revealed day by day as the clock passes each date. Reloading the page
  must never change an order's story.
- **Vendor outage:** an order acknowledged during an outage has every line confirmed as 0 and a
  `vendor_note`. `process_vendor_responses` cancels it on the acknowledgement date. While the
  primary vendor is down, new orders go to `backup_supplier` at `BACKUP_PREMIUM` (12%) more.
- **Recalled lots** are pulled from the shelf and can never be received again.
- **Service levels** default to Vital 99%, Essential 95%, Desirable 90% (`planning.DEFAULT_SERVICE_LEVELS`).

## 7. Conventions

**Writing (UI text, docs, commit messages):** the owner dislikes text that sounds AI-written.
- No em dashes (—), en dashes (–) or arrows (→) in prose. Use periods, commas, colons or "to". For
  menu paths use ">" (for example "History > Lot trace"). Show empty cells as "n/a".
- No slogan taglines, "not just X but Y", or words like seamless, robust, leverage, delve.
- Plain, concrete sentences. The portfolio text (homepage, README) is first person.
- Use proper plurals with the `n(count, word)` helper in `app.py`, never "item(s)".
- The visual stage bar in Purchasing keeps its arrows because it is a graphic, not prose.

**Code:**
- Keep the existing style: plain functions, pandas DataFrames, SQL in the module that owns the table.
- Raise `db.StockError` with a clear, user-facing message for anything the user did wrong. `app.py`
  shows it as an error instead of crashing (see `run()` in `app.py`).
- Give every new widget a `key`. To change a widget's value from code, set the session state
  *before* the widget is drawn, or use an `on_click` callback.
- pandas 3: avoid chained assignment and `.where` with plain booleans. Use `day_of_week`, not `dayofweek`.

**Tests:**
- One test file per module (`test_events.py`, `test_purchasing.py` and so on). UI tests use
  Streamlit's `AppTest` with a patched `db.connect` (see the `app` fixture in `test_app.py`).
- With `AppTest` forms: set the widget value and click the submit button, then call `run()` once.
- Formula tests use the course's worked examples as expected values. Don't change those numbers to
  make a test pass.

## 8. Known limitations

- One storeroom only: no ward-level stock or par levels.
- One primary and one backup vendor per item, no substitute items.
- No invoices, case-pack rounding, contract pricing or user roles.
- Inventory KPIs start on the first day of the transaction ledger. The sample history before that
  has usage but no stock movements.
- On Streamlit Cloud, all visitors share one database, and it resets when the app restarts.

## 9. Roadmap

In no fixed order, except that AI comes last:

1. ~~Multi-lot receiving~~: done (November 3, 2026).
2. **Scenario comparison:** run the same period with two policies (for example 95% vs 99% Vital
   service level) and compare the KPIs side by side.
3. **Multiple locations:** central storeroom plus ward supply rooms with par levels and transfers.
4. **Plain-language rewrite** of `docs/USER_GUIDE.md` and `docs/HOW_IT_WORKS.md` (the homepage and
   README are done).
5. **Automatic reset of the live demo data**, so visitors start clean.
6. **AI integration** (last phase, not started). Any AI feature should explain its reasoning with
   the app's own numbers and must not change stock without the user's approval.

## 10. Decision log

| Decision | Why |
|---|---|
| Streamlit + SQLite, one process | Simple to run and deploy for a portfolio. No server to manage |
| Continuous-review (Q, R) policy | It is the model taught in the course |
| Unmet demand counted in `usage` | Otherwise stockouts would make forecasts too low |
| Vendor events pre-drawn at send time | Reloads stay consistent, and the story is revealed by the clock |
| One PO per vendor, drafts need approval | Matches how hospital purchasing systems work |
| Backup vendor at +12%, used only during outages | Shows the cost of supply risk without complicating normal ordering |
| Sign-in via hashed passwords in Streamlit secrets | Keeps credentials out of the code and the public repo |
| Commits use the GitHub noreply email | Keeps the owner's personal email off the public repo |
