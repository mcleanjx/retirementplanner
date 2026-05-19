"""
montecarlo_v2.py — CMA-based Monte Carlo engine

Improvements over montecarlo.py (v1):

  Log-normal returns
    v1 draws r ~ N(mean, vol) which can theoretically go below -100% and
    systematically overstates high-return outcomes because it ignores the
    arithmetic/geometric gap at the distribution level.
    v2 draws from a log-normal: r = exp(log_mu + vol*z) - 1 where
    log_mu = log(1+mean) - 0.5*vol^2.  This corrects the geometric/arithmetic
    mean confusion, bounds the left tail at -100%, and produces realistic fat
    right tails.

  Correlated equity/bond factors
    v1 draws each account independently.  In reality equity accounts move
    together (a bad stock year hits the 401k and the taxable brokerage
    simultaneously).  v2 pre-generates one shared equity factor and one shared
    bond factor per year via Cholesky decomposition of a 2x2 correlation matrix.
    All equity-heavy accounts are driven by the equity factor; bond-heavy accounts
    by the bond factor.  Equity/bond correlation defaults to 0.10 (long-run CMA
    consensus — bonds provide modest diversification against equities).

  Stochastic inflation
    v1 applies a fixed inflation rate every year.  v2 draws inflation each year
    from N(inflation_mean, 1.5%) so spending and SS COLA vary across the
    retirement horizon.  This adds real-return uncertainty on top of nominal
    return volatility and slightly increases tail risk relative to v1.

  CMA-calibrated default volatilities
    v1 defaults: single equity_vol=12%, bond_vol=12%*0.30=3.6%.
    v2 defaults: equity_vol=15.5%, bond_vol=5.5% (JPM/Vanguard/BlackRock
    10-15yr CMA consensus).

Return model per investment account per year:
  equity_mean, bond_mean = _equity_bond_means(stock_pct, port_mean)
  r_eq = exp(log_mu(equity_mean, equity_vol) + equity_vol * equity_z) - 1
  r_bd = exp(log_mu(bond_mean, bond_vol)    + bond_vol   * bond_z)   - 1
  r    = stock_pct * r_eq + bond_pct * r_bd

_equity_bond_means() preserves the equity risk premium (3pp) while ensuring
the blended return equals port_mean (= ret_return or account's own rate).
"""

import copy
import numpy as np
from constants import RMD_TABLE, RMD_START_AGE

TRADITIONAL_TYPES = {"traditional_401k", "traditional_ira"}
ROTH_TYPES = {"roth_401k", "roth_ira"}
TAXABLE_TYPES = {"taxable", "reit"}
BANK_TYPES = {"bank"}
CRASH_AFFECTED_TYPES = TRADITIONAL_TYPES | ROTH_TYPES | TAXABLE_TYPES | {"hsa"}

# Capital market assumption defaults (JPM/Vanguard/BlackRock 10-15yr consensus)
DEFAULT_EQUITY_VOL = 0.155
DEFAULT_BOND_VOL = 0.055
DEFAULT_EQUITY_BOND_CORR = 0.10
EQUITY_RISK_PREMIUM = 0.030  # equity expected return above bond expected return
INFLATION_VOL = 0.015        # std dev of annual inflation draws


def _rmd_divisor(age: int) -> float:
    if age < RMD_START_AGE:
        return 0.0
    return RMD_TABLE.get(age, RMD_TABLE.get(min(age, max(RMD_TABLE.keys())), 6.4))


def _generate_crash_years(rng, retirement_age: int, life_expectancy: int) -> set[int]:
    crash_years: set[int] = set()
    next_crash = retirement_age + int(rng.integers(10, 21))
    while next_crash <= life_expectancy:
        crash_years.add(next_crash)
        next_crash += int(rng.integers(10, 21))
    return crash_years


def _equity_bond_means(stock_pct: float, target_return: float) -> tuple[float, float]:
    """
    Scale equity and bond expected returns so their weighted average equals
    target_return while preserving the 3pp equity risk premium.

    With 60/40 and target=5%:
      bond_mean = 5% - 0.6*3% = 3.2%
      equity_mean = 3.2% + 3% = 6.2%
      blended = 0.6*6.2% + 0.4*3.2% = 5.0% ✓
    """
    bond_mean = target_return - stock_pct * EQUITY_RISK_PREMIUM
    equity_mean = bond_mean + EQUITY_RISK_PREMIUM
    return equity_mean, bond_mean


def _mc_single_run_v2(
    accts: list[dict],
    profile: dict,
    assumptions: dict,
    equity_zs: np.ndarray,
    bond_zs: np.ndarray,
    infl_zs: np.ndarray,
    equity_vol: float,
    bond_vol: float,
    crash_years: set[int],
    crash_magnitude: float,
    stock_pct: float,
    withdrawal_mode: str = "constant_real",
) -> tuple[list[float], int | None]:
    retirement_age = profile["retirement_age"]
    life_expectancy = profile["life_expectancy"]
    inflation_mean = assumptions.get("inflation_rate", 0.03)
    ret_return = assumptions.get("retirement_return_rate", 0.05)
    swr = assumptions.get("safe_withdrawal_rate", 0.04)
    spending_mode = assumptions.get("spending_mode", "swr")
    filing_status = profile["filing_status"]

    total_start = sum(a["balance"] for a in accts)
    years_to_ret = profile["retirement_age"] - profile["current_age"]

    _ss_inflate = (1 + inflation_mean) ** max(0, years_to_ret)
    if spending_mode == "fixed":
        spending = (
            assumptions.get("annual_spending_target", total_start * swr)
            * (1 + inflation_mean) ** years_to_ret
        )
    else:
        spending = total_start * swr

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
    bond_pct = 1.0 - stock_pct
    _gk_base_rate: float | None = None  # Guyton-Klinger baseline withdrawal rate

    for t, age in enumerate(range(retirement_age, life_expectancy + 1)):
        spouse_age = age + spouse_age_offset if filing_status == "married_filing_jointly" else None

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
        hc_cost = (post_hc if age >= 65 else pre_hc) * (1 + inflation_mean) ** years_in

        total_ss = 0.0
        if age >= ss_start:
            total_ss += ss_benefit
        if spouse_age is not None and spouse_age >= spouse_ss_start:
            total_ss += spouse_ss
        rental = sum(
            a.get("net_annual_rental_income", 0.0)
            for a in accts if a["type"] == "rental_property"
        )

        # Guyton-Klinger guardrails: adjust discretionary spending before withdrawing.
        # Compare the planned net portfolio draw to the initial retirement withdrawal rate.
        #   Capital Preservation Rule: if rate > 120% of baseline → cut spending 10%
        #   Prosperity Rule:           if rate <  80% of baseline → raise spending 10%
        # Healthcare and SS are outside the retiree's control and are not adjusted.
        if withdrawal_mode == "guardrails":
            current_bal = sum(a["balance"] for a in accts)
            if current_bal > 0:
                planned_net = max(0.0, spending + hc_cost - total_ss - rental)
                current_rate = planned_net / current_bal
                if _gk_base_rate is None:
                    _gk_base_rate = current_rate  # lock in baseline at year 0
                elif _gk_base_rate > 0:
                    if current_rate > _gk_base_rate * 1.20:
                        spending *= 0.90
                    elif current_rate < _gk_base_rate * 0.80:
                        spending *= 1.10

        net_from_portfolio = max(0.0, spending + hc_cost - total_ss - rental)

        for a in accts:
            if a["type"] in TRADITIONAL_TYPES and age >= RMD_START_AGE:
                div = _rmd_divisor(age)
                rmd = min(a["balance"] / div if div > 0 else 0.0, a["balance"])
                a["balance"] = max(0.0, a["balance"] - rmd)
                net_from_portfolio = max(0.0, net_from_portfolio - rmd)

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

        # Log-normal correlated returns
        for a in accts:
            if a["type"] == "bank":
                base = a.get("return_rate", 0.04)
                v = equity_vol * 0.10
                log_mu = np.log(max(1e-6, 1.0 + base)) - 0.5 * v ** 2
                r = float(np.exp(log_mu + v * equity_zs[t]) - 1.0)
            elif a["type"] == "rental_property":
                base = a.get("return_rate", 0.04)
                v = equity_vol * 0.40
                log_mu = np.log(max(1e-6, 1.0 + base)) - 0.5 * v ** 2
                r = float(np.exp(log_mu + v * bond_zs[t]) - 1.0)
            else:
                port_mean = (
                    a.get("return_rate", ret_return)
                    if not a.get("use_global_return_rate", True)
                    else ret_return
                )
                eq_mean, bd_mean = _equity_bond_means(stock_pct, port_mean)
                eq_log_mu = np.log(max(1e-6, 1.0 + eq_mean)) - 0.5 * equity_vol ** 2
                bd_log_mu = np.log(max(1e-6, 1.0 + bd_mean)) - 0.5 * bond_vol ** 2
                eq_r = float(np.exp(eq_log_mu + equity_vol * equity_zs[t]) - 1.0)
                bd_r = float(np.exp(bd_log_mu + bond_vol * bond_zs[t]) - 1.0)
                r = stock_pct * eq_r + bond_pct * bd_r

            a["balance"] = max(0.0, a["balance"] * (1 + max(-0.95, r)))

            if age in crash_years and a["type"] in CRASH_AFFECTED_TYPES:
                a["balance"] *= (1 - stock_pct * crash_magnitude)

        total_bal = sum(a["balance"] for a in accts)
        if total_bal <= 0 and depleted_age is None:
            depleted_age = age
        portfolio_by_age.append(total_bal)

        # Stochastic inflation — affects spending next year and SS COLA
        infl_this_year = float(max(-0.01, inflation_mean + INFLATION_VOL * infl_zs[t]))
        spending *= 1 + infl_this_year
        ss_benefit *= 1 + infl_this_year
        spouse_ss *= 1 + infl_this_year

    return portfolio_by_age, depleted_age


def run_monte_carlo_v2(
    accounts_at_retirement: list[dict],
    profile: dict,
    assumptions: dict,
    n_runs: int = 1000,
    equity_vol: float = DEFAULT_EQUITY_VOL,
    bond_vol: float = DEFAULT_BOND_VOL,
    equity_bond_corr: float = DEFAULT_EQUITY_BOND_CORR,
    enable_crashes: bool = False,
    crash_magnitude: float = 0.20,
    stock_pct: float = 0.60,
    withdrawal_mode: str = "constant_real",
    seed: int | None = None,
) -> dict:
    rng = np.random.default_rng(seed)
    retirement_age = profile["retirement_age"]
    life_expectancy = profile["life_expectancy"]
    n_years = life_expectancy - retirement_age + 1
    ages = list(range(retirement_age, life_expectancy + 1))

    # Pre-generate all random numbers for all trials and years at once.
    # Cholesky for 2x2 [[1, rho], [rho, 1]]: L = [[1, 0], [rho, sqrt(1-rho^2)]]
    rho = equity_bond_corr
    z_raw = rng.standard_normal((n_runs, n_years, 2))
    equity_zs_all = z_raw[:, :, 0]
    bond_zs_all = rho * z_raw[:, :, 0] + np.sqrt(max(0.0, 1 - rho ** 2)) * z_raw[:, :, 1]
    infl_zs_all = rng.standard_normal((n_runs, n_years))

    all_runs: list[list[float]] = []
    depletion_ages: list[int] = []

    for i in range(n_runs):
        accts = copy.deepcopy(accounts_at_retirement)
        crash_years = (
            _generate_crash_years(rng, retirement_age, life_expectancy)
            if enable_crashes
            else set()
        )
        bal_series, dep_age = _mc_single_run_v2(
            accts, profile, assumptions,
            equity_zs_all[i], bond_zs_all[i], infl_zs_all[i],
            equity_vol, bond_vol,
            crash_years, crash_magnitude, stock_pct,
            withdrawal_mode,
        )
        all_runs.append(bal_series)
        if dep_age is not None:
            depletion_ages.append(dep_age)

    arr = np.array(all_runs)
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
        "volatility": equity_vol,      # compat key for chart_monte_carlo()
        "equity_vol": equity_vol,
        "bond_vol": bond_vol,
        "equity_bond_corr": equity_bond_corr,
        "enable_crashes": enable_crashes,
        "crash_magnitude": crash_magnitude,
        "stock_pct": stock_pct,
        "withdrawal_mode": withdrawal_mode,
    }
