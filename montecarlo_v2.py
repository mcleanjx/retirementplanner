"""
montecarlo_v2.py — CMA-based Monte Carlo engine

This engine generates stochastic per-year returns and inflation, then runs the
**exact deterministic plan** for each trial by delegating to
``withdrawals.simulate_retirement``. That means every trial models the same
strategy the Retirement tab and Optimizer use — Roth conversions, 0%-bracket
capital-gains harvesting, planned rebalancing, the tax-efficient fill-to-bracket
withdrawal order, SS taxability, IRMAA/NIIT, RMDs and survivor transition — under
randomized markets. Earlier versions re-implemented a simplified (tax-light,
no-conversion) withdrawal loop here, which made the MC results diverge from the
deterministic projection; that duplication has been removed.

Return model per investment account per year:

  Log-normal returns
    r = exp(log_mu + vol*z) - 1 where log_mu = log(1+mean) - 0.5*vol^2.
    Bounds the left tail at -100% and corrects the arithmetic/geometric gap.

  Correlated equity/bond factors
    One shared equity factor and one shared bond factor per year via Cholesky of a
    2x2 correlation matrix (default corr 0.10). Equity-heavy accounts are driven by
    the equity factor, bond-heavy/real-estate by the bond factor.

  Stochastic inflation
    Inflation each year ~ N(inflation_mean, 1.5%), passed to simulate_retirement so
    spending, SS COLA and healthcare vary across the horizon.

  CMA-calibrated default volatilities
    equity_vol=15.5%, bond_vol=5.5% (JPM/Vanguard/BlackRock 10-15yr CMA consensus).

Each account's per-year return is precomputed here and injected into
simulate_retirement via its ``market_returns`` hook; the realized inflation path is
injected via ``inflation_sequence``. Guyton-Klinger guardrails and the spending
floor are passed through assumptions (handled inside simulate_retirement).

_equity_bond_means() preserves the equity risk premium (3pp) while ensuring the
blended return equals port_mean (= ret_return or the account's own rate).

Variance reduction (M3 + L4)
    Optional Sobol quasi-random draws (scipy) and/or antithetic variates reduce
    the sampling error on success rate / percentile bands at fixed n_runs. Both
    default on; Sobol gracefully falls back to pseudorandom if scipy is missing.

CMA presets (M1)
    ``cma_preset`` selects a published forward-looking capital market assumption
    set (Vanguard / BlackRock / JPM 2026, plus the 2022-era spec consensus).
    A preset overrides equity_mean, bond_mean, equity_vol, and bond_vol for
    accounts using the global rate. Per-account rate overrides
    (use_global_return_rate=False) are unaffected.

Adjustment metrics (H2)
    When run under guardrails, the result dict carries probabilities and averages
    of GK cuts / raises / floor clamps so callers can report Kitces-style
    "probability of adjustment" alongside the headline success rate.
"""

import numpy as np
from withdrawals import simulate_retirement

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

# Forward-looking CMA presets. Means/vols feed _build_market_returns directly so
# the preset *replaces* the derived (ret_return ± ERP) equity/bond means for any
# account using the global rate. Per-account overrides (use_global_return_rate=False)
# still drive their own returns via _equity_bond_means(stock_pct, own_rate).
CMA_PRESETS: dict[str, dict] = {
    "vanguard_2026": {
        "label": "Vanguard 2026 VCMM (mid)",
        "equity_mean": 0.045,
        "bond_mean": 0.045,
        "equity_vol": 0.165,
        "bond_vol": 0.060,
        "description": "Vanguard 2026 10y: US equity 3.5–5.5% mid, US agg ~4.5%.",
    },
    "blackrock_2026": {
        "label": "BlackRock late-2025",
        "equity_mean": 0.050,
        "bond_mean": 0.041,
        "equity_vol": 0.160,
        "bond_vol": 0.055,
        "description": "BlackRock late-2025: US equity ~5.0%, US agg ~4.1%.",
    },
    "jpm_2026": {
        "label": "JPMorgan 2026 LTCMA",
        "equity_mean": 0.065,
        "bond_mean": 0.045,
        "equity_vol": 0.155,
        "bond_vol": 0.055,
        "description": "JPMorgan 2026 LTCMA: US LC ~6.5%, US agg ~4.5%.",
    },
    "original_2022": {
        "label": "2022 spec consensus",
        "equity_mean": 0.075,
        "bond_mean": 0.045,
        "equity_vol": 0.155,
        "bond_vol": 0.055,
        "description": "Original spec defaults — 2022-era CMA consensus.",
    },
}


def _first_year_crash(sim_start_age: int) -> set[int]:
    """
    Model sequence-of-returns risk: a single market crash in the first year of
    retirement (the simulation's first year). Returned as a one-element set so it
    feeds the same crash-application path as before. Deterministic across trials —
    the same first-year shock is applied to every trial, on top of its random draw.
    """
    return {sim_start_age}


def _deterministic_year_returns(accts: list[dict], ret_return: float) -> dict:
    """
    Per-account return dict matching what the *deterministic* simulate_retirement
    would apply in a year (withdrawals.py Step 7 else-branch): rental/bank and
    per-account-override accounts use their own rate; everything else uses the
    global retirement return. Used to pin the first simulated year so the
    near-term recommendation is a concrete figure, not an MC draw.
    """
    out: dict = {}
    for a in accts:
        always_own = a["type"] in {"rental_property", "bank"}
        if always_own or not a.get("use_global_return_rate", True):
            out[a["id"]] = a.get("return_rate", 0.05)
        else:
            out[a["id"]] = ret_return
    return out


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


def _draw_normals(
    n_runs: int,
    dim: int,
    rng,
    quasi_random: bool,
    antithetic: bool,
    seed: int | None,
) -> np.ndarray:
    """
    Variance-reduced standard-normal draws, shape (n_runs, dim).

    quasi_random=True uses Sobol (scipy.stats.qmc) with inverse-CDF mapping; Sobol
    sequences fill the unit hypercube more uniformly than pseudorandom, sharpening
    aggregate statistics (success rate, percentiles) at fixed sample count. Falls
    back silently to pseudorandom if scipy is missing.

    antithetic=True pairs each draw with its negation, halving the variance of any
    statistic monotone in the draw. Cheap; composes with Sobol (the second half
    becomes the antithetic reflection of the first).
    """
    n_base = (n_runs + 1) // 2 if antithetic else n_runs
    z_base = None
    if quasi_random:
        try:
            from scipy.stats import qmc
            from scipy.special import ndtri
            sampler = qmc.Sobol(d=dim, scramble=True, seed=seed)
            # Sobol balance holds best at power-of-2 sample counts; pad and slice.
            pow2 = 1
            while pow2 < max(2, n_base):
                pow2 *= 2
            import warnings as _w
            with _w.catch_warnings():
                _w.simplefilter("ignore")
                u = sampler.random(pow2)[:n_base]
            u = np.clip(u, 1e-10, 1 - 1e-10)
            z_base = ndtri(u)
        except ImportError:
            z_base = None
    if z_base is None:
        z_base = rng.standard_normal((n_base, dim))
    if antithetic:
        z = np.concatenate([z_base, -z_base], axis=0)[:n_runs]
    else:
        z = z_base[:n_runs]
    return z


def _build_market_returns(
    accts: list[dict],
    ages: list[int],
    equity_zs: np.ndarray,
    bond_zs: np.ndarray,
    equity_vol: float,
    bond_vol: float,
    ret_return: float,
    stock_pct: float,
    crash_years: set[int],
    crash_magnitude: float,
    eq_mean_override: float | None = None,
    bd_mean_override: float | None = None,
) -> list[dict]:
    """
    Per-simulation-year, per-account return dicts replicating the v2 CMA log-normal
    model. Returned as ``[{account_id: return_rate}, ...]`` aligned with ``ages``,
    ready to feed simulate_retirement's ``market_returns`` hook. Crash shocks are
    baked in so simulate_retirement applies a single growth factor per account.

    When eq_mean_override / bd_mean_override are supplied (CMA preset), accounts
    using the global rate get those means directly. Per-account overrides
    (use_global_return_rate=False) still derive via _equity_bond_means(stock_pct,
    own_rate) so user-specified rates remain authoritative.
    """
    bond_pct = 1.0 - stock_pct
    out: list[dict] = []
    for t, age in enumerate(ages):
        ez = float(equity_zs[t])
        bz = float(bond_zs[t])
        year: dict = {}
        for a in accts:
            atype = a["type"]
            if atype == "bank":
                base = a.get("return_rate", 0.04)
                v = equity_vol * 0.10
                log_mu = np.log(max(1e-6, 1.0 + base)) - 0.5 * v ** 2
                r = float(np.exp(log_mu + v * ez) - 1.0)
            elif atype == "rental_property":
                base = a.get("return_rate", 0.04)
                v = equity_vol * 0.40
                log_mu = np.log(max(1e-6, 1.0 + base)) - 0.5 * v ** 2
                r = float(np.exp(log_mu + v * bz) - 1.0)
            else:
                if eq_mean_override is not None and a.get("use_global_return_rate", True):
                    eq_mean, bd_mean = eq_mean_override, bd_mean_override
                else:
                    port_mean = (
                        a.get("return_rate", ret_return)
                        if not a.get("use_global_return_rate", True)
                        else ret_return
                    )
                    eq_mean, bd_mean = _equity_bond_means(stock_pct, port_mean)
                eq_log_mu = np.log(max(1e-6, 1.0 + eq_mean)) - 0.5 * equity_vol ** 2
                bd_log_mu = np.log(max(1e-6, 1.0 + bd_mean)) - 0.5 * bond_vol ** 2
                eq_r = float(np.exp(eq_log_mu + equity_vol * ez) - 1.0)
                bd_r = float(np.exp(bd_log_mu + bond_vol * bz) - 1.0)
                r = stock_pct * eq_r + bond_pct * bd_r

            r = max(-0.95, r)
            if age in crash_years and atype in CRASH_AFFECTED_TYPES:
                r = (1.0 + r) * (1.0 - stock_pct * crash_magnitude) - 1.0
            year[a["id"]] = r
        out.append(year)
    return out


def _mc_single_run_v2(
    accts: list[dict],
    profile: dict,
    assumptions: dict,
    roth_conversion: dict | None,
    spending_overrides: dict | None,
    equity_zs: np.ndarray,
    bond_zs: np.ndarray,
    infl_zs: np.ndarray,
    equity_vol: float,
    bond_vol: float,
    crash_years: set[int],
    crash_magnitude: float,
    stock_pct: float,
    withdrawal_mode: str = "constant_real",
    spending_floor: float = 0.0,
    eq_mean_override: float | None = None,
    bd_mean_override: float | None = None,
    deterministic_first_year: bool = False,
) -> tuple[list[float], dict]:
    """One trial: build the stochastic return/inflation paths and run the full plan.
    Returns (portfolio_by_age, trial_summary) where trial_summary carries depletion
    age, lifetime after-tax spend, and the GK adjustment counters surfaced via
    simulate_retirement.

    When deterministic_first_year is set, the first simulated year's per-account
    returns and inflation are pinned to their deterministic values (the rest of the
    horizon stays stochastic). This makes the near-term, actionable recommendation
    reproducible from known balances while long-horizon risk is still MC-driven."""
    retirement_age = profile["retirement_age"]
    life_expectancy = profile["life_expectancy"]
    current_age = profile.get("current_age", retirement_age)
    sim_start_age = max(retirement_age, current_age)
    ages = list(range(sim_start_age, life_expectancy + 1))

    inflation_mean = assumptions.get("inflation_rate", 0.03)
    ret_return = assumptions.get("retirement_return_rate", 0.065)

    market_returns = _build_market_returns(
        accts, ages, equity_zs, bond_zs, equity_vol, bond_vol,
        ret_return, stock_pct, crash_years, crash_magnitude,
        eq_mean_override, bd_mean_override,
    )
    inflation_sequence = [
        float(max(-0.01, inflation_mean + INFLATION_VOL * float(infl_zs[t])))
        for t in range(len(ages))
    ]

    if deterministic_first_year and market_returns:
        # Pin year 0 to the deterministic plan: known balances → concrete near-term
        # action. Any first-year crash shock is intentionally not applied here.
        market_returns[0] = _deterministic_year_returns(accts, ret_return)
        inflation_sequence[0] = inflation_mean

    trial_assumptions = {
        **assumptions,
        "withdrawal_mode": withdrawal_mode,
        "spending_floor": spending_floor,
    }

    df, summary = simulate_retirement(
        accts, profile, trial_assumptions, roth_conversion, spending_overrides,
        market_returns=market_returns, inflation_sequence=inflation_sequence,
    )

    portfolio_by_age = df["total_portfolio"].tolist() if not df.empty else [0.0] * len(ages)
    lifetime_spend = float(df["actual_after_tax_net"].sum()) if not df.empty else 0.0
    trial_summary = {
        "portfolio_depleted_age": summary.get("portfolio_depleted_age"),
        "lifetime_spend": lifetime_spend,
        "gk_cuts": summary.get("gk_cuts", 0),
        "gk_raises": summary.get("gk_raises", 0),
        "gk_floor_clamps": summary.get("gk_floor_clamps", 0),
        "gk_min_real_ratio": summary.get("gk_min_real_ratio", 1.0),
    }
    return portfolio_by_age, trial_summary


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
    spending_floor: float = 0.0,
    roth_conversion: dict | None = None,
    spending_overrides: dict | None = None,
    seed: int | None = None,
    cma_preset: str | None = None,
    quasi_random: bool = True,
    antithetic: bool = True,
    deterministic_first_year: bool = False,
) -> dict:
    rng = np.random.default_rng(seed)
    retirement_age = profile["retirement_age"]
    life_expectancy = profile["life_expectancy"]
    # Already-retired support: start at current_age when it exceeds retirement_age, so the
    # MC horizon matches simulate_retirement and the deterministic baseline overlay aligns.
    sim_start_age = max(retirement_age, profile.get("current_age", retirement_age))
    n_years = life_expectancy - sim_start_age + 1
    ages = list(range(sim_start_age, life_expectancy + 1))

    # CMA preset overrides equity/bond vol + mean for accounts using the global rate.
    eq_mean_override = None
    bd_mean_override = None
    preset_meta = None
    if cma_preset and cma_preset in CMA_PRESETS:
        preset_meta = CMA_PRESETS[cma_preset]
        equity_vol = preset_meta["equity_vol"]
        bond_vol = preset_meta["bond_vol"]
        eq_mean_override = preset_meta["equity_mean"]
        bd_mean_override = preset_meta["bond_mean"]

    # Pre-generate all random numbers for all trials and years at once via Sobol +
    # antithetic when enabled. Layout: dim 0 = raw equity z, dim 1 = raw bond z
    # (Cholesky-rotated below), dim 2 = inflation z.
    z = _draw_normals(n_runs, n_years * 3, rng, quasi_random, antithetic, seed)
    z = z.reshape(n_runs, n_years, 3)
    rho = equity_bond_corr
    equity_zs_all = z[:, :, 0]
    bond_zs_all = rho * z[:, :, 0] + np.sqrt(max(0.0, 1 - rho ** 2)) * z[:, :, 1]
    infl_zs_all = z[:, :, 2]

    all_runs: list[list[float]] = []
    depletion_ages: list[int] = []
    spend_per_trial: list[float] = []
    gk_cuts_per_trial: list[int] = []
    gk_raises_per_trial: list[int] = []
    gk_floor_per_trial: list[int] = []
    gk_min_real_per_trial: list[float] = []

    for i in range(n_runs):
        # simulate_retirement deep-copies accounts internally, and _build_market_returns
        # only reads metadata, so the shared list is safe to pass without a per-trial copy.
        crash_years = _first_year_crash(sim_start_age) if enable_crashes else set()
        bal_series, trial_summary = _mc_single_run_v2(
            accounts_at_retirement, profile, assumptions,
            roth_conversion, spending_overrides,
            equity_zs_all[i], bond_zs_all[i], infl_zs_all[i],
            equity_vol, bond_vol,
            crash_years, crash_magnitude, stock_pct,
            withdrawal_mode, spending_floor,
            eq_mean_override, bd_mean_override,
            deterministic_first_year,
        )
        all_runs.append(bal_series)
        spend_per_trial.append(trial_summary["lifetime_spend"])
        if trial_summary["portfolio_depleted_age"] is not None:
            depletion_ages.append(trial_summary["portfolio_depleted_age"])
        gk_cuts_per_trial.append(trial_summary["gk_cuts"])
        gk_raises_per_trial.append(trial_summary["gk_raises"])
        gk_floor_per_trial.append(trial_summary["gk_floor_clamps"])
        gk_min_real_per_trial.append(trial_summary["gk_min_real_ratio"])

    arr = np.array(all_runs)
    success_rate = 1.0 - len(depletion_ages) / n_runs
    percentiles = {
        p: np.percentile(arr, p, axis=0).tolist()
        for p in [10, 25, 50, 75, 90]
    }

    # Cross-trial distributions for strategy scoring (optimizer_v3): final-year
    # legacy and full-horizon lifetime after-tax spend. final_percentiles[p] is the
    # p-th percentile of the terminal portfolio; spend_percentiles[p] the p-th
    # percentile of summed real-dollar spending across the horizon.
    final_arr = arr[:, -1] if arr.size else np.zeros(n_runs)
    spend_arr = np.array(spend_per_trial) if spend_per_trial else np.zeros(n_runs)
    final_percentiles = {p: float(np.percentile(final_arr, p)) for p in [10, 25, 50, 75, 90]}
    spend_percentiles = {p: float(np.percentile(spend_arr, p)) for p in [10, 25, 50, 75, 90]}

    # Adjustment metrics — Kitces' reframing of pure success rate. In constant_real
    # mode these stay zero (no GK firings, real ratio == 1.0); they only carry
    # information under withdrawal_mode == "guardrails".
    cuts_arr = np.array(gk_cuts_per_trial)
    raises_arr = np.array(gk_raises_per_trial)
    floor_arr = np.array(gk_floor_per_trial)
    min_real_arr = np.array(gk_min_real_per_trial)
    adjustment_metrics = {
        "prob_any_cut": float((cuts_arr > 0).mean()),
        "prob_any_raise": float((raises_arr > 0).mean()),
        "prob_any_floor_hit": float((floor_arr > 0).mean()),
        "avg_cuts_per_trial": float(cuts_arr.mean()),
        "avg_raises_per_trial": float(raises_arr.mean()),
        "avg_floor_years_per_trial": float(floor_arr.mean()),
        "min_real_ratio_p10": float(np.percentile(min_real_arr, 10)),
        "min_real_ratio_p50": float(np.percentile(min_real_arr, 50)),
        "min_real_ratio_p90": float(np.percentile(min_real_arr, 90)),
    }

    return {
        "ages": ages,
        "percentiles": percentiles,
        "final_percentiles": final_percentiles,
        "spend_percentiles": spend_percentiles,
        "success_rate": success_rate,
        "n_runs": n_runs,
        "n_depleted": len(depletion_ages),
        "depletion_ages": depletion_ages,
        "deterministic_first_year": deterministic_first_year,
        "volatility": equity_vol,      # compat key for chart_monte_carlo()
        "equity_vol": equity_vol,
        "bond_vol": bond_vol,
        "equity_bond_corr": equity_bond_corr,
        "enable_crashes": enable_crashes,
        "crash_magnitude": crash_magnitude,
        "stock_pct": stock_pct,
        "withdrawal_mode": withdrawal_mode,
        "spending_floor": spending_floor,
        "cma_preset": cma_preset,
        "cma_preset_meta": preset_meta,
        "quasi_random": quasi_random,
        "antithetic": antithetic,
        "adjustment_metrics": adjustment_metrics,
    }
