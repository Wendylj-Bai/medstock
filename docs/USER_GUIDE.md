# MedStock User Guide

MedStock helps a hospital supply room answer three questions every day:

1. **What do I need to order today, and how much?**
2. **What is about to expire?**
3. **Is demand about to change?** (for example, flu season)

It tracks every box that comes in and goes out, by lot number and expiry date, and recalculates
reorder points automatically from real usage and real supplier delivery times.

---

## 1. Starting MedStock

Open a terminal in the `Inventory Managment` folder and run:

```bash
.venv/bin/streamlit run app.py
```

Then open **http://localhost:8501** in your browser. Leave the terminal window open while you work.

---

## 2. What's on the screen

The sidebar on the left has four parts: the **menu** with the six main pages (Dashboard, Inventory,
Purchasing, Forecast, Alerts and Reports), **More** with every other page, **Planning settings**
(the simulation clock and the hospital policy settings: how much protection each type of item gets
and how demand is forecast), and **Project home / Sign out** at the bottom. "More" and "Planning
settings" start collapsed; click them to open. In the menu, **Alerts** is the Recalls & disruptions
page and **Reports** is the KPIs page.

**The notification bell** sits next to the word "Menu" at the top of the sidebar. It is the one place
that counts active alerts:

- recalled lots with a recall in the last 14 days,
- vendors with a supply disruption today,
- items with a lot on the shelf that has expired or expires within 30 days (an item counts once, however
  many of its lots qualify; recalled lots are not counted again here).

Reorder suggestions are not counted; they are on the Dashboard and Inventory. A red number appears on the
bell only when there is at least one active alert (above 99 it shows "99+"). Click the bell to open
**Alerts**. The bell is inside the sidebar, so on a phone it is hidden while the sidebar is closed; open
the sidebar with the arrow at the top left to see it.

**Actions that cannot be undone ask first.** Recalls, vendor disruptions (starting one, ending one early,
or simulating a random one), write-offs, approving or cancelling a purchase order, deleting a draft,
refusing a line at the dock and unusually large issues open a confirmation that lists exactly what will
change. Nothing is saved until you press the confirm button; **Cancel**, the **X** or the **Esc** key
leave everything as it was.

| Page | What it is for |
|---|---|
| **Dashboard** | Start here every day: the most urgent items, draft purchase orders, supply alerts and charts |
| **Inventory** | Every item: search, quick views, filters, row actions and CSV export |
| **KPIs** (Reports) | Is inventory management working? Fill rate (predicted and measured), stockouts, inventory turns, days on hand, waste, vendor reliability, weekly trends and CSV export |
| **Purchasing** | Purchase orders to vendors: drafts to approve, orders on their way, vendor messages, the vendor directory and scorecard |
| **Stock movements** | Record what physically happens: issue to a department, receive a delivery, write off, count |
| **Recalls & disruptions** | Recall a lot, or make a vendor unable to supply, and watch how the system reacts. The notification bell at the top of the sidebar counts active alerts and opens this page |
| **Forecast** | Expected demand for the next 12 months, and which items are about to get busier |
| **Expiry** | Expired stock, stock expiring soon, and stock that will expire before it can be used |
| **Item detail** | Everything about one item, including how its reorder point was calculated |
| **History** | Every movement ever recorded, record accuracy, and lot tracing for recalls |
| **ABC-VED analysis** | Which items deserve the most attention (money × clinical importance) |
| **Calculators** | What-if calculators for order quantity, reorder point and one-time purchases |
| **Help** | Getting started, status definitions, workflows, formulas and how to reset the demo, plus this guide |

---

## 3. Words you will see

| Term | Meaning |
|---|---|
| **VED** | Clinical importance. **V**ital = a patient can be harmed if it runs out (e.g. epinephrine, IV fluids). **E**ssential = important, but there are workarounds. **D**esirable = nice to have. |
| **ABC** | Money importance. **A** items are the few that make up about 70% of annual spending, **C** items are the many cheap ones. |
| **On hand** | Everything physically on the shelf, including expired boxes. |
| **Usable** | On hand **minus expired lots**. Only usable stock counts, because expired stock must never reach a patient. |
| **On order** | Ordered from the supplier but not yet received. |
| **Reorder point (ROP)** | When usable + on order drops to this number, it is time to order. |
| **Safety stock** | The extra cushion inside the reorder point that protects against busier-than-expected days and late deliveries. |
| **Order quantity (Q)** | The most economical amount to order at once. Never more than can be used before it expires. |
| **Days of supply** | How many days the usable stock will last at the current rate of use. |
| **Lot** | One batch from the manufacturer, with its own lot number and expiry date (printed on the box). |
| **FEFO** | *First Expired, First Out.* MedStock always tells you to use the lot that expires soonest. |
| **Fill rate** | The share of requests that can be filled straight from the shelf. |
| **PO (purchase order)** | The official order to one vendor. It has one **line** per item. |
| **Draft** | A PO that MedStock prepared but nobody has approved yet. **The vendor has not received it**, so it does not count as *on order*. |
| **ASN** | *Advance ship notice*: the vendor's message that the order has shipped, with carrier, tracking number, and the lot numbers and expiry dates in the boxes. |
| **Vendor backorder** | The vendor cannot supply the full quantity. You get what it confirmed; the rest must be reordered. |

**Status colors**

| Status | Meaning | What to do |
|---|---|---|
| 🔴 **Order now** | Usable + on order is at or below the reorder point | Place an order today |
| 🟡 **Order soon** | Will reach the reorder point within about a week | Plan the order |
| 🟢 **OK** | Enough stock | Nothing |

---

## 4. A typical day

**Every morning (5 minutes)**
1. Open 📋 **Dashboard**.
2. Read the colored boxes at the top. **Red = Vital items at risk.** Handle those first.
3. Check the 🔴 list and click **📝 Prepare draft purchase orders**.
4. Go to 🛒 **Purchasing**, review each draft, click **Review and approve**, then **Approve and send** (6.3).
5. Receive anything waiting at the dock (📦 banner on the Dashboard, see 6.2).

**During the day**
- Every time a department takes stock: **Issue to ward** (6.1).
- Every time a delivery arrives: **receive it** (6.2).

**Every week**
- ⏳ **Expiry** page: write off expired stock, act on lots that will expire unused.
- **Cycle count** a few items (6.6). Count Category I items (see ABC-VED) every week.

**Every month**
- 📈 **Forecast** page: look at the seasonal outlook before flu season or summer.

---

## 5. The Dashboard

The dashboard is a summary. Under the title you see the date (marked *simulated date* once the clock
has moved) and one line such as *"44 items to order now and 40 Vital items at risk."*

### 5.1 The four cards at the top

| Card | Meaning | The small line under the number |
|---|---|---|
| **Order now** | Items at or below their reorder point | How many more will reach it soon |
| **Vital items at risk** | Vital items whose usable stock may run out before the next reliable delivery | How many have no usable stock at all |
| **Fill rate** | Share of requested units filled from the shelf over the last 4 weeks | Change from last week, or *No weekly history yet* |
| **Inventory value** | Dollar value of everything on the shelf | Change from last week, or *No weekly history yet* |

Hover over the **?** next to a card for its exact definition.

### 5.2 Urgent inventory actions

A short table of the **8 most urgent items**: no usable stock first, then shortage risk, then items
at their reorder point, Vital items before others. It shows the risk in words, days of stock left,
what is already on order, the suggested order and the vendor. **View all items** opens the
Inventory page with the full list.

Right below it, **Suggested purchase orders** shows how many vendors and items are involved and the
estimated value. **Prepare N draft purchase orders, one per vendor** creates drafts only. Nothing is
sent: you review and approve each draft in Purchasing (6.3). Only then do the items count as
*on order*. **Breakdown by vendor** lists each vendor's lines, value and freight.

### 5.3 Supply alerts and analytics

Three cards, each with a label (**Needs attention** or **All clear**), a short description and a
button that opens the right page:

- **Expiring stock:** expired lots still on the shelf, and lots expiring within 30 days.
- **Rising demand:** items forecast to rise by 15% or more over the next 90 days. Their reorder
  points already include the rise, so this is a heads-up.
- **Vendor delays:** late deliveries, vendor outages, recent recalls and deliveries waiting at the
  dock (then the button is **Receive** for that order).

Below them, four charts: **Demand trend** (complete weeks of actual demand plus a 4-week forecast),
**Reorder status** (Order now, Order soon, Enough stock, with counts), **Vendor performance**
(share of deliveries on time) and **ABC-VED mix** (items by spend class and criticality).

### 5.4 The full table (Inventory page)

The **Inventory** page lists every item. Start with the toolbar:

| Control | What it does |
|---|---|
| **Search** | Finds items by name or ID (for example *insulin* or *MED007*) |
| **Quick view** | All, Order now, Shortage risk, Incoming (an order is on its way) or Expiring (a lot has expired or expires within 30 days). Each button shows how many items it holds. |
| **More filters and columns** | Reorder status, Availability, Criticality, Sort by, and extra calculation columns (on hand, reorder point, safety stock, VED, ABC, order value) |
| **Clear filters** | Puts every filter back to "all" in one click |

The table shows the item and its ID, one **Status**, usable stock, stock on order, days of supply, the
suggested order and the vendor. **Status** is the more urgent of the item's two statuses:

- **Reorder status**: is it time to place an order? (Order now, Order soon, OK)
- **Availability**: will usable stock last? (No usable stock, Shortage risk, Shortage watch, Enough stock)

An item can be OK for ordering but at risk for availability: an order is already on the way, but stock
may run out before it arrives. Statuses are always written in words, never shown by color alone.

**Select a row** (the box at its left) to open the item, issue stock, create a purchase order or see its
history. **Download as CSV** exports every column with full precision for the items shown. The line above
the table warns you if your filters are hiding a Vital item at risk. The measured fill rate from logged
requests is on **Reports**.

**Why does a Vital item disappear from the list after I order it?** Because it is no longer at risk:
the order counts as *on order*, and usable + on order is now above the reorder point. If the delivery
is late, watch **On order** in Stock movements (late lines are marked).

---|---|
| **Reorder status** | 🔴 / 🟡 / 🟢 from the reorder point: is it time to place an order? |
| **Availability** | Will usable stock last the next 90 days? An item can be 🔴 here even with an order on the way, if that order arrives too late. |
| **Criticality** | V - Vital, E - Essential, D - Desirable |
| **Sort by** | Reorder status, red first (default) or green first, availability risk, Vital first, lowest days of supply, or highest order value |

The first column is **Reorder status** and the second is **Availability**, in the same order as the
filters. Availability says 🟢 **Enough stock** (not "OK") so the two columns are easy to tell apart.
An item can be 🟢 for reorder status but 🔴 for availability: an order is already on the way, but
stock may run out before it arrives.

The line above the table says how many items are shown, and warns you if your filters are hiding a
Vital item with 🔴 availability.

**Why does a Vital item disappear from the list after I order it?** Because it is no longer at risk:
the order counts as *on order*, and usable + on order is now above the reorder point. If the delivery
is late, watch **Open purchase orders** in Stock movements (late ones are marked *Overdue*).

---

## 6. How to …

### 6.1 Issue stock to a department
1. 📦 **Stock movements** > **📤 Issue to ward**.
2. Choose the **Item**. The blue box shows how many usable units you have.
3. Choose the **Department** and **Quantity**. Change the date only if you are entering yesterday's issues.
4. Click **Issue stock**.
5. The message tells you **which lot(s) to take from the shelf**, e.g. *"Take from shelf: lot L99201 × 20"*.
   Take those boxes. They are the ones that expire first.

> MedStock will refuse to issue expired stock, and will refuse to issue more than you have.

### 6.2 Receive a delivery
A delivery can be received once it has **arrived at the dock** (📦 banner on the Dashboard, or
status 📦 *Arrived at dock* in Purchasing).

**Quick way (everything as the vendor said):** **Purchasing** > open the PO >
**Receive whole shipment (as per ASN)**. Every line goes on the shelf with the lot numbers and expiry
dates from the vendor's ship notice. A line can arrive as **several lots** (boxes from different
production runs, each with its own expiry date); each lot gets its own place on the shelf, so the
earliest-expiring one is issued first. If one of those lots is under recall, only that lot is refused.

**Line by line (to check the boxes):** **Stock movements** > **Receive delivery**.
1. Choose the **Delivery line**.
2. The **lots table** is pre-filled from the ship notice: one row per lot number, with its expiry
   date and quantity. Change a row if the boxes say something else, add a row for an extra lot, or
   delete one. The line under the table shows the total you are receiving. Every lot needs a lot
   number and an expiry date, and the same lot number cannot appear twice.
3. Check the yellow warning, if any: it appears when, at current usage, part of this lot would
   expire before it can be used. Consider refusing it or asking for a longer-dated lot.
4. Click **Receive**, or **Refuse / cancel this line** to send it back. Refusing asks you to confirm and shows
   the order, item, quantity and vendor first; the line then no longer counts as on order.

MedStock records the real delivery time, which makes future reorder points more accurate.

> A delivery that is already expired is rejected. Do not accept it; return it to the vendor.

### 6.3 Review, approve and send a purchase order
1. 🛒 **Purchasing** > **📄 Purchase orders** > choose the PO (drafts say *📝 Draft*).
2. You see the PO the way the vendor will: vendor address and contact, ship-to address, payment terms,
   the lines with quantity and price, freight and total.
3. Change quantities if needed (0 removes a line), add other items from the same vendor, set the
   **Need by** date and **Notes to vendor**.
4. Watch the messages under the total: *below the vendor's minimum order* or *$X more and freight is free*.
5. Click **Review and approve**. A summary of the vendor, lines, total and need-by date opens; click
   **Approve and send** to send it, or **Cancel** to keep editing. (Or **💾 Save changes** to keep it as a
   draft, or **🗑️ Delete draft**, which also asks you to confirm.)
6. **⬇️ Download PO document** gives a printable PO (open it in your browser, print or save as PDF).

**To order something MedStock did not suggest:** Purchasing > **➕ New purchase order** > choose the vendor.
Every item from that vendor is listed with its status and a *Suggested* quantity. Type the quantities you
want under **Order qty**, then **Review and approve** or **Save as draft**.

### 6.4 Follow an order and cancel it
Open the PO in Purchasing. The status bar shows where it is:

📝 Draft > 📤 Sent > ✔️ Confirmed > 🚚 Shipped > 📦 Arrived at dock > ✅ Received

Under **Vendor messages** you see what the vendor has told you so far: the acknowledgement (and any
**vendor backorder**), the shipment with tracking number, and the delivery (on time or late).
**❌ Cancel order** is possible until the vendor ships. It asks you to confirm, because a cancelled order cannot be reopened.

### 6.5 Write off stock (expired, damaged, recalled, lost)
- **One lot:** 📦 **Stock movements** > **Write-off** > choose the item and the **lot** > a **reason** (required) > quantity > **Review write-off**, then **Write off** in the confirmation.
- **One expired lot:** ⏳ **Expiry** page > select the lot in the expired table > **Write off lot ...**.
- **All expired stock at once:** ⏳ **Expiry** page > **Write off all expired lots**. The confirmation lists every lot, quantity and value first.

A write-off cannot be undone. If one was a mistake, correct the shelf quantity with a cycle count.

Write-offs are *not* counted as demand, so they do not make the forecast think the item is busier.

### 6.6 Count stock (cycle count)
1. 📦 **Stock movements** > **🔢 Cycle count**.
2. Choose the item and the **lot**.
3. Count the boxes of that lot on the shelf and enter the number. The system quantity is hidden on purpose,
   so the count is not influenced by it (a *blind count*).
4. Click **Save count**. The message shows what you counted and what the system expected. If they differ,
   MedStock corrects the stock and records the difference.

The **Record accuracy** number in History shows how often the counts matched. Aim for 97% or more.

### 6.7 Handle a recall
1. 🚨 **Recalls & disruptions** > **Product recalls**.
2. Choose the lot from the recall notice, its **class** and the reason, then **Review recall for this lot**.
   (Or press **Simulate a random manufacturer recall** to practice.) A confirmation shows the item, units,
   value, wards that already received it and the expected effect. Nothing changes until you click **Confirm recall**.
3. MedStock then:
   - pulls every unit of the lot off the shelf (a loss, **not** demand, so the forecast is not inflated);
   - lists the **departments that already received it**, so they can check their shelves;
   - **refuses** any delivery still on its way with that lot number.
4. Usable stock has dropped, so the item may turn 🔴 on the Dashboard. Order a replacement as usual.

Recall classes (FDA): **I** could cause serious harm, **II** temporary or reversible harm, **III** unlikely to
cause harm (for example a labeling error). Every movement of any lot: 📜 **History** > **🔍 Lot trace**.

### 6.8 When a vendor cannot supply (disruption)
Every item has a **primary** vendor and a **backup** vendor (shown in Purchasing > 🏢 Vendors).
1. 🚨 **Recalls & disruptions** > **Vendor disruptions**: choose the vendor, how many days, and why, then
   **Review disruption** (or **Simulate a random disruption**), then **Start disruption** in the confirmation,
   which lists the items that switch to a backup vendor.
2. While it lasts:
   - orders that vendor receives are **rejected** at acknowledgement (you see ❌ in its vendor messages), and
     what was "on order" is no longer counted;
   - the Dashboard and the automatic reordering send that vendor's items to their **backup vendor**, at
     **+12%** price and with the backup's own lead time;
   - orders already shipped still arrive.
3. Press **… is supplying again** to end it early, then confirm. Ordering then goes back to the primary vendor.

### 6.9 Check how well inventory is managed (KPIs)
📊 **KPIs** > choose the period (30, 90 or 365 days).

| KPI | Meaning | Good direction |
|---|---|---|
| **Fill rate** (and Vital fill rate) | Units served ÷ units requested | Higher (98%+; Vital 99.5%+) |
| **Stockout events** | Item-days with a request that could not be filled | Lower |
| **Average inventory** | Dollar value on the shelf | Lower, *as long as fill rate holds* |
| **Inventory turns** | Yearly value issued ÷ average inventory | Higher = leaner |
| **Days on hand** | How long the average stock would last | Lower, but not too low |
| **Waste** | Expired, damaged, lost and recalled stock in dollars | Lower |
| **On-time deliveries**, **vendor fill rate** | Vendor reliability | Higher |
| **Orders rejected**, **spend with backup vendors** | Cost of vendor disruptions | Lower |

Fill rate and inventory value usually move in opposite directions: that trade-off is what safety stock manages.

### 6.10 Export the history
📜 **History** > filter by type or item if you like > **⬇️ Download as CSV** (opens in Excel).

### 6.11 See why an item has the reorder point it has
**Item detail** > choose the item > open **Show the calculation**. Every number is shown step by step.

### 6.12 Ask MedStock (AI assistant)
**Ask MedStock** is under **More** in the menu. Type a question, or click one of the example questions,
for example "What should I order today, and why?". The assistant looks the answer up in MedStock's own
data and shows, under each answer, how many lookups it made, how long it took, how many tokens it used,
an **estimated** cost at the provider's standard paid rates, and whether every figure in the answer was
found in the data. The estimate is not an invoice: MedStock cannot see whether the Gemini key belongs to
a free-tier or a billed project. When the app is set up for the free tier, the page adds that the expected
charge is $0 while the project stays within the free tier. The daily spending limit counts the estimate
and is checked before each new question: once it is reached, no more questions are sent that day. The
answer in progress when the limit is reached can take the total slightly over it. Open **What it looked up** to see each lookup.
- It can only **read**. It cannot order, issue, receive or change settings; it tells you which page does that.
- It uses Google Gemini by default (the model is named above the chat). It does not search the web;
  it only uses MedStock's data.
- **Privacy:** on Gemini's free tier, Google may use what you type to improve its products. Use it only
  with this fictional demo, never with real patient, hospital, vendor-confidential or personal information.
- **New conversation** clears the chat. **Audit log and usage** lists every answer with its provider,
  model, tokens and estimated cost.
- It needs a `GEMINI_API_KEY` in the app's secrets (see docs/AI_DESIGN.md). Each account has a daily
  question limit and a daily limit on estimated spending. Without a key, the page explains how to add one and everything else works.

---

## 7. The simulation clock

MedStock comes with fictional vendors and a fictional hospital, so you can watch weeks of operations in seconds.
The sidebar shows **Today** (marked *simulated* once the clock has moved).

| Button | What happens |
|---|---|
| **+1 day** / **+7 days** | Each simulated day: deliveries at the dock are received (if auto-receive is on), every department uses stock (random demand around the forecast, quieter on weekends), and vendors move your orders along |
| **Next** | Jumps to the day the next delivery arrives |

After each run a **Simulation report** shows units requested, the share filled from the shelf
(the fill rate), **stockouts**, deliveries received and POs created.

**Simulation settings** (sidebar):

| Setting | Meaning |
|---|---|
| **Automatic reordering: Off** | You order yourself (the default) |
| **Create drafts for approval** | Every evening MedStock drafts POs for 🔴 items. They wait for you. This is how most hospital systems work. |
| **Fully automatic (send POs)** | MedStock drafts *and sends* the POs. Hospitals do this for low-risk, high-volume items. |
| **Auto-receive deliveries** | Receive deliveries as the ship notice lists them. Turn off to receive them yourself. |
| **Random events** | Each simulated day there is a small chance that a vendor cannot supply for 1-4 weeks (about every 6 weeks), or that a lot on your shelf is recalled (about every 6 weeks). Off by default. |
| **Reset to fresh sample data** | Erases everything and sets the clock back to the real date (tick the box first) |

**Vendors behave like real ones (all fictional):**

| Vendor | Orders via | Promised | Reality |
|---|---|---|---|
| Northwest Medical Distributors | EDI | 2 days | 2 ± 0.6 days, rarely short |
| Pacific Pharma Supply | EDI | 4 days | 4 ± 1.2 days |
| Cascade Surgical Supply | Email | 7 days | 7 ± 2.5 days |
| Overseas Medical Imports | Web portal | 21 days | 21 ± 7 days, more often short |

**Experiments to try:**
1. Reset, then press **+7 days** without ordering anything. Look at the stockouts.
2. Reset, prepare and approve the suggested POs, then press **+7 days** a few times. Compare.
3. Set *Fully automatic*, raise the Vital service level to 99.9% and simulate a month. More safety stock,
   fewer stockouts, more money on the shelf (Dashboard: inventory value).
4. Watch the 🏢 **Vendors** scorecard: late deliveries from Overseas are why its items need so much safety stock.
5. Turn on *Fully automatic* and *Random events*, simulate two months, then open 📊 **KPIs**: see what the
   recalls and disruptions cost (waste, rejected orders, backup spend) and whether fill rate held.

## 8. Policy settings (sidebar)

| Setting | What it does | Default |
|---|---|---|
| **Service level: Vital / Essential / Desirable** | The chance of *not* running out during a delivery wait. Higher = more safety stock = more money on the shelf. | 99% / 95% / 90% |
| **Demand forecast: Method** | How future demand is estimated. Leave on **Auto** unless you are comparing methods. | Auto |
| **Smoothing constants** | Fine-tuning for the forecast methods. Leave as is unless you know the methods. | α 0.2, β 0.1, γ 0.3, N 3 |

Changes apply immediately to every screen but are **not saved**. They reset when the page is reloaded.

---

## 9. Messages you may see

| Message | Meaning | What to do |
|---|---|---|
| *Only X usable … on hand (Y more are expired …)* | You tried to issue more than the usable stock | Issue less; write off the expired lots |
| *Lot number is required* | Receiving without a lot number | Copy it from the box label |
| *This lot is already expired* | The expiry date is today or earlier | Do not accept the delivery |
| *Received date cannot be before the order date* | Date typo | Check the date |
| *Date cannot be in the future* | Date typo | Use today or an earlier date |
| *… is not an open purchase order* | It was already received or cancelled | Check Purchasing |
| *… has not arrived yet* | The delivery is still with the vendor or carrier | Wait, or press Next |
| *… is not supplied by …* | Each item has one vendor in the item master | Put it on that vendor's PO |
| *… has already shipped* | Too late to cancel | Refuse the line at the dock (6.2) |
| *Below the vendor's minimum order* | The PO is small | Add 🟡 items from the same vendor, or accept a small-order fee |

---

## 10. Frequently asked questions

**An item is still 🔴 after I issued stock. Why?** Issuing makes stock go *down*, so it can only get more urgent.
Only an order (or a receipt) makes it go back to 🟢.

**The suggested order is bigger than usual. Why?** Either the stock has fallen well below the reorder point
(MedStock then also orders the shortfall), or the forecast expects busier weeks ahead (e.g. flu season).
The Item detail page shows the exact numbers.

**Why is the order quantity smaller than the "EOQ"?** For items with a short shelf life, MedStock never orders
more than can be used within 80% of the shelf life, to avoid waste.

**How do I start over with fresh sample data?** Sidebar > Simulation settings > tick *I want to erase everything*,
then **Reset to fresh sample data**.

**Why are there stockouts right after I start the simulation?** The sample hospital starts with several items
already below their reorder point, some from a vendor that needs 21 days. Even a perfect order today
arrives too late for those. That is the cost of reacting late, and the reason the reorder point includes the lead time.

**Do professional systems order automatically?** Mostly they *prepare* the order automatically: they
find what is below its reorder point (or par level), group the items by each item's vendor into one PO
per vendor, and fill in quantities and contract prices. A buyer approves, often only the exceptions
(expensive or unusual orders), and the PO goes to the vendor electronically (EDI).
MedStock works the same way; the sidebar setting lets you try all three levels of automation.

**Is the sample data real?** No. It is a realistic, made-up US hospital with 150 items, 3 years of usage,
a yearly flu season and a summer peak for trauma supplies.

---

## 11. Current limitations

- Each item has one primary and one backup vendor; real systems may have several, plus approved substitute items.
- A recall pulls the lot from the storeroom only; stock already on ward shelves is not tracked (wards are listed to notify).
- No invoices or three-way match (PO = receipt = invoice), and no rounding to case packs.
- Vendors, the hospital and their behaviour are fictional and simulated.
- Sidebar settings are not saved between sessions.
- Sign-in is a simple gate: everyone who signs in has full access (no roles such as buyer or approver).
- MedStock runs on one computer. To share it, it must be deployed to a server.
