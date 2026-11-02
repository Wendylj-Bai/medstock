"""
Tests that check the forecasting methods against the professor's worked examples
(Forecasting chapter, slides 270-306).
"""

import numpy as np
import pandas as pd
from pytest import approx

import forecasting as fc


def test_accuracy_measures_slide_272():
    demand = [1012, 984, 1007, 1075, 1086, 949, 969, 923, 903, 1054,
              1005, 922, 1057, 1096, 910, 952, 947, 1005, 916, 945]
    forecast = [1000, 1000, 950, 1000, 1150, 960, 1000, 900, 950, 1000,
                1150, 912, 1010, 1100, 909, 960, 940, 1100, 950, 900]
    a = fc.accuracy(demand, forecast)
    assert a["MAD"] == approx(39.3, abs=0.05)
    assert a["MSE"] == approx(2788.8, abs=0.05)
    assert a["MAPE"] == approx(0.0392, abs=1e-4)
    assert a["bias"] == approx(6.2)                # slide 274: small next to MAD = 39.3


def test_moving_average_engine_failures_slide_278():
    failures = [200, 250, 175, 186, 225, 285, 305, 190]
    f3, _ = fc.moving_average(failures, 3)
    assert f3[3] == approx(208.33, abs=0.01)       # forecast for quarter 4
    assert fc.accuracy(failures, f3)["MAD"] == approx(57.6, abs=0.05)
    assert fc.accuracy(failures, f3)["MSE"] == approx(4198.49, abs=0.01)

    f6, _ = fc.moving_average(failures, 6)
    assert fc.accuracy(failures, f6)["MAD"] == approx(66.25)
    # The slide's verdict: MA(3) is better here (lower MAD)


def test_ma_vs_exponential_smoothing_slide_286():
    sales = [190, 240, 165, 176, 215, 275, 295]
    ma, ma_next = fc.moving_average(sales, 3)
    assert ma_next(1)[0] == approx(261.67, abs=0.01)                 # forecast month 8

    es, es_next = fc.exponential_smoothing(sales, alpha=0.1, init_periods=2)
    assert es[2] == approx(215)                                       # F3 = avg of months 1-2
    assert es_next(1)[0] == approx(222.28, abs=0.01)                  # forecast month 8
    assert fc.accuracy(sales, es)["MAD"] == approx(48.15, abs=0.01)


def test_holt_slide_293_setup():
    sales = [190, 240, 165, 176, 215, 275, 295]
    fitted, future = fc.holt(sales, alpha=0.1, beta=0.1, S0=190, G0=20)
    assert fitted[0] == approx(210)                     # F1 = S0 + G0
    # Month 11 is 4 months after month 7: F = S7 + 4 G7
    f11 = future(4)[-1]
    assert future(4)[0] < f11                           # an upward trend continues


def test_winters_matches_professor_table_slide_306():
    D = [53, 22, 37, 45, 58, 25, 40, 50, 62, 27, 44, 56]
    fitted, future = fc.winters(D, N=4, alpha=0.2, beta=0.3, gamma=0.25,
                                S0=156, G0=4, c0=[0.34, 0.14, 0.24, 0.29])
    assert fitted[1] == approx(22.8101, abs=1e-3)       # F2
    assert fitted[2] == approx(39.6427, abs=1e-3)       # F3
    assert fitted[4] == approx(56.0544, abs=1e-3)       # F5
    assert fitted[11] == approx(54.5440, abs=1e-3)      # F12


def test_winters_initialization_slide_305():
    D = [53, 22, 37, 45, 58, 25, 40, 50, 62, 27, 44, 56]
    S0, G0, c = fc.winters_initial(D, N=4, seasons=3)
    assert G0 == approx(4)                              # (189 - 157) / (2 × 4)
    assert c.sum() == approx(1)
    # The slide shows 0.34, 0.14, 0.24, 0.29 (hand-rounded; they add up to 1.01)
    assert c == approx([0.34, 0.14, 0.24, 0.29], abs=0.01)


def test_winters_wins_on_seasonal_data_and_daily_rates():
    # 3 years of a strongly seasonal monthly series: high in Dec-Feb
    idx = pd.date_range("2023-11-01", periods=36, freq="MS")
    season = np.array([1.1, 1.6, 1.8, 1.5, 1.1, 0.9, 0.8, 0.8, 0.8, 0.8, 0.8, 0.9])
    rng = np.random.default_rng(0)
    series = pd.Series(50 * np.tile(season, 3) * rng.normal(1, 0.03, 36), index=idx)

    res = fc.forecast_item(series)
    assert res["method"] == "Winters (seasonal)"
    assert res["future"].index[0] == pd.Timestamp("2026-11-01")
    jan = res["future"][pd.Timestamp("2027-01-01")]
    jul = res["future"][pd.Timestamp("2027-07-01")]
    assert jan > 1.8 * jul                              # it learned the flu-season peak

    rates = fc.daily_rates(res["future"], pd.Timestamp("2026-11-01"))
    assert len(rates) == 365
    assert rates[0] == approx(res["future"].iloc[0])    # Nov 1 uses the November rate
    assert rates[61] == approx(jan)                     # Jan 1 uses the January rate
