"""
Tests that check our formulas against the professor's worked examples.
Run with:   .venv/bin/python -m pytest -v
"""

import statistics

from pytest import approx

import inventory_math as im


def test_eoq_slide_188():
    # D = 1000/yr, S = $50, C = $40, holding = 25% of C  ->  H = $10
    D, S, C = 1000, 50, 40
    H = 0.25 * C
    Q = im.eoq(D, S, H)
    assert Q == approx(100)

    cost = im.total_annual_cost(Q, D, S, H, C)
    assert cost["ordering"] == approx(500)
    assert cost["holding"] == approx(500)   # at EOQ, ordering cost = holding cost
    assert cost["total"] == approx(41_000)
    assert im.cycle_time_days(Q, D) == approx(36.5)   # 0.1 year


def test_uncertain_demand_and_leadtime_slide_203():
    # Annual demand ~ Normal(1000, 50); lead time ~ Normal(0.2, 0.05) months
    # S = $50, i = 20%, C = $50, service level 95%.  Work in MONTHS.
    Q = im.eoq(1000, 50, 0.20 * 50)
    assert Q == approx(100)

    d = 1000 / 12               # 83.33 per month
    sd = 50 / 12 ** 0.5         # 14.43 per month (variance scales with time)
    r = im.reorder_point(d, sd, L=0.2, sL=0.05, service_level=0.95)
    assert r["z"] == approx(1.645, abs=1e-3)
    assert r["ddlt"] == approx(16.67, abs=0.01)
    assert r["sigma_ddlt"] == approx(7.68, abs=0.01)
    assert r["safety_stock"] == approx(12.64, abs=0.01)
    assert r["rop"] == approx(29.30, abs=0.01)


def test_backorders_and_fill_rate_slide_208():
    # Monthly demand 50, 60, 40, 50; lead time 17 days = 17/30 month; Q = 100
    history = [50, 60, 40, 50]
    d = statistics.mean(history)        # 50
    sd = statistics.stdev(history)      # 8.165 (sample std. dev.)
    L = 17 / 30
    sig = im.sigma_ddlt(d, sd, L, 0)

    # (1) max 7% chance of stockout -> 93% service level
    r = im.reorder_point(d, sd, L, 0, 0.93)
    assert r["z"] == approx(1.476, abs=1e-3)
    assert r["rop"] == approx(37.40, abs=0.01)

    # (2) expected backorders per year and fill rate
    eb = im.expected_backorders_per_cycle(r["z"], sig)
    orders_per_year = 12 * d / 100      # 6 cycles a year
    assert eb * orders_per_year == approx(1.14, abs=0.01)
    assert im.fill_rate(r["z"], sig, 100) == approx(0.998, abs=1e-3)

    # (3) 99% fill rate -> find z, then the ROP
    z99 = im.z_for_fill_rate(0.99, sig, 100)
    assert im.fill_rate(z99, sig, 100) == approx(0.99, abs=1e-6)
    assert d * L + z99 * sig < r["rop"]   # a 99% FILL rate needs less stock than a 93% CYCLE service level


def test_newsvendor_joes_beef_slides_228_231():
    # Cost $2/lb, price $4, salvage (tax deduction) $0.50, demand ~ N(80, 20)
    r = im.newsvendor(price=4, cost=2, salvage=0.5, mu=80, sigma=20)
    assert r["cu"] == 2 and r["co"] == 1.5
    assert r["service_level"] == approx(0.5714, abs=1e-4)
    assert r["q"] == approx(83.6, abs=0.1)
    assert r["expected_shortage"] == approx(6.3, abs=0.1)
    assert r["expected_sales"] == approx(73.7, abs=0.1)
    assert r["expected_excess"] == approx(9.9, abs=0.1)
    assert r["expected_profit"] == approx(132.5, abs=0.5)


def test_service_level_slide_225():
    # Cu = 1.5, Co = 0.5 -> 75%
    r = im.newsvendor(price=2.0, cost=0.5, salvage=0.0, mu=100, sigma=10)
    assert r["service_level"] == approx(0.75)


def test_abc_university_shop_slide_215():
    items = [
        {"name": "T-shirts", "unit_cost": 10, "annual_demand": 13_000},
        {"name": "Pants", "unit_cost": 20, "annual_demand": 3_000},
        {"name": "Shoes", "unit_cost": 50, "annual_demand": 150},
        {"name": "Caps", "unit_cost": 5, "annual_demand": 7_500},
        {"name": "Socks", "unit_cost": 3, "annual_demand": 2_000},
        {"name": "Sweaters", "unit_cost": 25, "annual_demand": 8_000},
        {"name": "Backpacks", "unit_cost": 30, "annual_demand": 200},
        {"name": "Key chains", "unit_cost": 1, "annual_demand": 15_000},
    ]
    rows = im.abc_classify(items)
    assert sum(r["annual_value"] for r in rows) == 462_000
    classes = {r["name"]: r["abc"] for r in rows}
    assert classes["Sweaters"] == "A" and classes["T-shirts"] == "A"       # 71%
    assert classes["Pants"] == "B" and classes["Caps"] == "B"              # 21%
    for c in ["Key chains", "Shoes", "Socks", "Backpacks"]:
        assert classes[c] == "C"                                            # 8%
