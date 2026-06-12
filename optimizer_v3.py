"""
optimizer_v3.py — MC-aware, receding-horizon strategy optimizer.

Where v1/v2 score each candidate strategy against a *single deterministic*
`simulate_retirement` run, v3 scores each candidate against a **Monte Carlo
distribution** (via `montecarlo_v2.run_monte_carlo_v2`), so the search rewards
strategies that are robust across bad return sequences rather than ones that
merely win on the single mean-return path.

Designed to be re-run every year as actual balances change (each Progress-tab
check-in re-anchors the scenario's `current_age` and balances):

  • First simulated year is DETERMINISTIC — the recommended action for *this*
    year (convert $X, withdraw from account Y, claim SS) is a concrete figure
    from known balances, reproducible and free of MC noise.
  • Years 2…N are MC-driven — long-horizon success, downside legacy, median
    spending, and Guyton-Klinger adjustment frequency come from the stochastic
    fan, not a point estimate.

Cost control (the search now evaluates an MC per candidate, not one sim):

  • Successive halving — every candidate is screened at a low path count
    (`mc_runs_screen`); only the top `survivors` are re-scored at full fidelity
    (`mc_runs_final`). Full-fidelity cost is paid only on contenders.
  • Common Random Numbers (CRN) — every candidate faces the *same* MC draw set
    (fixed `mc_seed`), so score differences are signal, not sampling noise.
    Without CRN the optimizer suffers winner's-curse and ranks the lucky seed.
  • The single best survivor is re-confirmed at full fidelity with a *fresh*
    seed, guarding against overfitting to the CRN draw set.

Objective (robust / downside-first): maximize success rate first, then break
ties on downside (p25) legacy and median lifetime spending, penalizing frequent
guardrail cuts. See `_score_mc`.

Does NOT modify any scenario files, withdrawals.py, or the v1/v2 optimizers.
"""

import copy
import random
from typing import Optional

import pandas as pd

from withdrawals import simulate_retirement
from montecarlo_v2 import run_monte_carlo_v2
from optimizer import build_actions_table
from optimizer_v2 import _sample_strategy_v2, describe_strategy_v2

# --- Robust objective weights ------------------------------------------------
# Lifetime spend / legacy are in dollars (~$1M-$10M); success_rate is in [0, 1].
# SUCCESS_BONUS is large enough that any meaningful success-rate gap dominates
# the dollar terms, so the search prefers "survive first"; among near-equal
# success it falls back to downside legacy + median spend. CUT_PENALTY discounts
# plans that only "succeed" by repeatedly cutting spending under guardrails.
SUCCESS_BONUS = 10_000_000.0   # per unit success rate (1.0 = always solvent)
LEGACY_P_FOR_SCORE = 25        # downside percentile of terminal portfolio
CUT_PENALTY = 100_000.0        # per expected guardrail cut per trial


def _score_mc(mc: dict, legacy_weight: float) -> float:
    """
    Robust, downside-first score from a run_monte_carlo_v2 result dict.

    success_rate dominates; ties broken by downside (p25) legacy and median
    lifetime spend; expected guardrail cuts penalized.
    """
    if not mc or mc.get("n_runs", 0) == 0:
        return float("-inf")

    success = float(mc.get("success_rate", 0.0))
    p25_legacy = float(mc.get("final_percentiles", {}).get(LEGACY_P_FOR_SCORE, 0.0))
    p50_spend = float(mc.get("spend_percentiles", {}).get(50, 0.0))
    avg_cuts = float(mc.get("adjustment_metrics", {}).get("avg_cuts_per_trial", 0.0))

    return (
        success * SUCCESS_BONUS
        + p50_spend
        + legacy_weight * p25_legacy
        - avg_cuts * CUT_PENALTY
    )


# Knobs forwarded to run_monte_carlo_v2. Mirror the MC-tab defaults; the caller
# (app) can override with the user's actual MC settings so the optimizer scores
# against the same engine configuration the user sees on the Monte Carlo tab.
_DEFAULT_MC_CONFIG: dict = {
    "stock_pct": 0.60,
    "withdrawal_mode": "constant_real",
    "spending_floor": 0.0,
    "enable_crashes": False,
    "cma_preset": None,
    "quasi_random": True,
    "antithetic": True,
}


def _eval_strategy_mc(
    accounts_at_retirement: list,
    trial_profile: dict,
    trial_assumptions: dict,
    rc: dict,
    spending_overrides: dict,
    n_runs: int,
    mc_seed: int,
    mc_config: dict,
) -> dict:
    """Score one fully-specified strategy with a deterministic-first-year MC run."""
    return run_monte_carlo_v2(
        accounts_at_retirement=accounts_at_retirement,
        profile=trial_profile,
        assumptions=trial_assumptions,
        n_runs=n_runs,
        roth_conversion=rc,
        spending_overrides=spending_overrides,
        seed=mc_seed,
        deterministic_first_year=True,
        **{k: v for k, v in mc_config.items() if k in {
            "stock_pct", "withdrawal_mode", "spending_floor", "enable_crashes",
            "cma_preset", "quasi_random", "antithetic", "equity_vol", "bond_vol",
            "equity_bond_corr", "crash_magnitude",
        }},
    )


def _first_year_action(
    accounts_at_retirement: list,
    trial_profile: dict,
    trial_assumptions: dict,
    rc: dict,
    spending_overrides: dict,
    accounts: list,
) -> dict:
    """
    Concrete, deterministic action for the upcoming year, derived from a single
    deterministic simulate_retirement run (no market_returns) on known balances.

    Returns the first row of build_actions_table (per-account draws/conversions,
    taxes, realized gains, total spend) plus the Roth conversion this year.
    """
    df, _ = simulate_retirement(
        accounts_at_retirement, trial_profile, trial_assumptions, rc, spending_overrides,
    )
    if df is None or df.empty:
        return {}
    actions = build_actions_table(df, rc, accounts)
    row = actions.iloc[0].to_dict() if not actions.empty else {}
    row["Roth Conversion This Year"] = float(df.iloc[0].get("roth_conversion", 0.0))
    return row


def run_optimizer_v3(
    accounts_at_retirement: list,
    profile: dict,
    assumptions: dict,
    roth_conversion_baseline: Optional[dict],
    spending_overrides: Optional[dict],
    accounts: Optional[list] = None,
    n_iterations: int = 300,
    legacy_weight: float = 0.20,
    seed: int = 42,
    mc_runs_screen: int = 100,
    mc_runs_final: int = 1000,
    survivors: int = 15,
    mc_seed: int = 12345,
    mc_config: Optional[dict] = None,
) -> dict:
    """
    Receding-horizon MC-aware optimizer. Drop-in cousin of run_optimizer_v2 with
    an MC objective and successive-halving cost control.

    Args:
        accounts_at_retirement: balances at the simulation anchor (current_age once
            a check-in has re-anchored the scenario).
        accounts: original account dicts (for names in the first-year action table);
            defaults to accounts_at_retirement.
        n_iterations: candidate strategies sampled.
        mc_runs_screen / mc_runs_final: MC paths for screening vs. finalists.
        survivors: how many top screened candidates advance to full-fidelity scoring.
        mc_seed: Common Random Numbers seed shared by all candidates.
        mc_config: knobs forwarded to run_monte_carlo_v2 (stock_pct, withdrawal_mode,
            cma_preset, vols, etc.). Defaults mirror the MC-tab defaults.

    Returns a dict with baseline_result, best_result, top_results, n_evaluated,
    all_scores, plus best_result["recommendation"] — a JSON-serializable summary
    suitable for persisting alongside a Progress-tab check-in.
    """
    rng = random.Random(seed)
    spending_overrides = spending_overrides or {}
    accounts = accounts if accounts is not None else accounts_at_retirement
    cfg = {**_DEFAULT_MC_CONFIG, **(mc_config or {})}

    base_rc = copy.deepcopy(roth_conversion_baseline) or {"enabled": False}

    # --- Baseline: current settings, scored under the same MC objective ---
    try:
        base_mc = _eval_strategy_mc(
            accounts_at_retirement, profile, assumptions, base_rc,
            spending_overrides, mc_runs_final, mc_seed, cfg,
        )
        base_score = _score_mc(base_mc, legacy_weight)
    except Exception:
        base_mc, base_score = {}, float("-inf")

    baseline_result = {
        "score": base_score,
        "withdrawal_strategy": assumptions.get("withdrawal_strategy", "tax_efficient"),
        "roth_conversion": base_rc,
        "annual_rebalance_gain": assumptions.get("annual_rebalance_gain", 0.0),
        "profile_overrides": {},
        "mc": base_mc,
        "label": "Baseline (Current Settings)",
    }

    # --- Screening pass: every candidate at low fidelity, shared CRN seed ---
    screened: list[dict] = []
    all_scores: list[float] = []
    n_evaluated = 0

    for _ in range(n_iterations):
        w_strat, rc, prof_overrides, cliff_label, reb_gain = _sample_strategy_v2(
            profile, accounts_at_retirement, assumptions, rng
        )
        trial_profile = {**profile, **prof_overrides}
        trial_assumptions = {
            **assumptions,
            "withdrawal_strategy": w_strat,
            "annual_rebalance_gain": reb_gain,
        }
        try:
            mc = _eval_strategy_mc(
                accounts_at_retirement, trial_profile, trial_assumptions, rc,
                spending_overrides, mc_runs_screen, mc_seed, cfg,
            )
            sc = _score_mc(mc, legacy_weight)
        except Exception:
            continue

        n_evaluated += 1
        all_scores.append(sc)
        screened.append({
            "screen_score": sc,
            "withdrawal_strategy": w_strat,
            "roth_conversion": rc,
            "annual_rebalance_gain": reb_gain,
            "profile_overrides": prof_overrides,
            "cliff_label": cliff_label,
            "trial_profile": trial_profile,
            "trial_assumptions": trial_assumptions,
        })

    screened.sort(key=lambda r: r["screen_score"], reverse=True)

    # --- Finalist pass: re-score survivors at full fidelity (same CRN seed) ---
    finalists: list[dict] = []
    for cand in screened[:survivors]:
        try:
            mc = _eval_strategy_mc(
                accounts_at_retirement, cand["trial_profile"], cand["trial_assumptions"],
                cand["roth_conversion"], spending_overrides, mc_runs_final, mc_seed, cfg,
            )
            cand["score"] = _score_mc(mc, legacy_weight)
            cand["mc"] = mc
            cand["label"] = "Optimized"
            finalists.append(cand)
        except Exception:
            continue

    finalists.sort(key=lambda r: r["score"], reverse=True)

    if finalists:
        best = finalists[0]
        # Confirmation run with a fresh seed: detects overfit to the CRN draw set.
        try:
            confirm = _eval_strategy_mc(
                accounts_at_retirement, best["trial_profile"], best["trial_assumptions"],
                best["roth_conversion"], spending_overrides, mc_runs_final, mc_seed + 1, cfg,
            )
            best["mc_confirm"] = confirm
            best["confirm_score"] = _score_mc(confirm, legacy_weight)
        except Exception:
            best["mc_confirm"] = best.get("mc", {})

        action = _first_year_action(
            accounts_at_retirement, best["trial_profile"], best["trial_assumptions"],
            best["roth_conversion"], spending_overrides, accounts,
        )
        best_mc = best.get("mc", {})
        best["first_year_action"] = action
        best["recommendation"] = _build_recommendation(
            best, action, best_mc, base_mc, profile,
        )
        best_result = best
    else:
        best_result = copy.deepcopy(baseline_result)
        best_result["label"] = "Optimized"

    return {
        "baseline_result": baseline_result,
        "best_result": best_result,
        "top_results": finalists[:10],
        "n_evaluated": n_evaluated,
        "all_scores": all_scores,
        "mc_config": cfg,
        "mc_runs_screen": mc_runs_screen,
        "mc_runs_final": mc_runs_final,
    }


def _build_recommendation(
    best: dict, action: dict, best_mc: dict, base_mc: dict, profile: dict,
) -> dict:
    """JSON-serializable recommendation snapshot — suitable for persisting per check-in."""
    rc = best.get("roth_conversion", {})
    overrides = best.get("profile_overrides", {})
    # The deterministic action row is the first *simulated* year — the current year
    # once the anchor is in retirement, but the retirement year while still
    # accumulating. Record its age explicitly so the conversion figure isn't
    # mistaken for "this calendar year" when anchor_age < retirement_age.
    first_year_age = int(action.get("Age")) if action.get("Age") is not None else None
    return {
        "anchor_age": int(profile.get("current_age", 0)),
        "first_year_age": first_year_age,
        "withdrawal_strategy": best.get("withdrawal_strategy"),
        "roth_conversion_first_year": float(action.get("Roth Conversion This Year", 0.0)),
        "roth_conversion_config": rc if rc.get("enabled") else {"enabled": False},
        "ss_start_age": overrides.get("social_security_start_age", profile.get("social_security_start_age")),
        "spouse_ss_start_age": overrides.get("spouse_ss_start_age", profile.get("spouse_ss_start_age")),
        "annual_rebalance_gain": float(best.get("annual_rebalance_gain", 0.0)),
        "mc_success_rate": float(best_mc.get("success_rate", 0.0)),
        "mc_p25_legacy": float(best_mc.get("final_percentiles", {}).get(25, 0.0)),
        "mc_median_spend": float(best_mc.get("spend_percentiles", {}).get(50, 0.0)),
        "baseline_success_rate": float(base_mc.get("success_rate", 0.0)) if base_mc else None,
    }
