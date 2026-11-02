"""
inventory_math.py: The "brain" of the app.

Every formula here comes from the Inventory Management chapter of the
course slides (pp. 175-232). Slide numbers are noted on each function so
you can compare the code with the lecture.

Notation (same as the professor's):
    D      annual demand (units/year)
    S      ordering / setup cost per order ($)
    C      unit cost ($)
    i      holding (carrying) cost rate per year (e.g. 0.25 = 25%)
    H      holding cost per unit per year = i * C
    Q      order quantity
    d      average demand per period (e.g. per day)
    sd     standard deviation of demand per period
    L      average lead time (same period unit as d)
    sL     standard deviation of lead time
    z      safety factor from the standard normal table

IMPORTANT: d, sd, L and sL must use the SAME time unit (all days, or all months).
"""

import math

from scipy.stats import norm


# ---------------------------------------------------------------------------
# 1. EOQ model (slides 183-191)
# ---------------------------------------------------------------------------

def eoq(D, S, H):
    """Economic Order Quantity: Q* = sqrt(2DS / H)   (slide 188)"""
    return math.sqrt(2 * D * S / H)


def total_annual_cost(Q, D, S, H, C=0.0, safety_stock=0.0):
    """Total cost = purchasing + ordering + holding   (slide 187)

    If you carry safety stock, it is also held all year, so it adds H * SS.
    """
    purchasing = D * C
    ordering = (D / Q) * S
    holding = (Q / 2 + safety_stock) * H
    return {
        "purchasing": purchasing,
        "ordering": ordering,
        "holding": holding,
        "total": purchasing + ordering + holding,
    }


def cycle_time_days(Q, D, days_per_year=365):
    """Time between orders = Q / D (in years), converted to days."""
    return Q / D * days_per_year


# ---------------------------------------------------------------------------
# 2. Uncertain demand and lead time (slides 197-204)
# ---------------------------------------------------------------------------

def z_from_service_level(service_level):
    """Service level (e.g. 0.95) -> z (e.g. 1.645). Replaces the normal table (slide 202)."""
    return norm.ppf(service_level)


def sigma_ddlt(d, sd, L, sL):
    """Std. dev. of demand during lead time   (slide 200-201)

        sigma_ddlt = sqrt( L * sd^2  +  d^2 * sL^2 )

    Constant demand   -> sd = 0
    Constant lead time -> sL = 0
    """
    return math.sqrt(L * sd ** 2 + d ** 2 * sL ** 2)


def safety_stock(z, d, sd, L, sL):
    """SS = z * sigma_ddlt   (slide 200)"""
    return z * sigma_ddlt(d, sd, L, sL)


def reorder_point(d, sd, L, sL, service_level):
    """ROP = DDLT + SS, where DDLT = d * L   (slide 200)

    Returns a dict so the app can show every intermediate number.
    """
    z = z_from_service_level(service_level)
    ddlt = d * L
    sig = sigma_ddlt(d, sd, L, sL)
    ss = z * sig
    return {"z": z, "ddlt": ddlt, "sigma_ddlt": sig, "safety_stock": ss, "rop": ddlt + ss}


# ---------------------------------------------------------------------------
# 3. Expected backorders and fill rate (slides 205-211)
# ---------------------------------------------------------------------------

def standard_loss(z):
    """Standardized loss function L(z) = phi(z) - z * (1 - Phi(z))   (slide 206)"""
    return norm.pdf(z) - z * (1 - norm.cdf(z))


def expected_backorders_per_cycle(z, sigma):
    """E(b) = sigma_ddlt * L(z)   (slide 207)"""
    return sigma * standard_loss(z)


def fill_rate(z, sigma, Q):
    """Fill rate = 1 - E(b)/Q, the share of demand served straight from the shelf."""
    return 1 - expected_backorders_per_cycle(z, sigma) / Q


def z_for_fill_rate(target_fill_rate, sigma, Q):
    """Find the z that achieves a target fill rate (slide 208, part 3).

    We need L(z) = (1 - fill_rate) * Q / sigma. L(z) always decreases as z
    grows, so a simple bisection search finds it.
    """
    target = (1 - target_fill_rate) * Q / sigma
    lo, hi = -4.0, 6.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if standard_loss(mid) > target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


# ---------------------------------------------------------------------------
# 4. Single-period / Newsvendor model (slides 217-231)
# ---------------------------------------------------------------------------

def newsvendor(price, cost, salvage, mu, sigma):
    """How many to stock for ONE selling period with uncertain demand.

    Cu = price - cost        (cost of having one unit too few, slide 223)
    Co = cost - salvage      (cost of having one unit too many, slide 224)
    Optimal service level = Cu / (Cu + Co)   (slide 225)
    Q = mu + z * sigma                         (slide 227)
    """
    cu = price - cost
    co = cost - salvage
    sl = cu / (cu + co)
    z = norm.ppf(sl)
    q = mu + z * sigma
    # Slide 231: expected shortages, sales, excess and profit
    shortage = sigma * standard_loss(z)
    sales = mu - shortage
    excess = q - sales
    profit = price * sales + salvage * excess - cost * q
    return {
        "cu": cu, "co": co, "service_level": sl, "z": z, "q": q,
        "expected_shortage": shortage, "expected_sales": sales,
        "expected_excess": excess, "expected_profit": profit,
    }


# ---------------------------------------------------------------------------
# 5. ABC classification (slides 213-215)
# ---------------------------------------------------------------------------

def abc_classify(items, a_cut=0.70, b_cut=0.90):
    """items: list of dicts with 'name', 'unit_cost', 'annual_demand'.

    Sort by annual dollar value. An item is A while the running total
    BEFORE it is under 70%, B while under 90%, otherwise C.
    Returns a new list (largest value first) with value, share and class.
    """
    rows = [dict(it, annual_value=it["unit_cost"] * it["annual_demand"]) for it in items]
    rows.sort(key=lambda r: r["annual_value"], reverse=True)
    grand_total = sum(r["annual_value"] for r in rows) or 1
    running = 0.0
    for r in rows:
        r["share"] = r["annual_value"] / grand_total
        r["abc"] = "A" if running < a_cut else ("B" if running < b_cut else "C")
        running += r["share"]
        r["cumulative_share"] = running
    return rows
