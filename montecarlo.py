import copy
import numpy as np
import pandas as pd
from constants import RMD_TABLE, RMD_START_AGE

TRADITIONAL_TYPES = {"traditional_401k", "traditional_ira"}
ROTH_TYPES = {"roth_401k", "roth_ira"}
TAXABLE_TYPES = {"taxable", "reit"}
BANK_TYPES = {"bank"}

# Account types whose market value falls during a stock crash
# Bank and rental property are intentionally excluded (cash / real estate)
CRASH_AFFECTED_TYPES = TRADITIONAL_TYPES | ROTH_TYPES | TAXABLE_TYPES | {"hsa"}


def _rmd_divisor(age: int) -> float:
    if age < RMD_START_AGE:
        return 0.0
    return RMD_TABLE.get(age, RMD_TABLE.get(min(age, max(RMD_TABLE.keys())), 6.4))


def _generate_crash_years(rng, retirement_age: int, life_expectancy: int) -> set[int]:
    """
    Schedule market crashes at random 10–20 year intervals throughout retirement.
    Each trial gets its own independently drawn crash schedule.
    """
    crash_years: set[int] = set()
    next_crash = retirement_age + int(rng.integers(10, 21))  # first crash in years 10–20
    while next_crash <= life_expectancy:
        crash_years.add(next_crash)
        next_crash += int(rng.integers(10, 21))
    return crash_years


def _mc_single_run(
    accts: list[dict],
    profile: dict,
    assumptions: dict,
    rng,
    volatility: float,
    crash_years: set[int],
    crash_magnitude: float,
    stock_pct: float,
    bond_return_rate: float,
) -> tuple[list[float], int | None]:
    """
    One Monte Carlo trial. Returns (portfolio_balance_by_age, depletion_age_or_None).
    accts must already be deep-copied by the caller.
    """
    retirement_age = profile["retirement_age"]
    life_expectancy = profile["life_expectancy"]
    inflation = assumptions.get("inflation_rate", 0.03)
    ret_return = assumptions.get("retirement_return_rate", 0.05)
    swr = assumptions.get("safe_withdrawal_rate", 0.04)
    spending_mode = assumptions.get("spending_mode", "swr")
    filing_status = profile["filing_status"]

    total_start = sum(a["balance"] for a in accts)
    years_to_ret = profile["retirement_age"] - profile["current_age"]
    if spending_mode == "fixed":
        spending = (
            assumptions.get("annual_spending_target", total_start * swr)
            * (1 + inflation) ** years_to_ret
        )
    else:
        spending = total_start * swr

    _ss_inflate = (1 + inflation) ** max(0, years_to_ret)
    ss_benefit = profile.get("social_security_benefit", 0.0) * _ss_inflate
    ss_start = profile.get("social_security_start_age", 67)
    spouse_ss = profile.get("spouse_ss_benefit", 0.0) * _ss_inflate
    spouse_ss_start = profile.get("spouse_ss_start_age", 67)
    spouse_age_offset = (
        profile.get("spouse_age", profile.get("current_age", 0))
        - profile.get("current_age", 0)
    )
    survivor_reduction = profile.get("survivor_spending_reduction", 0.25)
    pre_hc = profile.get("pre_medicare_healthcare", 0.0)
    post_hc = profile.get("post_medicare_healthcare", 0.0)

    survivor_triggered = False
    depleted_age = None
    portfolio_by_age = []

    for age in range(retirement_age, life_expectancy + 1):
        spouse_age = age + spouse_age_offset if filing_status == "married_filing_jointly" else None

        # Survivor transition
        if (
            not survivor_triggered
            and filing_status == "married_filing_jointly"
            and spouse_age is not None
            and spouse_age >= profile.get("life_expectancy", 90)
        ):
            survivor_triggered = True
            ss_benefit = max(ss_benefit, spouse_ss)
            spouse_ss = 0.0
            spending *= 1 - survivor_reduction

        years_in = age - retirement_age
        hc_cost = (post_hc if age >= 65 else pre_hc) * (1 + inflation) ** years_in

        # Passive income that offsets portfolio drawdown
        total_ss = 0.0
        if age >= ss_start:
            total_ss += ss_benefit
        if spouse_age is not None and spouse_age >= spouse_ss_start:
            total_ss += spouse_ss
        rental = sum(
            a.get("net_annual_rental_income", 0.0)
            for a in accts
            if a["type"] == "rental_property"
        )

        net_from_portfolio = max(0.0, spending + hc_cost - total_ss - rental)

        # RMDs (mandatory; reduce net_from_portfolio if they cover spending)
        for a in accts:
            if a["type"] in TRADITIONAL_TYPES and age >= RMD_START_AGE:
                div = _rmd_divisor(age)
                rmd = min(a["balance"] / div if div > 0 else 0.0, a["balance"])
                a["balance"] = max(0.0, a["balance"] - rmd)
                net_from_portfolio = max(0.0, net_from_portfolio - rmd)

        # Discretionary withdrawals: bank → taxable → traditional → roth
        remaining = net_from_portfolio
        for bucket in [BANK_TYPES, TAXABLE_TYPES, TRADITIONAL_TYPES, ROTH_TYPES]:
            for a in sorted(
                [a for a in accts if a["type"] in bucket], key=lambda x: -x["balance"]
            ):
                if remaining <= 0:
                    break
                w = min(remaining, a["balance"])
                a["balance"] = max(0.0, a["balance"] - w)
                remaining -= w

        # Randomized returns (applied after withdrawals, same timing as deterministic sim)
        bond_pct = 1.0 - stock_pct
        # Bonds are ~30% as volatile as equities and draw from a separate distribution
        bond_vol = volatility * 0.30
        for a in accts:
            if a["type"] == "bank":
                # Cash: near-deterministic, tiny vol
                base = a.get("return_rate", 0.04)
                r = float(rng.normal(base, volatility * 0.10))
            elif a["type"] == "rental_property":
                # Real estate: lower vol than equities, not split by stock/bond
                base = a.get("return_rate", 0.04)
                r = float(rng.normal(base, volatility * 0.40))
            else:
                # Investment accounts: blend equity and bond draws each year
                stock_mean = (
                    a.get("return_rate", ret_return)
                    if not a.get("use_global_return_rate", True)
                    else ret_return
                )
                stock_r = float(rng.normal(stock_mean, volatility))
                bond_r = float(rng.normal(bond_return_rate, bond_vol))
                r = stock_pct * stock_r + bond_pct * bond_r

            # Floor at -60% to avoid absurd tail draws
            a["balance"] = max(0.0, a["balance"] * (1 + max(-0.6, r)))

            # Crash shock: only equity accounts, scaled by stock allocation
            # (a 60/40 portfolio absorbs 60% of the crash, bonds are unaffected)
            if age in crash_years and a["type"] in CRASH_AFFECTED_TYPES:
                a["balance"] *= (1 - stock_pct * crash_magnitude)

        total_bal = sum(a["balance"] for a in accts)
        if total_bal <= 0 and depleted_age is None:
            depleted_age = age

        portfolio_by_age.append(total_bal)

        spending *= 1 + inflation
        ss_benefit *= 1 + inflation
        spouse_ss *= 1 + inflation  # 0 after survivor transition; harmless

    return portfolio_by_age, depleted_age


def run_monte_carlo(
    accounts_at_retirement: list[dict],
    profile: dict,
    assumptions: dict,
    n_runs: int = 1000,
    volatility: float = 0.12,
    enable_crashes: bool = False,
    crash_magnitude: float = 0.20,
    stock_pct: float = 0.60,
    bond_return_rate: float = 0.035,
    seed: int | None = None,
) -> dict:
    """
    Run N Monte Carlo trials with per-year, per-account randomized returns.

    When enable_crashes=True, each trial independently schedules market crashes
    at random 10–20 year intervals. In a crash year, equity accounts take an
    additional crash_magnitude drop on top of that year's normal return draw.

    Returns:
        ages: list of retirement ages simulated
        percentiles: {10, 25, 50, 75, 90} → list of portfolio values by age
        success_rate: fraction of runs where portfolio never hit $0
        n_runs: number of trials
        n_depleted: number of trials that depleted
        depletion_ages: list of ages at which each failed run depleted
        volatility: the volatility used
        enable_crashes / crash_magnitude: parameters used (for staleness check)
    """
    rng = np.random.default_rng(seed)
    retirement_age = profile["retirement_age"]
    life_expectancy = profile["life_expectancy"]
    ages = list(range(retirement_age, life_expectancy + 1))

    all_runs: list[list[float]] = []
    depletion_ages: list[int] = []

    for _ in range(n_runs):
        accts = copy.deepcopy(accounts_at_retirement)
        crash_years = (
            _generate_crash_years(rng, retirement_age, life_expectancy)
            if enable_crashes
            else set()
        )
        bal_series, dep_age = _mc_single_run(
            accts, profile, assumptions, rng, volatility,
            crash_years, crash_magnitude, stock_pct, bond_return_rate,
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
        "bond_return_rate": bond_return_rate,
    }
