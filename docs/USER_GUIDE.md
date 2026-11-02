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

| Area | What it is for |
|---|---|
| **Sidebar (left)** | The 🕒 **simulation clock**, plus hospital policy settings: how much protection each type of item gets, and how demand is forecast |
| 📋 **Dashboard** | Start here every day: what to order, what is at risk |
| 📊 **KPIs** | Is inventory management working? Fill rate, stockouts, inventory turns, days on hand, waste, vendor reliability, weekly trends |
| 🛒 **Purchasing** | Purchase orders to vendors: drafts to approve, orders on their way, vendor messages, the vendor directory and scorecard |
| 📦 **Stock movements** | Record what physically happens: issue to a department, receive a delivery, write off, count |
| 🚨 **Recalls & disruptions** | Recall a lot, or make a vendor unable to supply, and watch how the system reacts |
| 📈 **Forecast** | Expected demand for the next 12 months, and which items are about to get busier |
| ⏳ **Expiry** | Expired stock, stock expiring soon, and stock that will expire before it can be used |
| 🔎 **Item detail** | Everything about one item, including how its reorder point was calculated |
| 📜 **History** | Every movement ever recorded, record accuracy, and lot tracing for recalls |
| 🅰️ **ABC-VED analysis** | Which items deserve the most attention (money × clinical importance) |
| 🧮 **Calculators** | What-if calculators for order quantity, reorder point and one-time purchases |
| 📖 **Help** | This guide |

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
4. Go to 🛒 **Purchasing**, review each draft and click **✅ Approve & send to vendor** (6.3).
5. Receive anything waiting at the dock (📦 banner on the Dashboard, see 6.2).

**During the day**
- Every time a department takes stock: **Issue to ward** (6.1).
- Every time a delivery arrives: **receive it** (6.2).

**Every week**
- ⏳ **Expiry** tab: write off expired stock, act on lots that will expire unused.
- **Cycle count** a few items (6.6). Count Category I items (see ABC-VED) every week.

**Every month**
- 📈 **Forecast** tab: look at the seasonal outlook before flu season or summer.

---

## 5. The Dashboard

### 5.1 The four numbers at the top

| Number | Meaning |
|---|---|
| 🔴 **Order now** | How many items need ordering today |
| 🟡 **Order soon** | How many items will need ordering within about a week |
| **Vital items at risk** | How many of the 🔴 items are **Vital** (see below) |
| **Inventory value on hand** | Dollar value of everything on the shelf |

### 5.2 Vital items at risk: where to find them

"Vital items at risk" counts the items that are **both**:
- **Vital (V)**: running out could harm a patient, **and**
- **🔴 Order now**: usable stock + stock on order is at or below the reorder point.

You can see them in three places:

1. **The number:** third box at the top of the Dashboard. Hover over the **?** next to it for the definition.
2. **The red box** right under the numbers: it names every Vital item at risk and how many days of
   stock it has left, e.g. *"Lactated Ringer's 1L (12 days left)"*.
3. **The table:** in the **Criticality** filter, choose **V - Vital**, and in **Reorder status**
   choose 🔴 **Order now**. The table then shows only the Vital items at risk.

### 5.3 Filtering and sorting the table

The four controls above the table work together, and every filter is strict (an empty filter means "all"):

| Control | What it does |
|---|---|
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
is late, watch **Open purchase orders** in 📦 Stock movements (late ones are marked *Overdue*).

### 5.4 Other banners

- ⏳ **Yellow box**: expired lots still on the shelf, or lots expiring within 30 days. Go to the ⏳ Expiry tab.
- 📈 **Blue box**: items whose demand is forecast to rise by 15% or more over the next 90 days.
  Their reorder points already include the rise, so nothing extra is needed. It is a heads-up.
- 📦 **Deliveries at the dock**: a vendor delivery has arrived and must be received before it can be used.
- ⏰ **Late vendor deliveries**: past the vendor's promised date and still not here.
- 🚫 **Stockouts in the last 30 days**: wards asked for more than was on the shelf (this happens in the simulation).

### 5.5 Placing the suggested orders

Under **Suggested purchase orders by vendor** you see one line per vendor with the PO value and freight.
Click **📝 Prepare N draft purchase order(s), one per vendor**. MedStock fills in the vendor, every
item, the quantity (order up to R + Q) and the price. Nothing is sent yet: you review and approve the
drafts in 🛒 Purchasing (6.3). Only then do the items count as *on order* and turn 🟢 or 🟡.

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
status 📦 *Arrived at dock* in 🛒 Purchasing).

**Quick way (everything as the vendor said):** 🛒 **Purchasing** > open the PO >
**📥 Receive whole shipment (as per ASN)**. Every line goes on the shelf with the lot number and expiry
date from the vendor's ship notice.

**Line by line (to check the boxes):** 📦 **Stock movements** > **📥 Receive delivery**.
1. Choose the **Delivery line**.
2. Quantity, **lot number** and **expiry date** are pre-filled from the ship notice. Change them if the boxes say
   something else (e.g. a box is missing). Both lot number and expiry date are required.
3. Check the yellow warning, if any: it appears when, at current usage, part of this lot would
   expire before it can be used. Consider refusing it or asking for a longer-dated lot.
4. Click **Receive**, or **Refuse / cancel this line** to send it back.

MedStock records the real delivery time, which makes future reorder points more accurate.

> A delivery that is already expired is rejected. Do not accept it; return it to the vendor.

### 6.3 Review, approve and send a purchase order
1. 🛒 **Purchasing** > **📄 Purchase orders** > choose the PO (drafts say *📝 Draft*).
2. You see the PO the way the vendor will: vendor address and contact, ship-to address, payment terms,
   the lines with quantity and price, freight and total.
3. Change quantities if needed (0 removes a line), add other items from the same vendor, set the
   **Need by** date and **Notes to vendor**.
4. Watch the messages under the total: *below the vendor's minimum order* or *$X more and freight is free*.
5. Click **✅ Approve & send to vendor**. (Or **💾 Save changes** to keep it as a draft, or **🗑️ Delete draft**.)
6. **⬇️ Download PO document** gives a printable PO (open it in your browser, print or save as PDF).

**To order something MedStock did not suggest:** 🛒 Purchasing > **➕ New purchase order** > choose the vendor.
Every item from that vendor is listed with its status and a *Suggested* quantity. Type the quantities you
want under **Order qty**, then **Approve & send** or **Save as draft**.

### 6.4 Follow an order and cancel it
Open the PO in 🛒 Purchasing. The status bar shows where it is:

📝 Draft > 📤 Sent > ✔️ Confirmed > 🚚 Shipped > 📦 Arrived at dock > ✅ Received

Under **Vendor messages** you see what the vendor has told you so far: the acknowledgement (and any
**vendor backorder**), the shipment with tracking number, and the delivery (on time or late).
**❌ Cancel order** is possible until the vendor ships.

### 6.5 Write off stock (expired, damaged, recalled, lost)
- **One lot:** 📦 **Stock movements** > **🗑️ Write-off** > choose the item and the **lot** > reason > quantity > **Write off**.
- **All expired stock at once:** ⏳ **Expiry** tab > **🗑️ Write off all expired lots**.

Write-offs are *not* counted as demand, so they do not make the forecast think the item is busier.

### 6.6 Count stock (cycle count)
1. 📦 **Stock movements** > **🔢 Cycle count**.
2. Choose the item and the **lot**.
3. Count the boxes of that lot on the shelf and enter the number. The system quantity is hidden on purpose,
   so the count is not influenced by it (a *blind count*).
4. Click **Save count**. If the number differs, MedStock corrects the stock and records the difference.

The **Record accuracy** number in 📜 History shows how often the counts matched. Aim for 97% or more.

### 6.7 Handle a recall
1. 🚨 **Recalls & disruptions** > **Product recalls**.
2. Choose the lot from the recall notice, its **class** and the reason, then **🚨 Issue recall for this lot**.
   (Or press **🎲 Simulate a random manufacturer recall** to practice.)
3. MedStock then:
   - pulls every unit of the lot off the shelf (a loss, **not** demand, so the forecast is not inflated);
   - lists the **departments that already received it**, so they can check their shelves;
   - **refuses** any delivery still on its way with that lot number.
4. Usable stock has dropped, so the item may turn 🔴 on the Dashboard. Order a replacement as usual.

Recall classes (FDA): **I** could cause serious harm, **II** temporary or reversible harm, **III** unlikely to
cause harm (for example a labeling error). Every movement of any lot: 📜 **History** > **🔍 Lot trace**.

### 6.8 When a vendor cannot supply (disruption)
Every item has a **primary** vendor and a **backup** vendor (shown in 🛒 Purchasing > 🏢 Vendors).
1. 🚨 **Recalls & disruptions** > **Vendor disruptions**: choose the vendor, how many days, and why, then
   **🏭 Start disruption** (or **🎲 Simulate a random disruption**).
2. While it lasts:
   - orders that vendor receives are **rejected** at acknowledgement (you see ❌ in its vendor messages), and
     what was "on order" is no longer counted;
   - the Dashboard and the automatic reordering send that vendor's items to their **backup vendor**, at
     **+12%** price and with the backup's own lead time;
   - orders already shipped still arrive.
3. Press **✅ … is supplying again** to end it early. Ordering then goes back to the primary vendor.

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
🔎 **Item detail** > choose the item > open **📐 Show the calculation**. Every number is shown step by step.

---

## 7. The simulation clock

MedStock comes with fictional vendors and a fictional hospital, so you can watch weeks of operations in seconds.
The sidebar shows **Today** (marked *simulated* once the clock has moved).

| Button | What happens |
|---|---|
| **+1 day** / **+7 days** | Each simulated day: deliveries at the dock are received (if auto-receive is on), every department uses stock (random demand around the forecast, quieter on weekends), and vendors move your orders along |
| **🚚 Next** | Jumps to the day the next delivery arrives |

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
| **🔄 Reset to fresh sample data** | Erases everything and sets the clock back to the real date (tick the box first) |

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
| *… is not an open purchase order* | It was already received or cancelled | Check 🛒 Purchasing |
| *… has not arrived yet* | The delivery is still with the vendor or carrier | Wait, or press 🚚 Next |
| *… is not supplied by …* | Each item has one vendor in the item master | Put it on that vendor's PO |
| *… has already shipped* | Too late to cancel | Refuse the line at the dock (6.2) |
| *Below the vendor's minimum order* | The PO is small | Add 🟡 items from the same vendor, or accept a small-order fee |

---

## 10. Frequently asked questions

**An item is still 🔴 after I issued stock. Why?** Issuing makes stock go *down*, so it can only get more urgent.
Only an order (or a receipt) makes it go back to 🟢.

**The suggested order is bigger than usual. Why?** Either the stock has fallen well below the reorder point
(MedStock then also orders the shortfall), or the forecast expects busier weeks ahead (e.g. flu season).
The 🔎 Item detail tab shows the exact numbers.

**Why is the order quantity smaller than the "EOQ"?** For items with a short shelf life, MedStock never orders
more than can be used within 80% of the shelf life, to avoid waste.

**How do I start over with fresh sample data?** Sidebar > Simulation settings > tick *I want to erase everything*,
then **🔄 Reset to fresh sample data**.

**Why are there stockouts right after I start the simulation?** The sample hospital starts with several items
already below their reorder point, some from a vendor that needs 21 days. Even a perfect order today
arrives too late for those. That is the cost of reacting late, and the reason the reorder point includes the lead time.

**Do professional systems order automatically?** Mostly they *prepare* the order automatically: they
find what is below its reorder point (or par level), group the items by each item's vendor into one PO
per vendor, and fill in quantities and contract prices. A buyer approves, often only the exceptions
(expensive or unusual orders), and the PO goes to the vendor electronically (EDI).
MedStock works the same way; the sidebar setting lets you try all three levels of automation.

**Is the sample data real?** No. It is a realistic, made-up US hospital with 30 items, 3 years of usage,
a yearly flu season and a summer peak for trauma supplies.

---

## 11. Current limitations

- One delivery is received as one lot. A delivery with two lot numbers must be received as two partial deliveries.
- Each item has one primary and one backup vendor; real systems may have several, plus approved substitute items.
- A recall pulls the lot from the storeroom only; stock already on ward shelves is not tracked (wards are listed to notify).
- No invoices or three-way match (PO = receipt = invoice), and no rounding to case packs.
- Vendors, the hospital and their behaviour are fictional and simulated.
- Sidebar settings are not saved between sessions.
- Sign-in is a simple gate: everyone who signs in has full access (no roles such as buyer or approver).
- MedStock runs on one computer. To share it, it must be deployed to a server.
