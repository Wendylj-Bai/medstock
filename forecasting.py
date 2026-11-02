"""
forecasting.py: Demand forecasting with the methods from the course
(Forecasting chapter, slides 259-306).

We forecast a MONTHLY series: the average daily usage in each month
(a monthly total divided by the days in that month, so February is not
"low" just because it is short).

Notation, as in the slides:
    D_t     actual demand in period t
    F_t     forecast for period t (made at the end of period t-1)
    e_t     forecast error = F_t - D_t           (slide 270)
    S_t     smoothed level,  G_t  smoothed trend,  c_t  seasonal factor
    N       periods per season (12 months)

How the app uses this
  1. For each item, run all methods on its history.
  2. Backtest: compare each method's one-step-ahead forecasts with what
     actually happened in the last 12 months (MAD, MSE, MAPE, bias).
  3. "Auto" picks the method with the lowest MAD for that item.
  4. The chosen method forecasts the next 12 months. That gives
       d̄  = forecast daily demand during the coming lead time (for the ROP)
       D  = forecast demand over the next year (for the EOQ)
       σd = the size of the forecast ERRORS (for the safety stock)
"""

import math
from datetime import date

import numpy as np
import pandas as pd

DAYS_PER_MONTH = 365 / 12        # 30.4

# Default smoothing constants (slides suggest small values, ~0.1-0.3)
DEFAULT_PARAMS = {
    "ma_n": 3,                    # moving average over N months
    "alpha": 0.2,                 # level
    "beta": 0.1,                  # trend
    "gamma": 0.3,                 # seasonal factors
}

METHODS = ["Moving average", "Exponential smoothing", "Holt (trend)", "Winters (seasonal)"]


# ---------------------------------------------------------------------------
# Accuracy measures (slides 270-274)
# ---------------------------------------------------------------------------

def accuracy(actual, forecast):
    """MAD, MSE, MAPE and bias, using e = F - D. Ignores periods with no forecast."""
    D = np.asarray(actual, dtype=float)
    F = np.asarray(forecast, dtype=float)
    ok = ~np.isnan(F)
    e = F[ok] - D[ok]
    nz = D[ok] != 0
    return {
        "MAD": np.mean(np.abs(e)),
        "MSE": np.mean(e ** 2),
        "MAPE": np.mean(np.abs(e[nz] / D[ok][nz])) if nz.any() else 0.0,
        "bias": np.mean(e),                 # > 0: we over-forecast on average
        "n": int(ok.sum()),
    }


# ---------------------------------------------------------------------------
# The four methods.
# Each returns (fitted, future):
#   fitted[t] = one-step-ahead forecast for period t (NaN if not available yet)
#   future(h) = forecast for h = 1, 2, ... periods after the last observation
# ---------------------------------------------------------------------------

def moving_average(D, N=3):
    """F_t = (D_{t-1} + ... + D_{t-N}) / N        (slide 276)"""
    D = np.asarray(D, dtype=float)
    fitted = np.full(len(D), np.nan)
    for t in range(N, len(D)):
        fitted[t] = D[t - N:t].mean()
    last = D[-N:].mean()
    return fitted, (lambda h: np.full(h, last))


def exponential_smoothing(D, alpha=0.2, init_periods=2):
    """F_{t+1} = α D_t + (1 - α) F_t              (slide 283)

    Start-up as in slide 286: the first forecast is the average of the
    first `init_periods` observations.
    """
    D = np.asarray(D, dtype=float)
    fitted = np.full(len(D), np.nan)
    F = D[:init_periods].mean()
    for t in range(init_periods, len(D)):
        fitted[t] = F
        F = alpha * D[t] + (1 - alpha) * F
    return fitted, (lambda h: np.full(h, F))


def holt(D, alpha=0.2, beta=0.1, S0=None, G0=None):
    """Holt's double exponential smoothing for a linear trend (slides 290-293).

        S_t = α D_t + (1 - α)(S_{t-1} + G_{t-1})       level
        G_t = β (S_t - S_{t-1}) + (1 - β) G_{t-1}       trend
        F_{t, t+τ} = S_t + τ G_t
    """
    D = np.asarray(D, dtype=float)
    S = D[0] if S0 is None else S0
    G = 0.0 if G0 is None else G0
    fitted = np.full(len(D), np.nan)
    for t in range(len(D)):
        fitted[t] = S + G
        S_new = alpha * D[t] + (1 - alpha) * (S + G)
        G = beta * (S_new - S) + (1 - beta) * G
        S = S_new
    if S0 is None:
        fitted[0] = np.nan          # the very first "forecast" is just D_0 itself
    return fitted, (lambda h: S + G * np.arange(1, h + 1))


def winters_initial(D, N=12, seasons=2):
    """Initial S0, G0 and seasonal factors from the first full seasons (slide 305).

    Seasonal factor of position j = average over seasons of D_j / (season total).
    The factors add up to 1 (the professor's convention), so S is a "season
    total" level and G is how much that total grows per period.
    """
    D = np.asarray(D, dtype=float)
    blocks = D[:N * seasons].reshape(seasons, N)
    totals = blocks.sum(axis=1)
    if (totals <= 0).all() or (totals == 0).any():        # zero-demand history: no seasonal signal
        return 0.0, 0.0, np.full(N, 1.0 / N)
    c = (blocks / totals[:, None]).mean(axis=0)
    c = c / c.sum()
    G0 = (totals[-1] - totals[0]) / ((seasons - 1) * N) if seasons > 1 else 0.0
    S0 = totals[0] - G0 * N / 2          # level at the START of season 1
    return S0, G0, c


def winters(D, N=12, alpha=0.2, beta=0.1, gamma=0.3, S0=None, G0=None, c0=None, init_seasons=2):
    """Winters' model for trend + seasonality (slides 300-306).

        S_t = α (D_t / c_{t-N}) + (1 - α)(S_{t-1} + G_{t-1})
        G_t = β (S_t - S_{t-1}) + (1 - β) G_{t-1}
        c_t = γ (D_t / S_t) + (1 - γ) c_{t-N}
        F_{t, t+τ} = (S_t + τ G_t) c_{t+τ-N}
    """
    D = np.asarray(D, dtype=float)
    if c0 is None:
        S0, G0, c0 = winters_initial(D, N, init_seasons)
    S, G = S0, G0
    c = list(c0)                         # c[j] = latest factor for season position j
    fitted = np.full(len(D), np.nan)
    for t in range(len(D)):
        j = t % N
        fitted[t] = (S + G) * c[j]
        S_new = alpha * (D[t] / c[j]) + (1 - alpha) * (S + G)
        G = beta * (S_new - S) + (1 - beta) * G
        S = S_new
        c[j] = gamma * (D[t] / S) + (1 - gamma) * c[j]
    n = len(D)

    def future(h):
        return np.array([(S + tau * G) * c[(n + tau - 1) % N] for tau in range(1, h + 1)])
    return fitted, future


def run_method(name, D, params):
    p = {**DEFAULT_PARAMS, **(params or {})}
    if name == "Moving average":
        return moving_average(D, p["ma_n"])
    if name == "Exponential smoothing":
        return exponential_smoothing(D, p["alpha"])
    if name == "Holt (trend)":
        return holt(D, p["alpha"], p["beta"])
    if name == "Winters (seasonal)":
        return winters(D, 12, p["alpha"], p["beta"], p["gamma"])
    raise ValueError(name)


# ---------------------------------------------------------------------------
# Turning raw usage into a monthly series
# ---------------------------------------------------------------------------

def monthly_series(usage, today):
    """Average daily usage per COMPLETE month, one column per item.

    Days without usage count as 0. The current (unfinished) month is left
    out, because half a month would look like a demand drop.
    """
    if usage.empty or usage["date"].isna().all():
        return pd.DataFrame(index=pd.DatetimeIndex([], name="date"))
    first, last = usage["date"].min(), pd.Timestamp(today) - pd.Timedelta(days=1)
    days = pd.date_range(first, last)
    daily = (usage.groupby(["date", "item_id"])["qty_used"].sum()
             .unstack("item_id").reindex(days).fillna(0))
    monthly = daily.resample("MS").mean()
    complete = (monthly.index >= first.to_period("M").to_timestamp()) & \
               ((monthly.index + pd.offsets.MonthEnd(0)) <= last)
    # also drop a first month that started part-way through
    if first.day != 1:
        complete &= monthly.index > first
    return monthly[complete]


# ---------------------------------------------------------------------------
# Forecast every item
# ---------------------------------------------------------------------------

def available_methods(n_months):
    methods = []
    if n_months >= 4:
        methods += ["Moving average", "Exponential smoothing", "Holt (trend)"]
    if n_months >= 24 + 3:                  # 2 seasons to start, 3+ months to test
        methods.append("Winters (seasonal)")
    return methods


def forecast_item(series, method="Auto", params=None, test_months=12, horizon_months=13):
    """Backtest every method on one item and forecast with the chosen one.

    Returns a dict with:
        method        the method used
        scores        DataFrame: MAD / MSE / MAPE / bias per method (backtest)
        fitted        one-step forecasts of the chosen method (for charts)
        future        monthly forecast of average daily usage, next horizon_months
        sigma_daily   σd for the safety-stock formula (from forecast errors)
    """
    D = series.to_numpy(dtype=float)
    n = len(D)
    methods = available_methods(n)
    if not methods:
        return None
    if np.nanmax(D) <= 0:                           # zero-demand history: Winters would divide by zero
        methods = ["Moving average"]
    test = slice(max(n - test_months, 24 if "Winters (seasonal)" in methods else 0), n)
    results, rows = {}, []
    for m in methods:
        fitted, future = run_method(m, D, params)
        results[m] = (fitted, future)
        rows.append({"method": m, **accuracy(D[test], fitted[test])})
    scores = pd.DataFrame(rows).set_index("method")
    chosen = scores["MAD"].idxmin() if method == "Auto" or method not in results else method
    fitted, future = results[chosen]
    mad = scores.loc[chosen, "MAD"]

    # σ of a monthly-average error ≈ 1.25 × MAD (normal errors). A month's
    # average daily rate has σ_daily / √30.4, so convert back to one day:
    sigma_daily = 1.25 * mad * math.sqrt(DAYS_PER_MONTH)

    future_months = pd.date_range(series.index[-1] + pd.offsets.MonthBegin(1),
                                  periods=horizon_months, freq="MS")
    return {
        "method": chosen,
        "scores": scores,
        "fitted": pd.Series(fitted, index=series.index),
        "future": pd.Series(np.maximum(future(horizon_months), 0), index=future_months),
        "sigma_daily": sigma_daily,
    }


def daily_rates(future_monthly, today, days=365):
    """Spread a monthly forecast over the next `days` days, starting today."""
    dates = pd.date_range(pd.Timestamp(today), periods=days)
    rate_by_month = future_monthly.copy()
    rate_by_month.index = rate_by_month.index.to_period("M")
    rates = rate_by_month.reindex(dates.to_period("M")).ffill().bfill()
    return rates.to_numpy()


def forecast_all(usage, today=None, method="Auto", params=None):
    """Forecast every item. Returns {item_id: result dict + 'rates' for the next 365 days}."""
    today = today or date.today()
    if usage.empty or usage["date"].isna().all():
        return {}
    monthly = monthly_series(usage, today)
    out = {}
    for item_id in monthly.columns:
        series = monthly[item_id]
        if np.nanmax(series.to_numpy(dtype=float)) <= 0:     # zero-demand item: nothing to forecast
            continue
        res = forecast_item(series, method, params)
        if res is None:
            continue
        res["history"] = series
        res["rates"] = daily_rates(res["future"], today)
        out[item_id] = res
    return out
