"""
montecarlo.py — Standard (normal-returns) Monte Carlo engine.

Like montecarlo_v2, this generates stochastic per-year, per-account returns and then
runs the full deterministic plan for each trial via ``withdrawals.simulate_retirement``,
so every trial models the same strategy as the Retirement tab and Optimizer — Roth
conversions, 0%-bracket gain harvesting, planned rebalancing, the tax-efficient
fill-to-bracket withdrawal order, SS taxability, IRMAA/NIIT, RMDs and the survivor
transition.

It differs from v2 (CMA log-normal) only in the RETURN DISTRIBUTION:
  - returns are drawn from a normal distribution (not log-normal),
  - each account is drawn independently (no shared equity/bond correlation factor),
  - inflation is deterministic (the assumption rate, not stochastic).

This is the simpler, more optimistic "Standard" model retained for comparison; the
v2 engine is recommended for serious planning.
"""

import numpy as np
from withdrawals import simulate_retirement

TRADITIONAL_TYPES = {"traditional_401k", "traditional_ira"}
ROTH_TYPES = {"roth_401k", "roth_ira"}
TAXABLE_TYPES = {"taxable", "reit"}
BANK_TYPES = {"bank"}

# Account types whose market value falls during a stock crash
# Bank and rental property are intentionally excluded (cash / real estate)
CRASH_AFFECTED_TYPES = TRADITIONAL_TYPES | ROTH_TYPES | TAXABLE_TYPES | {"hsa"}


def _first_year_crash(sim_start_age: int) -> set[int]:
    """
    Model sequence-of-returns risk: a single market crash in the first year of
    retirement (the simulation's first year). Returned as a one-element set so it
    feeds the same crash-application path as before. Deterministic across trials —
    the same first-year shock is applied to every trial, on top of its random draw.
    """
    return {sim_start_age}


def _build_market_returns(
    accts: list[dict],
    ages: list[int],
    rng,
    volatility: float,
    stock_pct: float,
    ret_return: float,
    crash_years: set[int],
    crash_magnitude: float,
) -> list[dict]:
    """
    Per-simulation-year, per-account normal returns, returned as
    ``[{account_id: return_rate}, ...]`` aligned with ``ages`` for simulate_retirement's
    ``market_returns`` hook. Each account is drawn independently (the v1 simplification);
    crash shocks are baked in. Returns are floored at -60% to avoid absurd tail draws.
    """
    bond_pct = 1.0 - stock_pct
    portfolio_vol = stock_pct * volatility + bond_pct * (volatility * 0.30)
    out: list[dict] = []
    for age in ages:
        year: dict = {}
        for a in accts:
            atype = a["type"]
            if atype == "bank":
                base = a.get("return_rate", 0.04)
                r = float(rng.normal(base, volatility * 0.10))
            elif atype == "rental_property":
                base = a.get("return_rate", 0.04)
                r = float(rng.normal(base, volatility * 0.40))
            else:
                port_mean = (
                    a.get("return_rate", ret_return)
                    if not a.get("use_global_return_rate", True)
                    else ret_return
                )
                r = float(rng.normal(port_mean, portfolio_vol))
            r = max(-0.6, r)
            if age in crash_years and atype in CRASH_AFFECTED_TYPES:
                r = (1.0 + r) * (1.0 - stock_pct * crash_magnitude) - 1.0
            year[a["id"]] = r
        out.append(year)
    return out


def _mc_single_run(
    accts: list[dict],
    profile: dict,
    assumptions: dict,
    roth_conversion: dict | None,
    spending_overrides: dict | None,
    rng,
    volatility: float,
    crash_years: set[int],
    crash_magnitude: float,
    stock_pct: float,
) -> tuple[list[float], int | None]:
    """One Monte Carlo trial: build the normal return paths and run the full plan."""
    retirement_age = profile["retirement_age"]
    life_expectancy = profile["life_expectancy"]
    current_age = profile.get("current_age", retirement_age)
    sim_start_age = max(retirement_age, current_age)
    ages = list(range(sim_start_age, life_expectancy + 1))
    ret_return = assumptions.get("retirement_return_rate", 0.05)

    market_returns = _build_market_returns(
        accts, ages, rng, volatility, stock_pct, ret_return, crash_years, crash_magnitude,
    )

    # Inflation is deterministic in v1 (inflation_sequence=None → assumption rate).
    df, summary = simulate_retirement(
        accts, profile, assumptions, roth_conversion, spending_overrides,
        market_returns=market_returns,
    )
    portfolio_by_age = df["total_portfolio"].tolist() if not df.empty else [0.0] * len(ages)
    return portfolio_by_age, summary.get("portfolio_depleted_age")


def run_monte_carlo(
    accounts_at_retirement: list[dict],
    profile: dict,
    assumptions: dict,
    n_runs: int = 1000,
    volatility: float = 0.12,
    enable_crashes: bool = False,
    crash_magnitude: float = 0.20,
    stock_pct: float = 0.60,
    roth_conversion: dict | None = None,
    spending_overrides: dict | None = None,
    seed: int | None = None,
) -> dict:
    """
    Run N Monte Carlo trials with per-year, per-account normal returns, each trial
    running the full deterministic plan via simulate_retirement.

    The expected return for each account matches the deterministic simulation
    (ret_return from assumptions, or the account's own rate).  The stock/bond
    allocation controls volatility only: higher stock_pct → more volatile path.
    Bond volatility is fixed at 30% of equity volatility.

    When enable_crashes=True, a single market crash hits the first year of retirement
    (sequence-of-returns risk): equity accounts take an additional crash_magnitude
    drop on top of that first year's normal return draw, in every trial.

    Returns:
        ages: list of simulated ages (max(retirement_age, current_age) → life_expectancy)
        percentiles: {10, 25, 50, 75, 90} → list of portfolio values by age
        success_rate: fraction of runs where the portfolio never hit $0
        n_runs / n_depleted / depletion_ages
        volatility / stock_pct / enable_crashes / crash_magnitude: params used
    """
    rng = np.random.default_rng(seed)
    retirement_age = profile["retirement_age"]
    life_expectancy = profile["life_expectancy"]
    # Already-retired support: start at current_age when it exceeds retirement_age so the
    # MC horizon matches simulate_retirement and the deterministic baseline overlay aligns.
    sim_start_age = max(retirement_age, profile.get("current_age", retirement_age))
    ages = list(range(sim_start_age, life_expectancy + 1))

    all_runs: list[list[float]] = []
    depletion_ages: list[int] = []

    for _ in range(n_runs):
        # simulate_retirement deep-copies accounts internally and _build_market_returns
        # only reads metadata, so the shared list is safe to pass without a per-trial copy.
        crash_years = _first_year_crash(sim_start_age) if enable_crashes else set()
        bal_series, dep_age = _mc_single_run(
            accounts_at_retirement, profile, assumptions,
            roth_conversion, spending_overrides,
            rng, volatility, crash_years, crash_magnitude, stock_pct,
        )
        all_runs.append(bal_series)
        if dep_age is not None:
            depletion_ages.append(dep_age)

    arr = np.array(all_runs)  # shape: (n_runs, n_years)
    success_rate = 1.0 - len(depletion_ages) / n_runs

    percentiles = {
        p: np.percentile(arr, p, axis=0).tolist()
        for p in [10, 25, 50, 75, 90]
    }

    return {
        "ages": ages,
        "percentiles": percentiles,
        "success_rate": success_rate,
        "n_runs": n_runs,
        "n_depleted": len(depletion_ages),
        "depletion_ages": depletion_ages,
        "volatility": volatility,
        "enable_crashes": enable_crashes,
        "crash_magnitude": crash_magnitude,
        "stock_pct": stock_pct,
    }
