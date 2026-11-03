# Build log

How MedStock was built, in order: what I added, what broke and what I changed because of it. The
newest entry is at the bottom. For what the app does today, see the [README](../README.md). For
the formulas, see [How It Works](HOW_IT_WORKS.md).

Each entry has three parts:
- **Built:** what changed
- **Problem:** what went wrong or what I learned, if anything
- **Decision:** what I chose and why

---

## 1. Formulas from the course

**Date:** November 1, 2026

**Built:** The calculation engine in `inventory_math.py`: EOQ, total cost, safety stock and reorder
point under uncertain demand and lead time, the loss function, fill rate, the newsvendor model and
ABC classification. I used the professor's notation so the code reads like the slides.

**Decision:** Every formula test uses a worked example from the course deck as its expected value.
If a test fails, the code is wrong, not the example. This is still the rule in `AGENTS.md`.

## 2. A fictional hospital and its stock

**Date:** November 1, 2026

**Built:** A synthetic US hospital with 30 supplies from four made-up vendors, stored in SQLite.
Stock is kept as lots with lot numbers and expiry dates and issued earliest-expiry first (FEFO).
Every movement writes a ledger row that is never deleted.

**Problem:** Hospital supplies expire. An order quantity that looks cheapest by EOQ can leave stock
on the shelf past its expiry date.

**Decision:** Order quantities are capped by shelf life, and the Expiry tab projects which lots
will expire before they can be used. I also added VED criticality (Vital, Essential, Desirable) so
a ventilator circuit gets a higher service level than a box of gauze. Neither of these came from
the course.

## 3. Forecasting

**Date:** November 1, 2026

**Built:** Moving average, exponential smoothing, Holt and Winters from the forecasting unit. The
app backtests all four on each item's history and uses the one that would have been most accurate.

**Problem:** When an item runs out, recorded usage drops, and the forecast learns that demand fell.
It then orders less, which causes more stockouts.

**Decision:** Unmet demand is recorded as usage, so the forecast sees what the wards asked for, not
only what they got.

## 4. Purchasing and the simulation clock

**Date:** November 1, 2026

**Built:** One purchase order per vendor, built from the reorder plan and approved by the user.
Simulated vendors acknowledge, ship, sometimes run late and sometimes send less than ordered. The
flow is modeled on the EDI messages real hospitals use (850 order, 855 acknowledgement, 856 ship
notice). A simulation clock moves the hospital forward day by day so I can see whether the reorder
decisions hold up.

**Problem:** At first, reloading the page could change what a vendor did with an order.

**Decision:** Each order's story (delays, short shipments) is decided once, when the order is sent,
from a random generator seeded by the order number. The clock then reveals it day by day.

## 5. A data loss, and a guard against it

**Date:** November 1, 2026

**Problem:** Two AI assistants were editing the project at the same time, and a test run opened my
real database and wiped my simulated history.

**Decision:** `conftest.py` now makes any test that tries to open the real database fail. Every
test runs on a temporary copy. The first working rule in `AGENTS.md` is "one assistant at a time",
and the second is to back up the database before risky work.

## 6. Sign-in and the public homepage

**Date:** November 1, 2026

**Built:** A public homepage that explains the project, and an invite-only demo behind a sign-in.
Passwords are stored only as salted PBKDF2 hashes in a secrets file that is never committed.

**Decision:** Credentials are shared privately and never written in the code or the docs.

## 7. Two bugs found by using the app

**Date:** November 1, 2026

**Problem 1:** The dashboard filters didn't seem to do anything. The first fix made them strict,
but filtering for "OK" still didn't bring OK items to the top. The real cause was that two columns
both showed "🟢 OK", and the one being filtered was the second column, so the table looked
unchanged.

**Decision:** Reorder status became the first column, the availability label became "Enough stock",
and I added a Sort by option. Lesson: a filter can work correctly and still look broken.

**Problem 2:** After approving one vendor's draft order, the Purchasing screen stayed on that vendor
instead of moving to the next draft.

**Decision:** Drafts are listed first, and after an order is approved or deleted the screen opens
the next draft. Both bugs now have tests.

## 8. Recalls, vendor outages and KPIs

**Date:** November 1, 2026

**Built:** I wanted to see what happens when things go wrong in the supply chain.
- **Recalls:** a recalled lot is pulled from the shelf, the app lists which wards already received
  it, and any delivery with that lot number is refused at the dock.
- **Vendor outages:** orders sent to a vendor during an outage are rejected, and new orders go to
  each item's backup vendor at a 12% higher price.
- **KPIs:** fill rate, stockouts, inventory turns, days on hand, waste and vendor on-time delivery,
  with weekly trends.
- **Random events:** the simulation can trigger recalls and outages on its own.

**Decision:** A recall is a loss, not demand, so it doesn't inflate the forecast. The backup vendor
is used only during an outage, which shows the cost of supply risk without complicating normal
ordering.

## 9. Going live

**Date:** November 1, 2026

**Built:** Published the code to a public GitHub repo and deployed it on Streamlit Community
Cloud. Every push to `main` updates the live app.

**Decision:** The secrets file and databases are excluded from git, and commits use GitHub's
private noreply email. The live demo starts from fresh sample data, not my own history.

**Known limit:** All visitors share one database on the live app, and it resets when the app
restarts.

## 10. Writing and documentation

**Date:** November 1 and 2, 2026

**Built:** I rewrote the homepage and README in plain, first-person language. I took out long
dashes, arrows and phrasing that sounds machine-written, and fixed plurals such as "1 items". I
added a clear split between what came from the course and what I added. I also added `AGENTS.md`,
a guide so any collaborator or AI assistant can pick up the project, and this build log.

**Decision:** MedStock isn't finished. The roadmap is in the README and in `AGENTS.md`, and each
new feature gets an entry here.

## 11. A new look

**Date:** November 2 and 3, 2026

**Built:** I mocked up a cleaner design first, then rebuilt the app to match it.
- **Logo and colors:** a new logo (a supply box with a medical cross) and a violet theme with
  red, amber, green and blue accents.
- **Navigation:** the 12 pages moved from tabs to a menu in the sidebar, with the simulation clock
  under it. Only the open page is drawn, which also makes the app faster.
- **Icons:** my own icon set in place of emojis, with a colored tile for each page and KPI card.
- **KPI page:** a clearer text hierarchy, with section headers that say which question each group
  of numbers answers.
- **Homepage:** rebuilt in a corporate style, with a workflow diagram of a simulated day.

**Problem:** Drawing only the open page meant one page could no longer borrow a name set up by
another. I also named the menu function `go`, which overwrote the chart library and broke three
pages.

**Decision:** I added a test that opens every page from the menu, so a page that depends on
another page fails right away.

## 12. One delivery, several lots

**Date:** November 3, 2026

**Built:** A delivery line can now arrive as two or three lots from different production runs,
each with its own expiry date. About 3 in 10 shipped lines are split this way. The vendor's ship
notice lists every lot, receiving puts each lot on the shelf separately, and the manual receive
form has a lots table where you can add or change rows.

**Problem:** Two things could have gone quietly wrong. Receiving three lots as three separate
deliveries would have counted three lead-time samples for one truck and skewed σL. And a recall
of the second lot in a delivery would have been missed, because the old check only looked at the
first lot.

**Decision:** A multi-lot receipt is one delivery with one ledger row, and every lot is checked
before anything is saved. Recalls now check every lot on the way and refuse only the recalled
one. The split uses its own random numbers, so it does not change any vendor's dates or
quantities, and a test proves that.

## 13. From 30 to 150 items

**Date:** November 3, 2026

**Built:** The sample catalog grew from 30 to 150 items in six categories: medicines, IV fluids,
consumables, laboratory, and two new ones, surgical and respiratory supplies. Generic names only,
the same four fictional vendors, three years of daily usage for every item.

**Decision:** The new items were added after the original 30 in the generator. The generator uses
a fixed random seed and draws numbers in list order, so the original 30 items kept exactly the
same history, row for row, and every existing test stayed valid. I checked that by comparing the
old and new files. The homepage now counts the items from the catalog instead of saying "30".
