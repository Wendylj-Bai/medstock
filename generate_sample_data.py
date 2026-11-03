"""
generate_sample_data.py: Creates a realistic (but fake) US hospital supply dataset.

Run once:   .venv/bin/python generate_sample_data.py
It writes four CSV files into the data/ folder:

  items.csv       the item master list: 150 items (cost, VED class, supplier, shelf life)
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

# Catalog expansion (November 2026): 120 more items, added AFTER the original 30 so the original
# items keep exactly the same random history (the generator draws numbers in list order).
ITEMS += [
    ("MED013", "Vancomycin 1g vial", "Medicine", "vial", 8.00, 30, 10, "V", 730, "Pacific Pharma Supply", None),
    ("MED014", "Piperacillin-tazobactam 3.375g vial", "Medicine", "vial", 9.00, 30, 14, "V", 730, "Overseas Medical Imports", None),
    ("MED015", "Cefazolin 1g vial", "Medicine", "vial", 2.00, 30, 25, "V", 730, "Pacific Pharma Supply", None),
    ("MED016", "Azithromycin 500mg vial", "Medicine", "vial", 11.00, 30, 4, "E", 730, "Pacific Pharma Supply", "flu"),
    ("MED017", "Levofloxacin 500mg tab", "Medicine", "bottle/50", 14.00, 30, 1.5, "E", 1095, "Pacific Pharma Supply", None),
    ("MED018", "Metronidazole IV 500mg bag", "Medicine", "bag", 4.00, 30, 8, "E", 730, "Pacific Pharma Supply", None),
    ("MED019", "Morphine 4mg/mL syringe", "Medicine", "syringe", 3.00, 40, 12, "V", 545, "Northwest Medical Distributors", None),
    ("MED020", "Hydromorphone 1mg/mL syringe", "Medicine", "syringe", 4.00, 40, 9, "V", 545, "Northwest Medical Distributors", None),
    ("MED021", "Fentanyl 100mcg/2mL vial", "Medicine", "vial", 2.50, 40, 10, "V", 730, "Northwest Medical Distributors", None),
    ("MED022", "Ketorolac 30mg vial", "Medicine", "vial", 1.50, 30, 12, "E", 730, "Pacific Pharma Supply", None),
    ("MED023", "Ibuprofen 800mg tab", "Medicine", "bottle/100", 9.00, 30, 2, "D", 1095, "Pacific Pharma Supply", None),
    ("MED024", "Oxycodone 5mg tab", "Medicine", "bottle/100", 18.00, 40, 1.8, "E", 1095, "Northwest Medical Distributors", None),
    ("MED025", "Lorazepam 2mg/mL vial", "Medicine", "vial", 4.00, 40, 5, "E", 545, "Northwest Medical Distributors", None),
    ("MED026", "Midazolam 5mg/mL vial", "Medicine", "vial", 2.00, 40, 8, "V", 730, "Northwest Medical Distributors", None),
    ("MED027", "Propofol 200mg/20mL vial", "Medicine", "vial", 3.50, 40, 15, "V", 730, "Overseas Medical Imports", None),
    ("MED028", "Rocuronium 50mg vial", "Medicine", "vial", 9.00, 40, 6, "V", 545, "Overseas Medical Imports", None),
    ("MED029", "Lidocaine 1% 20mL vial", "Medicine", "vial", 1.50, 30, 14, "E", 730, "Pacific Pharma Supply", None),
    ("MED030", "Furosemide 40mg/4mL vial", "Medicine", "vial", 1.20, 30, 10, "E", 730, "Pacific Pharma Supply", None),
    ("MED031", "Metoprolol 5mg/5mL vial", "Medicine", "vial", 1.80, 30, 6, "E", 730, "Pacific Pharma Supply", None),
    ("MED032", "Amiodarone 150mg/3mL vial", "Medicine", "vial", 4.50, 30, 3, "V", 730, "Pacific Pharma Supply", None),
    ("MED033", "Atropine 1mg/10mL syringe", "Medicine", "syringe", 12.00, 30, 1.5, "V", 545, "Northwest Medical Distributors", None),
    ("MED034", "Naloxone 0.4mg/mL vial", "Medicine", "vial", 9.00, 30, 2, "V", 730, "Northwest Medical Distributors", None),
    ("MED035", "Dexamethasone 4mg/mL vial", "Medicine", "vial", 1.00, 30, 9, "E", 730, "Pacific Pharma Supply", None),
    ("MED036", "Methylprednisolone 125mg vial", "Medicine", "vial", 6.00, 30, 4, "E", 730, "Pacific Pharma Supply", "flu"),
    ("MED037", "Enoxaparin 40mg syringe", "Medicine", "syringe", 7.00, 30, 20, "V", 730, "Overseas Medical Imports", None),
    ("MED038", "Potassium chloride 20mEq tab", "Medicine", "bottle/100", 10.00, 30, 2.5, "E", 1095, "Pacific Pharma Supply", None),
    ("MED039", "Magnesium sulfate 2g/50mL bag", "Medicine", "bag", 6.00, 30, 6, "E", 730, "Pacific Pharma Supply", None),
    ("MED040", "Famotidine 20mg/2mL vial", "Medicine", "vial", 1.20, 30, 10, "D", 730, "Pacific Pharma Supply", None),
    ("MED041", "Diphenhydramine 50mg/mL vial", "Medicine", "vial", 1.00, 30, 5, "D", 730, "Pacific Pharma Supply", None),
    ("MED042", "Albuterol 2.5mg/3mL nebule", "Medicine", "box/25", 6.00, 30, 3, "V", 730, "Pacific Pharma Supply", "flu"),
    ("MED043", "Oseltamivir 75mg cap", "Medicine", "box/10", 28.00, 30, 2, "E", 1095, "Pacific Pharma Supply", "flu"),
    ("MED044", "Norepinephrine 4mg/4mL vial", "Medicine", "vial", 8.00, 40, 4, "V", 545, "Overseas Medical Imports", None),
    ("MED045", "Tetanus-diphtheria vaccine", "Medicine", "vial", 32.00, 40, 1, "E", 365, "Northwest Medical Distributors", "summer"),
    ("IVF004", "Sodium chloride 0.9% 500mL", "IV Fluids", "bag", 2.50, 50, 30, "V", 730, "Cascade Surgical Supply", "flu"),
    ("IVF005", "Sodium chloride 0.9% 100mL", "IV Fluids", "bag", 1.80, 50, 40, "E", 730, "Cascade Surgical Supply", None),
    ("IVF006", "Dextrose 5% / 0.45% NaCl 1L", "IV Fluids", "bag", 3.80, 50, 12, "E", 730, "Cascade Surgical Supply", None),
    ("IVF007", "Lactated Ringer's 500mL", "IV Fluids", "bag", 3.00, 50, 15, "V", 730, "Northwest Medical Distributors", "flu"),
    ("IVF008", "Sterile water for injection 1L", "IV Fluids", "bag", 3.20, 50, 6, "D", 730, "Northwest Medical Distributors", None),
    ("IVF009", "Dextrose 50% 50mL syringe", "IV Fluids", "syringe", 6.00, 40, 2, "V", 545, "Northwest Medical Distributors", None),
    ("IVF010", "Sodium bicarbonate 8.4% 50mL syringe", "IV Fluids", "syringe", 9.00, 40, 2, "V", 545, "Northwest Medical Distributors", None),
    ("CON013", "Syringe 10mL", "Consumables", "box/100", 18.00, 25, 2.2, "V", 1825, "Northwest Medical Distributors", None),
    ("CON014", "Syringe 3mL with needle", "Consumables", "box/100", 16.00, 25, 2, "E", 1825, "Northwest Medical Distributors", None),
    ("CON015", "Hypodermic needle 18G", "Consumables", "box/100", 7.00, 25, 1.8, "E", 1825, "Northwest Medical Distributors", None),
    ("CON016", "Hypodermic needle 25G", "Consumables", "box/100", 7.00, 25, 1.5, "E", 1825, "Northwest Medical Distributors", None),
    ("CON017", "Insulin syringe 1mL", "Consumables", "box/100", 20.00, 25, 1.2, "V", 1825, "Northwest Medical Distributors", None),
    ("CON018", "IV catheter 20G", "Consumables", "box/50", 90.00, 25, 1.3, "V", 1825, "Northwest Medical Distributors", "flu"),
    ("CON019", "IV catheter 18G", "Consumables", "box/50", 95.00, 25, 0.8, "V", 1825, "Northwest Medical Distributors", None),
    ("CON020", "Saline flush 10mL syringe", "Consumables", "box/30", 9.00, 25, 8, "V", 1095, "Northwest Medical Distributors", None),
    ("CON021", "Nitrile exam gloves (S)", "Consumables", "box/100", 8.00, 25, 8, "E", 1095, "Overseas Medical Imports", None),
    ("CON022", "Nitrile exam gloves (L)", "Consumables", "box/100", 8.00, 25, 10, "E", 1095, "Overseas Medical Imports", None),
    ("CON023", "Isolation gown", "Consumables", "box/10", 9.00, 25, 14, "E", 1825, "Overseas Medical Imports", "flu"),
    ("CON024", "Face shield", "Consumables", "box/24", 18.00, 25, 1, "E", 1825, "Overseas Medical Imports", "flu"),
    ("CON025", "Alcohol prep pad", "Consumables", "box/200", 3.00, 25, 6, "D", 1095, "Northwest Medical Distributors", None),
    ("CON026", "Chlorhexidine prep applicator", "Consumables", "box/25", 22.00, 25, 2, "E", 1095, "Cascade Surgical Supply", None),
    ("CON027", "Transparent dressing 4x4in", "Consumables", "box/50", 30.00, 25, 1.5, "E", 1825, "Cascade Surgical Supply", None),
    ("CON028", "Adhesive bandage 1x3in", "Consumables", "box/100", 4.00, 25, 2, "D", 1825, "Northwest Medical Distributors", None),
    ("CON029", "Elastic bandage 4in", "Consumables", "each", 2.00, 25, 6, "D", 1825, "Cascade Surgical Supply", "summer"),
    ("CON030", "Abdominal pad 8x10in", "Consumables", "box/20", 9.00, 25, 2, "E", 1825, "Cascade Surgical Supply", "summer"),
    ("CON031", "Specimen cup 4oz", "Consumables", "box/100", 18.00, 25, 1.5, "D", 1825, "Northwest Medical Distributors", None),
    ("CON032", "Urine collection bag 2000mL", "Consumables", "each", 2.50, 25, 6, "E", 1825, "Cascade Surgical Supply", None),
    ("CON033", "Nasogastric tube 16Fr", "Consumables", "each", 3.00, 25, 2, "E", 1825, "Cascade Surgical Supply", None),
    ("CON034", "Suction catheter 14Fr", "Consumables", "each", 1.20, 25, 12, "V", 1825, "Cascade Surgical Supply", None),
    ("CON035", "Sharps container 1 gal", "Consumables", "each", 4.00, 25, 5, "E", 1825, "Northwest Medical Distributors", None),
    ("CON036", "Disposable underpad 23x36in", "Consumables", "case/150", 38.00, 25, 1.2, "D", 1825, "Overseas Medical Imports", None),
    ("CON037", "Patient ID wristband", "Consumables", "box/500", 45.00, 25, 0.2, "E", 1825, "Northwest Medical Distributors", None),
    ("CON038", "Bedside commode liner", "Consumables", "box/50", 15.00, 25, 0.6, "D", 1825, "Overseas Medical Imports", None),
    ("CON039", "Hand sanitizer 16oz", "Consumables", "bottle", 5.00, 25, 8, "E", 1095, "Northwest Medical Distributors", "flu"),
    ("CON040", "Disinfectant wipes canister", "Consumables", "canister", 7.00, 25, 9, "E", 730, "Northwest Medical Distributors", "flu"),
    ("LAB004", "COVID-19 antigen test", "Laboratory", "test", 9.00, 30, 6, "E", 540, "Pacific Pharma Supply", "flu"),
    ("LAB005", "Strep A rapid test", "Laboratory", "test", 6.00, 30, 3, "E", 540, "Pacific Pharma Supply", "flu"),
    ("LAB006", "RSV rapid test", "Laboratory", "test", 12.00, 30, 2, "E", 540, "Pacific Pharma Supply", "flu"),
    ("LAB007", "Urine pregnancy test", "Laboratory", "test", 1.00, 30, 3, "E", 730, "Pacific Pharma Supply", None),
    ("LAB008", "Blood culture bottle set", "Laboratory", "set", 14.00, 30, 4, "V", 540, "Pacific Pharma Supply", None),
    ("LAB009", "EDTA tube 4mL (lavender top)", "Laboratory", "box/100", 22.00, 30, 1.2, "E", 545, "Northwest Medical Distributors", None),
    ("LAB010", "Serum tube 5mL (gold top)", "Laboratory", "box/100", 26.00, 30, 1.2, "E", 545, "Northwest Medical Distributors", None),
    ("LAB011", "Citrate tube 2.7mL (blue top)", "Laboratory", "box/100", 24.00, 30, 0.6, "E", 545, "Northwest Medical Distributors", None),
    ("LAB012", "Blood gas syringe", "Laboratory", "box/100", 120.00, 30, 0.3, "V", 730, "Northwest Medical Distributors", None),
    ("LAB013", "Urinalysis reagent strips", "Laboratory", "bottle/100", 35.00, 30, 0.4, "E", 730, "Pacific Pharma Supply", None),
    ("LAB014", "Lancet 21G", "Laboratory", "box/200", 10.00, 30, 0.8, "D", 1095, "Pacific Pharma Supply", None),
    ("LAB015", "Glucometer control solution", "Laboratory", "bottle", 9.00, 30, 0.3, "E", 365, "Pacific Pharma Supply", None),
    ("LAB016", "Troponin I test cartridge", "Laboratory", "box/25", 160.00, 30, 0.3, "V", 365, "Pacific Pharma Supply", None),
    ("LAB017", "Swab transport media", "Laboratory", "box/50", 40.00, 30, 0.5, "E", 545, "Pacific Pharma Supply", "flu"),
    ("LAB018", "Blood bank crossmatch tube", "Laboratory", "box/100", 30.00, 30, 0.4, "V", 545, "Cascade Surgical Supply", "summer"),
    ("SUR001", "Sterile surgical gown (L)", "Surgical", "each", 4.50, 30, 18, "E", 1825, "Cascade Surgical Supply", "summer"),
    ("SUR002", "Sterile surgical gloves size 7", "Surgical", "box/50", 55.00, 30, 0.8, "V", 1825, "Overseas Medical Imports", None),
    ("SUR003", "Sterile surgical gloves size 7.5", "Surgical", "box/50", 55.00, 30, 0.9, "V", 1825, "Overseas Medical Imports", None),
    ("SUR004", "Scalpel blade #10", "Surgical", "box/100", 25.00, 30, 0.4, "V", 1825, "Cascade Surgical Supply", None),
    ("SUR005", "Scalpel blade #15", "Surgical", "box/100", 25.00, 30, 0.5, "V", 1825, "Cascade Surgical Supply", None),
    ("SUR006", "Electrosurgical pencil", "Surgical", "each", 6.00, 30, 10, "V", 1825, "Cascade Surgical Supply", None),
    ("SUR007", "Grounding pad (adult)", "Surgical", "each", 4.00, 30, 10, "V", 1825, "Cascade Surgical Supply", None),
    ("SUR008", "Laparotomy sponge 18x18in", "Surgical", "pack/5", 6.00, 30, 12, "E", 1825, "Cascade Surgical Supply", "summer"),
    ("SUR009", "Nonabsorbable suture 3-0", "Surgical", "box/12", 95.00, 30, 0.5, "E", 1825, "Overseas Medical Imports", "summer"),
    ("SUR010", "Skin stapler 35W", "Surgical", "each", 18.00, 30, 3, "E", 1825, "Overseas Medical Imports", "summer"),
    ("SUR011", "Surgical drape sheet", "Surgical", "each", 5.00, 30, 14, "E", 1825, "Cascade Surgical Supply", None),
    ("SUR012", "Basic surgical pack", "Surgical", "each", 45.00, 40, 6, "V", 1825, "Cascade Surgical Supply", None),
    ("SUR013", "Laparoscopic trocar 12mm", "Surgical", "each", 85.00, 40, 1.5, "V", 1825, "Overseas Medical Imports", None),
    ("SUR014", "Bone wax 2.5g", "Surgical", "box/12", 60.00, 30, 0.1, "E", 1825, "Overseas Medical Imports", None),
    ("SUR015", "Hemostatic gauze 2x14in", "Surgical", "each", 40.00, 30, 0.8, "V", 1095, "Overseas Medical Imports", "summer"),
    ("SUR016", "Surgical skin marker with ruler", "Surgical", "box/25", 30.00, 30, 0.4, "D", 1825, "Northwest Medical Distributors", None),
    ("SUR017", "Wound drain 15Fr", "Surgical", "each", 22.00, 30, 1.2, "E", 1825, "Cascade Surgical Supply", None),
    ("SUR018", "Bouffant surgical cap", "Surgical", "box/100", 9.00, 25, 2.5, "D", 1825, "Northwest Medical Distributors", None),
    ("SUR019", "Shoe covers", "Surgical", "box/100", 8.00, 25, 2, "D", 1825, "Northwest Medical Distributors", None),
    ("SUR020", "Sterilization wrap 24x24in", "Surgical", "case/500", 140.00, 30, 0.1, "E", 1825, "Overseas Medical Imports", None),
    ("RES001", "Nasal cannula (adult)", "Respiratory", "each", 1.20, 25, 25, "V", 1825, "Northwest Medical Distributors", "flu"),
    ("RES002", "Simple oxygen mask (adult)", "Respiratory", "each", 1.80, 25, 10, "V", 1825, "Northwest Medical Distributors", "flu"),
    ("RES003", "Non-rebreather mask", "Respiratory", "each", 2.50, 25, 5, "V", 1825, "Northwest Medical Distributors", "flu"),
    ("RES004", "Nebulizer kit", "Respiratory", "each", 2.00, 25, 8, "E", 1825, "Northwest Medical Distributors", "flu"),
    ("RES005", "Oxygen tubing 7ft", "Respiratory", "each", 0.90, 25, 15, "E", 1825, "Northwest Medical Distributors", "flu"),
    ("RES006", "Bag-valve mask (adult)", "Respiratory", "each", 14.00, 30, 0.6, "V", 1825, "Cascade Surgical Supply", None),
    ("RES007", "Endotracheal tube 7.5mm", "Respiratory", "each", 3.00, 30, 1.5, "V", 1825, "Cascade Surgical Supply", "flu"),
    ("RES008", "Endotracheal tube 7.0mm", "Respiratory", "each", 3.00, 30, 1.2, "V", 1825, "Cascade Surgical Supply", None),
    ("RES009", "Oropharyngeal airway kit", "Respiratory", "kit", 8.00, 30, 0.5, "V", 1825, "Cascade Surgical Supply", None),
    ("RES010", "Ventilator circuit (adult)", "Respiratory", "each", 22.00, 30, 2, "V", 1825, "Overseas Medical Imports", "flu"),
    ("RES011", "Heat moisture exchanger filter", "Respiratory", "each", 3.00, 30, 6, "V", 1825, "Overseas Medical Imports", "flu"),
    ("RES012", "In-line suction catheter 14Fr", "Respiratory", "each", 9.00, 30, 3, "V", 1825, "Cascade Surgical Supply", "flu"),
    ("RES013", "Incentive spirometer", "Respiratory", "each", 4.00, 25, 4, "D", 1825, "Northwest Medical Distributors", None),
    ("RES014", "High-flow nasal cannula set", "Respiratory", "each", 45.00, 40, 0.8, "V", 1825, "Overseas Medical Imports", "flu"),
    ("RES015", "Tracheostomy care kit", "Respiratory", "kit", 6.00, 30, 0.8, "E", 1825, "Cascade Surgical Supply", None),
    ("RES016", "Colorimetric CO2 detector", "Respiratory", "each", 14.00, 30, 0.4, "V", 1825, "Cascade Surgical Supply", None),
    ("RES017", "Peak flow meter", "Respiratory", "each", 6.00, 25, 0.3, "D", 1825, "Northwest Medical Distributors", "flu"),
]

# Items that get an "expiry problem" lot, to make the expiry screen interesting:
# item_id -> days until expiry of its oldest lot (negative = already expired)
EXPIRY_PROBLEMS = {"MED007": -5, "LAB001": 12, "MED011": 25, "MED009": 40, "LAB002": 55, "MED008": 80,
                   "MED045": -3, "LAB016": 20, "MED044": 35, "LAB015": 60}


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
