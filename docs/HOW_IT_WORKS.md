# How MedStock Works

Technical documentation: the models, the data, and the design decisions.
Slide numbers refer to the course deck *Supply Chain Management Course* (Inventory Management
pp. 175-232, Forecasting pp. 259-306). For day-to-day use, see the [User Guide](USER_GUIDE.md).

**Course vs. extensions.** Sections and formulas with slide numbers come from the course lessons.
Everything else (VED and criticality-based service levels, lots/FEFO and expiry projection,
availability risk, the purchasing workflow and vendor simulation, the simulation clock, recalls,
vendor disruptions and backup vendors, KPIs, sign-in and homepage) is the author's own research
and design beyond the course.

---

## 1. Overview

MedStock is a continuous-review **(Q, R)** inventory system for a hospital supply room. It extends the
textbook model with what a hospital needs: clinical criticality (VED), lots and expiry dates (FEFO),
and seasonal demand forecasting.

```
 usage history ──► forecasting.py ──► d̄, σd, D ─┐
                                                 ├─► planning.py ──► EOQ, SS, ROP, status, order qty
 delivery history ──► L̄, σL ────────────────────┘          │
                                                            ▼
 lots (qty, expiry) ──► usable stock, FEFO waste projection ──► app.py (Streamlit screens)
                                                            ▲
                          db.py (SQLite) ◄── every stock movement the user records
```

Every recorded movement feeds back into the models: issues become demand history, receipts become
lead-time history. The plan is recalculated on every page load.

---

## 2. Files

| File | Responsibility |
|---|---|
| `inventory_math.py` | Pure formulas: EOQ, total cost, z, σ_DDLT, safety stock, ROP, loss function, fill rate, newsvendor, ABC |
| `forecasting.py` | Moving average, exponential smoothing, Holt, Winters; accuracy measures; backtest and method selection |
| `planning.py` | Combines data and formulas into one decision row per item; expiry projection |
| `db.py` | SQLite storage, the clock, and the rules for every stock movement |
| `purchasing.py` | Vendor master, purchase orders (draft > sent > confirmed > shipped > arrived > received), vendor simulation, scorecard, printable PO |
| `simulation.py` | Moves the clock forward: daily demand, receipts, automatic reordering, random events |
| `events.py` | Lot recalls and vendor disruptions (with automatic switch to backup vendors) |
| `kpis.py` | Key performance indicators and weekly trends, rebuilt from the ledger |
| `auth.py` | Sign-in gate for the demo (salted PBKDF2 password hashes in Streamlit secrets) |
| `homepage.py` | Public portfolio homepage |
| `app.py` | Streamlit user interface |
| `generate_sample_data.py` | Creates the synthetic hospital dataset (CSV) |
| `test_*.py` | 68 automated tests; the formula tests use the professor's worked examples as expected values |

Run the tests with `.venv/bin/python -m pytest -v`.

---

## 3. Data model (`data/medstock.db`)

| Table | Contents | Notes |
|---|---|---|
| `items` | Item master: unit cost C, ordering cost S, holding rate i, VED, shelf life, supplier | |
| `lots` | Lot number, expiry date, quantity left | **On hand is always `SUM(lots.qty)`**. It is never stored separately, so it cannot drift. |
| `usage` | Date, item, quantity used | Issues are appended here (write-offs are not) |
| `deliveries` | Order date, received date, lead time | Receipts are appended here |
| `po_headers` | One PO per vendor: status, dates of each vendor event, carrier, tracking, freight | Vendor event dates are drawn when the PO is sent |
| `purchase_orders` | PO **lines**: item, qty, price, confirmed qty, ASN lot and expiry; DRAFT / OPEN / RECEIVED / CANCELLED | Open lines form the *on order* quantity; drafts do not |
| `stockouts` | Date, item, units that could not be supplied | Written by the simulation |
| `settings` | The simulated "today" | Absent = real date |
| `transactions` | The ledger: every movement with running balance | Never deleted |
| `transaction_lots` | Which lots each movement touched | Enables recall tracing |
| `cycle_counts` | System vs counted quantity per count | Record accuracy |

Every write runs inside one SQLite transaction (`with conn:`), so a movement is either fully saved or not at all.

---

## 4. The decision pipeline for one item

### Step 1: Demand (`forecasting.py`, slides 259-306)

1. Daily usage is turned into a **monthly series of average daily usage**, complete months only (a half month would look like a drop).
2. Four methods, implemented as on the slides, with error **e = F − D** (slide 270):

| Method | Equations | Slides |
|---|---|---|
| Moving average | F_t = (D_{t−1} + … + D_{t−N}) / N | 276 |
| Exponential smoothing | F_{t+1} = αD_t + (1−α)F_t | 283 |
| Holt | S_t = αD_t + (1−α)(S_{t−1}+G_{t−1}); G_t = β(S_t−S_{t−1}) + (1−β)G_{t−1}; F = S_t + τG_t | 290-292 |
| Winters | S_t = α(D_t/c_{t−N}) + (1−α)(S_{t−1}+G_{t−1}); G_t as Holt; c_t = γ(D_t/S_t) + (1−γ)c_{t−N}; F = (S_t+τG_t)c_{t+τ−N} | 300-306 |

   Winters uses the slide's convention: seasonal factors sum to 1 and S is a season-total level.
   Initial values come from the first two seasons (slide 305), so Winters needs ≥ 27 months of history.

3. **Backtest:** each method makes one-step-ahead forecasts for the last 12 months using only earlier
   data; MAD, MSE, MAPE and bias are computed. **Auto picks the lowest MAD** for each item.
4. The chosen method forecasts 13 months ahead, spread into a forecast for each of the next 365 days.
5. Outputs used downstream:

| Symbol | Definition |
|---|---|
| d̄ | Average forecast daily demand over the next ⌈L̄⌉ days (the lead time) |
| D | Sum of the next 365 days of forecast |
| σd | 1.25 × MAD × √30.4 |

**Why σd = 1.25 × MAD × √30.4.** For normally distributed errors σ ≈ 1.25 × MAD. The MAD is measured on
monthly *averages*, whose σ is σ_daily / √30.4, so we multiply back. Safety stock therefore protects
against what the forecast cannot predict, including the uncertainty about how severe a flu season will be.
For non-seasonal items this gives about the same σd as the plain standard deviation of daily usage
(ceftriaxone: 14.4 vs 13.0), which is a useful sanity check.

Fallback: with fewer than 4 months of history (or the sidebar set to *Simple average*), d̄ and σd are the
mean and standard deviation of daily usage over a chosen window.

### Step 2: Lead time
L̄ and σL are the mean and standard deviation of `deliveries.lead_time_days` for the item. An item with no
history borrows its supplier's average.

### Step 3: Order quantity (slides 183-190)
- H = i × C
- EOQ = √(2DS / H)
- **Shelf-life cap:** Q = min(EOQ, d̄ × shelf life × 0.8). Ordering more than can be used before expiry
  would turn holding cost into waste.

### Step 4: Safety stock and reorder point (slides 197-204)
- z = Φ⁻¹(service level); the service level is set per VED class (default V 99%, E 95%, D 90%)
- σ_DDLT = √(L̄σd² + d̄²σL²)
- SS = z × σ_DDLT; DDLT = d̄ × L̄; **ROP = DDLT + SS**
- Fill rate = 1 − σ_DDLT × L(z) / Q, with L(z) = φ(z) − z(1 − Φ(z)) (slides 205-207)

### Step 5: Status and order quantity
- **Inventory position = usable + on order.** *Usable* excludes expired lots; *on order* prevents
  re-ordering something already ordered.
- 🔴 if position ≤ ROP; 🟡 if position ≤ ROP + 7 days of demand; otherwise 🟢.
- When 🔴, the suggested order is **⌈ROP + Q − position⌉**: "order up to R + Q". In the textbook
  case (position exactly at R) this equals Q. If position has fallen below R (big emergency issue, late
  reaction), it also covers the shortfall, so the item is no longer at risk after ordering.
- **Vital items at risk** = 🔴 items with VED = V.
- **On order** counts only lines that were *sent*. Once the vendor has acknowledged a PO it counts the
  **confirmed** quantity, so a vendor backorder immediately lowers the position and can turn the item 🔴 again.

---

## 4b. Purchasing and the vendor simulation (`purchasing.py`)

**Consolidation.** `draft_suggested_orders` takes every 🔴 item that is not already ordered or drafted,
groups it by the item's vendor, and creates one draft PO per vendor. Quantity = the plan's order
quantity (order up to R + Q), price = item master unit cost, need-by = today + quoted lead time.
One PO with several lines instead of several POs is what real systems do; it also lowers the real
ordering cost S per item.

**Lifecycle.** The status is not stored step by step. When a PO is sent, `send_order` draws its whole
story from the vendor's parameters (with a random generator seeded by the PO number, so it never
changes on reload):

| Event | Date |
|---|---|
| Acknowledgement (EDI 855) | sent + `ack_days` (0-2) |
| Real lead time L | max(1, round(Normal(L̄, σL))), the same L̄, σL as the sample history |
| Arrival | sent + L |
| Shipment / ASN (EDI 856) | max(ack, arrival − transit days) |
| Promise | sent + quoted lead time (= L̄). Because the real lead time varies around it, 20-50% of deliveries are late (the vendor scorecard shows the share) |
| Vendor backorder | with probability `short_prob` (3-12%) a line is confirmed at 40-90% |
| ASN lot / expiry | expiry = arrival + shelf life × U(0.6, 0.95); 8% of lots are short-dated (×U(0.15, 0.35)) |

`stage(header, today)` then compares today with these dates: SENT > CONFIRMED > SHIPPED > ARRIVED.
The user sees only what has happened by today (confirmed quantities after the acknowledgement,
lots after the ASN). `db.receive` refuses a line whose PO has not arrived.

**Vendor scorecard.** From the `deliveries` table: number of deliveries, average lead time (L̄), σL,
on-time share (lead time ≤ quoted) and fill rate (received ÷ ordered, POs from this version only).

---

## 4c. The simulation clock (`simulation.py`)

`db.today(conn)` returns the simulated date from `settings`, or the real date. Every rule uses it
(dates in the future are refused relative to it), so the whole app moves with the clock.

`advance(conn, days, …)` runs day by day:

1. **Morning:** if auto-receive is on, every PO at the dock is received per its ASN.
2. **Demand:** for each item, demand = round(max(0, Normal(μ, cv·μ))) with
   μ = forecast rate for that day × weekday factor (from the last 365 days of history) and
   cv = σ/mean of the last 90 days. It is issued FEFO from usable stock. Unfilled demand is written to
   `stockouts`, a STOCKOUT ledger row, **and** to `usage`, because the forecast must see true demand,
   not only what happened to be on the shelf (otherwise stockouts would make the forecast too low).
3. **Evening:** depending on the setting, nothing, drafts, or drafts that are sent at once.

The forecast is computed once and recomputed when a month is completed. A 30-day run takes about 7 seconds.

The point of the clock is to test the (Q, R) policy from slides 197-204 instead of only calculating
it. You can see the fill rate it actually achieves, how late vendors and backorders hurt it, and what
happens when drafts sit unapproved.

---

## 4d. Recalls, vendor disruptions and KPIs (`events.py`, `kpis.py`)

**Recall** (`events.recall_lot`). Every unit of the lot still on the shelf is set to zero with a `RECALL`
ledger row (with its lot link, so the lot trace shows it). It is recorded as a loss, never as usage, so
demand and forecasts are not distorted. The `recalls` table blocks the lot from ever being received:
`db.receive` raises an error and `purchasing.receive_order` refuses that line at the dock (`REFUSED`).
Departments that already got units are listed from `transaction_lots` (ward-level stock is not tracked).

**Vendor disruption** (`vendor_outages`: vendor, from, until). `purchasing.send_order` checks the vendor on
its acknowledgement date. If it is disrupted, every line is confirmed as 0, the header gets a `vendor_note`,
and nothing ships. `process_vendor_responses` (run on page load and every simulated day) cancels those lines
once the acknowledgement date is reached (`PO REJECTED`), so they stop counting as on order and the item
can turn 🔴 again.

**Backup vendor.** `items.backup_supplier` is filled by a fictional second-source rule
(`db.backup_supplier_for`). `purchasing.order_vendors` returns the primary vendor, or the backup while the
primary is disrupted. The backup charges `BACKUP_PREMIUM` = 12% over the contract price, and its own lead
time applies (the item's L̄ and σL then mix both vendors' deliveries, as in real history).

**Random events.** With *Random events* on, each simulated day has a 1/45 chance of a vendor disruption
(7-28 days) and a 1/40 chance of a recall of a random lot on the shelf (Class I 20%, II 65%, III 15%).

**KPIs.** Fill rate = 1 − stockout units ÷ demand units (usage includes unmet demand). Inventory value per
day is rebuilt backwards from today's lots: value(d) = value now − Σ value of ledger movements after d.
This only holds from the first ledger movement, so inventory KPIs start there. Turns = issued value per day
× 365 ÷ average inventory; days on hand = average inventory ÷ issued value per day. Vendor KPIs use orders
that arrived (on time = arrival ≤ promised date) or were rejected in the period.

---

## 5. Lots, FEFO and expiry

- **Issue:** picks lots in expiry order, skipping lots with `expiry_date ≤ issue date`. Refuses if usable stock is insufficient.
- **Receive:** requires lot number and expiry date; rejects expired lots; warns when (usable + qty) / d̄ exceeds the days left.
- **Expiry projection** (`planning.project_expiry`): for each item, lots are taken in expiry order.
  With C(t) = cumulative forecast demand over the next t days and U = units already used from earlier lots:

  used = min(qty, max(0, C(days_left) − U)), waste = qty − used

  This uses the day-by-day forecast, so a lot expiring just before flu season gets credit for the busier weeks.
  Projected waste is the overage cost (Co) side of the newsvendor trade-off (slides 221-224).

---

## 6. ABC-VED classification (slides 213-215)
- ABC on annual dollar value (D × C): an item is **A** while the cumulative share *before* it is < 70%,
  **B** while < 90%, else **C**. This reproduces the university-shop example on slide 215.
- Combined with VED into the standard hospital control matrix:
  **Category I** = AV, AE, AD, BV, CV (tight control); **II** = BE, CE, BD; **III** = CD.

---

## 7. Verification

| Test file | What is checked against the slides |
|---|---|
| `test_inventory_math.py` | EOQ (p. 188), uncertain demand & lead time (p. 203), backorders and fill rate (p. 208), newsvendor (pp. 225, 228-231), ABC (p. 215) |
| `test_forecasting.py` | Error measures (p. 272), moving averages (p. 278), MA vs ES (p. 286), Holt set-up (p. 293), Winters table (p. 306), initialisation (p. 305) |
| `test_db.py` | Stock rules: FEFO, no expired issues, no over-issue, lead-time capture, inventory position, write-offs ≠ demand, cycle counts, lot tracing, expiry projection |
| `test_purchasing.py` | One draft per vendor with pre-filled quantities and prices; drafts are not on order; lines must belong to the vendor; lifecycle follows the clock; no receiving before arrival; ASN lots land on the shelf; backorders lower on-order after acknowledgement; cancel rules; clock and reset; simulation keeps demand history complete; auto modes |

Where the slides show no final answer, the expected values were computed by hand. Notes:
- p. 208 uses the *sample* standard deviation.
- p. 305: the slide's rounded seasonal factors (0.34, 0.14, 0.24, 0.29) are matched within ±0.01.

---

## 8. Sample data
`generate_sample_data.py` creates a fictional US hospital: 30 items in USD, 4 fictional suppliers
(lead times 2 to 21 days), 3 years of daily usage (Nov 2023 to Oct 2026) with weekend dips, +4% growth per year,
a flu season with a different severity each year, a summer trauma peak for some items, and a few
deliberately expired or short-dated lots. The random seed is fixed, so the data is reproducible.

---

## 9. Known limitations and possible extensions

| Limitation | Possible extension |
|---|---|
| σd is constant over the year, but forecast errors are larger in flu season | Month-specific σ from backtest errors |
| One lot per delivery | Multi-lot receiving |
| One primary + one backup vendor; switch only during a disruption | Several sources, approved substitutes, switch on partial backorders |
| No invoices | Invoice from the vendor and three-way match (PO = receipt = invoice) |
| Order quantities not rounded to case packs | Pack size per item; round up to full cases |
| Demand in the simulation is independent per day | Bullwhip experiment: let several echelons order from each other (slides 236-238) |
| No quantity discounts (slide 195) | All-units discount EOQ |
| Single location | Multi-location with transfers (location pooling, slide 235) |
| Smoothing constants are fixed defaults | Choose α, β, γ by minimising backtest MSE |
| One sign-in gate (salted PBKDF2 hashes in Streamlit secrets), no roles | Roles (buyer, approver, ward), single sign-on, audit by user |
| Runs locally | Deploy to Streamlit Community Cloud |
