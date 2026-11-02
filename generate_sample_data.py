"""
generate_sample_data.py: Creates a realistic (but fake) US hospital supply dataset.

Run once:   .venv/bin/python generate_sample_data.py
It writes four CSV files into the data/ folder:

  items.csv       the item master list (cost, VED class, supplier, shelf life)
  usage.csv       three years of daily usage per item (Nov 2023 - Oct 2026)
  deliveries.csv  past purchase orders with order date and received date
                  (this is where lead time and its variability come from)
  lots.csv        the stock on the shelf TODAY, split into lots (batches),
                  each with a lot number and an expiry date

Realism built in:
  - prices in US dollars, roughly typical hospital acquisition costs
  - fewer elective procedures on weekends
  - slow growth: about +4% demand per year
  - a flu season (peak in January) that drives up IV fluids, acetaminophen,
    flu tests, masks and N95s. Every year's flu season has a different
    severity, so the past never repeats exactly.
  - a summer peak (more trauma cases) for sutures, gauze and blood bags
  - suppliers with different reliability (fast regional vs. slow overseas)
  - a few lots that are expired or close to expiry, so the expiry
    screen has something to show
"""

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

rng = np.random.default_rng(42)          # fixed seed -> same data every run
DATA = Path(__file__).parent / "data"
DATA.mkdir(exist_ok=True)

TODAY = date(2026, 11, 1)
START = date(2023, 11, 1)
HISTORY_DAYS = (TODAY - START).days

# Monthly multipliers for each seasonal pattern (month number -> extra demand)
FLU_SEASON = {11: 1.15, 12: 1.5, 1: 1.75, 2: 1.45, 3: 1.15}
SUMMER_PEAK = {6: 1.2, 7: 1.3, 8: 1.25}
GROWTH_PER_YEAR = 0.04
# Flu severity per season (the season starting in Nov of that year): mild, severe, average
FLU_SEVERITY = {2023: 0.8, 2024: 1.3, 2025: 1.0, 2026: 1.0}

# Suppliers (fictional): (average lead time in days, std. dev. of lead time in days)
SUPPLIERS = {
    "Northwest Medical Distributors": (2, 0.6),
    "Pacific Pharma Supply": (4, 1.2),
    "Cascade Surgical Supply": (7, 2.5),
    "Overseas Medical Imports": (21, 7.0),
}

# VED: V = Vital (patient harm if missing), E = Essential, D = Desirable
# Columns: id, name, category, unit, unit cost USD, ordering cost USD,
#          avg daily use (today's level), VED, shelf life days, supplier,
#          seasonal pattern ("flu", "summer" or None)
ITEMS = [
    ("MED001", "Acetaminophen 500mg tab", "Medicine", "bottle/100", 5.00, 30, 6, "E", 1095, "Pacific Pharma Supply", "flu"),
    ("MED002", "Acetaminophen IV 1g vial", "Medicine", "vial", 9.00, 30, 14, "V", 730, "Pacific Pharma Supply", "flu"),
    ("MED003", "Amoxicillin 500mg cap", "Medicine", "bottle/100", 12.00, 30, 3, "E", 730, "Pacific Pharma Supply", None),
    ("MED004", "Ceftriaxone 1g vial", "Medicine", "vial", 2.50, 30, 30, "V", 730, "Pacific Pharma Supply", None),
    ("MED005", "Meropenem 1g vial", "Medicine", "vial", 15.00, 60, 6, "V", 730, "Overseas Medical Imports", None),
    ("MED006", "Pantoprazole IV 40mg vial", "Medicine", "vial", 6.00, 30, 18, "E", 730, "Pacific Pharma Supply", None),
    ("MED007", "Insulin regular 10mL vial", "Medicine", "vial", 35.00, 40, 4, "V", 365, "Northwest Medical Distributors", None),
    ("MED008", "Epinephrine 1mg/10mL syringe", "Medicine", "syringe", 15.00, 30, 3, "V", 545, "Northwest Medical Distributors", None),
    ("MED009", "Oxytocin 10 units vial", "Medicine", "vial", 2.00, 30, 5, "V", 365, "Northwest Medical Distributors", None),
    ("MED010", "Heparin 5,000 units vial", "Medicine", "vial", 3.00, 40, 5, "V", 730, "Overseas Medical Imports", None),
    ("MED011", "Albumin 25% 50mL", "Medicine", "bottle", 60.00, 60, 1.2, "E", 1095, "Overseas Medical Imports", None),
    ("MED012", "Ondansetron 4mg vial", "Medicine", "vial", 1.00, 30, 8, "D", 730, "Pacific Pharma Supply", None),
    ("IVF001", "Sodium chloride 0.9% 1L", "IV Fluids", "bag", 3.00, 50, 60, "V", 730, "Cascade Surgical Supply", "flu"),
    ("IVF002", "Lactated Ringer's 1L", "IV Fluids", "bag", 3.50, 50, 45, "V", 730, "Cascade Surgical Supply", "flu"),
    ("IVF003", "Dextrose 5% 1L", "IV Fluids", "bag", 3.50, 50, 25, "E", 730, "Cascade Surgical Supply", "flu"),
    ("CON001", "Syringe 5mL", "Consumables", "box/100", 15.00, 25, 2.5, "V", 1825, "Northwest Medical Distributors", None),
    ("CON002", "IV catheter 22G", "Consumables", "box/50", 90.00, 25, 1.6, "V", 1825, "Northwest Medical Distributors", "flu"),
    ("CON003", "IV administration set", "Consumables", "each", 4.00, 25, 55, "V", 1825, "Northwest Medical Distributors", "flu"),
    ("CON004", "Nitrile exam gloves (M)", "Consumables", "box/100", 8.00, 25, 12, "E", 1095, "Overseas Medical Imports", None),
    ("CON005", "Surgical mask", "Consumables", "box/50", 6.00, 25, 6, "D", 1095, "Northwest Medical Distributors", "flu"),
    ("CON006", "N95 respirator", "Consumables", "box/20", 25.00, 25, 0.8, "E", 1095, "Overseas Medical Imports", "flu"),
    ("CON007", "Sterile gauze 4x4", "Consumables", "pack/100", 10.00, 25, 4, "E", 1825, "Cascade Surgical Supply", "summer"),
    ("CON008", "Foley catheter tray 16Fr", "Consumables", "each", 12.00, 25, 6, "E", 1825, "Cascade Surgical Supply", None),
    ("CON009", "Absorbable suture 2-0", "Consumables", "box/12", 120.00, 30, 0.7, "E", 1825, "Overseas Medical Imports", "summer"),
    ("CON010", "Isopropyl alcohol 70% 1 pint", "Consumables", "bottle", 3.00, 25, 10, "D", 1095, "Northwest Medical Distributors", None),
    ("CON011", "Cotton balls 300ct", "Consumables", "bag", 4.00, 25, 5, "D", 1825, "Northwest Medical Distributors", None),
    ("CON012", "Medical tape 1in", "Consumables", "roll", 2.00, 25, 9, "D", 1825, "Northwest Medical Distributors", None),
    ("LAB001", "Influenza A/B rapid test", "Laboratory", "test", 15.00, 30, 7, "V", 540, "Pacific Pharma Supply", "flu"),
    ("LAB002", "Glucose test strips", "Laboratory", "box/50", 25.00, 30, 1.5, "E", 540, "Pacific Pharma Supply", None),
    ("LAB003", "Blood collection bag 450mL", "Laboratory", "bag", 20.00, 30, 4, "V", 1095, "Cascade Surgical Supply", "summer"),
]

# Items that get an "expiry problem" lot, to make the expiry screen interesting:
# item_id -> days until expiry of its oldest lot (negative = already expired)
EXPIRY_PROBLEMS = {"MED007": -5, "LAB001": 12, "MED011": 25, "MED009": 40, "LAB002": 55, "MED008": 80}


def daily_usage(mean, season):
    """Three years of daily usage for one item."""
    rows = []
    for k in range(HISTORY_DAYS):
        day = START + timedelta(days=k)
        years_ago = (TODAY - day).days / 365
        m = mean / (1 + GROWTH_PER_YEAR) ** years_ago      # demand was a bit lower in the past
        if day.weekday() >= 5:                              # weekend: fewer elective cases
            m *= 0.8
        if season == "flu" and day.month in FLU_SEASON:
            season_year = day.year if day.month >= 11 else day.year - 1
            extra = FLU_SEASON[day.month] - 1
            m *= 1 + extra * FLU_SEVERITY[season_year]      # flu surge, stronger in bad years
        elif season == "summer" and day.month in SUMMER_PEAK:
            m *= SUMMER_PEAK[day.month]
        # Negative binomial gives "lumpy" counts like real hospital usage
        n = 8
        qty = rng.negative_binomial(n, n / (n + m)) if m > 0 else 0
        rows.append((day, qty))
    return rows


def make_lots(iid, on_hand, mean, shelf_life):
    """Split today's stock into 1-3 lots. Older lots expire sooner."""
    n = min(int(rng.integers(1, 4)), max(1, on_hand))
    cuts = sorted(rng.choice(np.arange(1, on_hand), size=n - 1, replace=False)) if n > 1 else []
    sizes = np.diff([0, *cuts, on_hand])
    lots = []
    for k, qty in enumerate(sizes):
        # Days until expiry: the newest lot has most of its shelf life left
        days_left = int(shelf_life * rng.uniform(0.35, 0.95)) - (len(sizes) - 1 - k) * 30
        if k == 0 and iid in EXPIRY_PROBLEMS:
            days_left = EXPIRY_PROBLEMS[iid]
            # make the problem lot big enough that some of it will really go to waste
            qty = max(int(qty), int(mean * max(days_left, 0) + mean * 10))
        lots.append({
            "item_id": iid,
            "lot_no": f"L{rng.integers(10000, 99999)}",
            "expiry_date": TODAY + timedelta(days=max(days_left, -30)),
            "qty": int(qty),
            "received_date": TODAY - timedelta(days=int(rng.integers(5, 120))),
        })
    return lots


def main():
    items, usage, deliveries, lots = [], [], [], []
    po = 1000
    for (iid, name, cat, unit, cost, s, mean, ved, life, sup, season) in ITEMS:
        for day, qty in daily_usage(mean, season):
            usage.append({"date": day, "item_id": iid, "qty_used": qty})

        # Past purchase orders roughly every 2-4 weeks, with random lead times
        L, sL = SUPPLIERS[sup]
        d = START + timedelta(days=int(rng.integers(0, 10)))
        while d < TODAY - timedelta(days=30):
            lt = max(1, round(rng.normal(L, sL)))
            deliveries.append({
                "po_id": f"PO{po}", "item_id": iid, "supplier": sup,
                "order_date": d, "received_date": d + timedelta(days=lt),
                "lead_time_days": lt,
            })
            po += 1
            d += timedelta(days=int(rng.integers(14, 30)))

        # Stock on hand today: between 2 and 45 days of supply, split into lots
        on_hand = max(2, int(mean * rng.uniform(2, 45)))
        lots += make_lots(iid, on_hand, mean, life)
        items.append({
            "item_id": iid, "name": name, "category": cat, "unit": unit,
            "unit_cost": cost, "ordering_cost": s, "holding_rate": 0.25,
            "ved": ved, "shelf_life_days": life, "supplier": sup,
        })

    pd.DataFrame(items).to_csv(DATA / "items.csv", index=False)
    pd.DataFrame(usage).to_csv(DATA / "usage.csv", index=False)
    pd.DataFrame(deliveries).to_csv(DATA / "deliveries.csv", index=False)
    pd.DataFrame(lots).to_csv(DATA / "lots.csv", index=False)
    print(f"Wrote {len(items)} items, {len(usage)} usage rows, {len(deliveries)} deliveries, "
          f"{len(lots)} lots to {DATA}")


if __name__ == "__main__":
    main()
