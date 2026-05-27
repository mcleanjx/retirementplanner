"""
optimizer_v2.py — Strategy optimizer v2.

Extends v1 (optimizer.py) with three additional decision variables:
  1. Social Security start age — primary and spouse sampled independently (62–70)
  2. Pre-retirement cash buffer — shift 0–3 years of spending from invested accounts
     into cash before retiring; models the sequence-of-returns shield described by
     Kitces / Pfau. Cash earns its own account return_rate (typically ~3%) rather
     than the global retirement return rate.
  3. Spending smile — real spending declines 0–1.2%/yr in mid-retirement, reflecting
     Blanchett's empirical finding that retirees spend ~20% less in real terms by 75.

Does NOT modify optimizer.py, withdrawals.py, or any scenario files.
"""

import copy
import random
from typing import Optional

import pandas as pd

from withdrawals import simulate_retirement
from constants import RMD_START_AGE
from optimizer import (
    _owner_min_conv_age,
    _score,
    _describe_strategy,
    build_actions_table,
    build_balances_table,
    TRADITIONAL_TYPES,
    ROTH_TYPES,
    BRACKET_OPTIONS,
    WITHDRAWAL_STRATEGIES,
)

BANK_TYPES = {"bank"}
TAXABLE_TYPES = {"taxable", "reit"}

# Cash buffer: years of base spending held in cash/bank at retirement
CASH_BUFFER_OPTIONS = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0]

# Spending smile: real decline per year (Blanchett ~1%/yr is the empirical center)
SPENDING_SMILE_OPTIONS = [0.000, 0.003, 0.005, 0.008, 0.010, 0.012]

# SS start age range to explore (delayed credits: +8%/yr from 62 → 70)
SS_AGE_OPTIONS = list(range(62, 71))


# ---------------------------------------------------------------------------
# Helper: cash buffer
# ---------------------------------------------------------------------------

def _apply_cash_buffer(
    accounts: list, annual_spending: float, buffer_years: float
) -> list:
    """
    Shift `buffer_years × annual_spending` from investable accounts into the
    largest bank account, simulating a pre-retirement liquidity reserve.

    Draw order: taxable first, then Traditional, then Roth (tax-efficiency order).
    Never over-draws any account. Returns a deep copy — original is unmodified.
    """
    if buffer_years <= 0:
        return copy.deepcopy(accounts)

    accts = copy.deepcopy(accounts)
    bank_accounts = [a for a in accts if a["type"] in BANK_TYPES]
    if not bank_accounts:
        return accts  # nowhere to put the buffer — skip

    target_bank = max(bank_accounts, key=lambda a: a["balance"])
    total_needed = buffer_years * annual_spending

    source_priority = [TAXABLE_TYPES, TRADITIONAL_TYPES, ROTH_TYPES]
    remaining = total_needed

    for type_set in source_priority:
        if remaining <= 0:
            break
        candidates = [a for a in accts if a["type"] in type_set and a["balance"] > 0]
        total_avail = sum(a["balance"] for a in candidates)
        if total_avail <= 0:
            continue
        to_draw = min(remaining, total_avail)
        for a in candidates:
            share = to_draw * (a["balance"] / total_avail)
            a["balance"] = max(0.0, a["balance"] - share)
            remaining -= share

    actual_buffer = total_needed - remaining
    target_bank["balance"] += actual_buffer
    return accts


# ---------------------------------------------------------------------------
# Helper: spending smile
# ---------------------------------------------------------------------------

def _compute_smile_overrides(
    retirement_age: int,
    life_expectancy: int,
    base_spending: float,
    smile_rate: float,
    inflation: float,
    existing_overrides: dict,
) -> dict:
    """
    Return a spending_overrides dict with a year-by-year nominal spending path
    that grows at (inflation - smile_rate) instead of full inflation, producing
    a real spending decline of smile_rate per year.

    Ages already in existing_overrides are left unchanged (user intent respected).
    """
    if smile_rate <= 0:
        return existing_overrides

    overrides = dict(existing_overrides)
    for age in range(retirement_age, life_expectancy + 1):
        if age in overrides:
            continue
        years_in = age - retirement_age
        # Nominal growth at (inflation − smile_rate) → real decline of smile_rate/yr
        nominal_factor = (1.0 + inflation - smile_rate) ** years_in
        overrides[age] = base_spending * nominal_factor
    return overrides


# ---------------------------------------------------------------------------
# Strategy sampler (v2)
# ---------------------------------------------------------------------------

def _sample_strategy_v2(
    profile: dict,
    accounts: list,
    assumptions: dict,
    rng: random.Random,
) -> tuple[str, dict, dict, float, float]:
    """
    Sample a complete v2 strategy configuration.

    Returns:
        withdrawal_strategy : str
        roth_conversion     : dict
        profile_overrides   : dict  (keys to merge into profile for this trial)
        cash_buffer_years   : float
        smile_rate          : float
    """
    life_expectancy = profile.get("life_expectancy", 90)

    withdrawal_strategy = rng.choice(WITHDRAWAL_STRATEGIES)

    # --- SS start ages ---
    ss_start = rng.choice(SS_AGE_OPTIONS)
    profile_overrides: dict = {"social_security_start_age": ss_start}

    if profile.get("filing_status") == "married_filing_jointly":
        profile_overrides["spouse_ss_start_age"] = rng.choice(SS_AGE_OPTIONS)

    # --- Roth conversion (same logic as v1; window end adjusts to sampled ss_start) ---
    trad_accounts = [a for a in accounts if a["type"] in TRADITIONAL_TYPES]
    roth_accounts = [a for a in accounts if a["type"] in ROTH_TYPES]

    rc: dict = {"enabled": False}
    if bool(trad_accounts) and bool(roth_accounts) and rng.random() < 0.70:
        n_sources = rng.randint(1, len(trad_accounts))
        source_accounts = rng.sample(trad_accounts, n_sources)
        source_ids = [a["id"] for a in source_accounts]

        min_conv_age = max(
            max(_owner_min_conv_age(a, profile) for a in source_accounts),
            60,
        )
        conv_max_end = max(
            min_conv_age + 1,
            min(RMD_START_AGE - 1, ss_start - 1, life_expectancy - 5),
        )

        if min_conv_age <= conv_max_end:
            start_age = rng.randint(min_conv_age, min(min_conv_age + 5, conv_max_end))
            end_age = rng.randint(start_age, min(conv_max_end, start_age + 15))
            strategy = rng.choice(
                ["fill_to_bracket", "fill_to_bracket", "fill_to_bracket", "fixed_amount"]
            )
            target_bracket = rng.choice(BRACKET_OPTIONS)
            fixed_amount = float(
                rng.choice([5_000, 10_000, 20_000, 30_000, 50_000, 75_000, 100_000])
            )
            dest_id = rng.choice([a["id"] for a in roth_accounts])
            rc = {
                "enabled": True,
                "strategy": strategy,
                "target_bracket": target_bracket,
                "fixed_amount": fixed_amount,
                "start_age": int(start_age),
                "end_age": int(end_age),
                "source_account_ids": source_ids,
                "destination_account_id": dest_id,
            }

    # --- Cash buffer ---
    cash_buffer_years = rng.choice(CASH_BUFFER_OPTIONS)

    # --- Spending smile ---
    smile_rate = rng.choice(SPENDING_SMILE_OPTIONS)

    return withdrawal_strategy, rc, profile_overrides, cash_buffer_years, smile_rate


# ---------------------------------------------------------------------------
# Strategy description (v2 adds extra rows for new variables)
# ---------------------------------------------------------------------------

def describe_strategy_v2(
    withdrawal_strategy: str,
    roth_conversion: dict,
    accounts: list,
    profile_overrides: dict,
    cash_buffer_years: float,
    smile_rate: float,
    base_profile: dict,
) -> dict:
    """Human-readable description of a v2 strategy, extending v1's output."""
    desc = _describe_strategy(withdrawal_strategy, roth_conversion, accounts)

    orig_ss = base_profile.get("social_security_start_age", 67)
    new_ss = profile_overrides.get("social_security_start_age", orig_ss)
    ss_label = f"Age {new_ss}"
    if new_ss != orig_ss:
        delta_pct = (new_ss - 62) * 8
        ss_label += f"  (≈ +{delta_pct}% vs. age-62 benefit)"
    desc["SS Start Age (primary)"] = ss_label

    if base_profile.get("filing_status") == "married_filing_jointly":
        orig_spouse_ss = base_profile.get("spouse_ss_start_age", 67)
        new_spouse_ss = profile_overrides.get("spouse_ss_start_age", orig_spouse_ss)
        spouse_label = f"Age {new_spouse_ss}"
        if new_spouse_ss != orig_spouse_ss:
            delta_pct = (new_spouse_ss - 62) * 8
            spouse_label += f"  (≈ +{delta_pct}% vs. age-62 benefit)"
        desc["SS Start Age (spouse)"] = spouse_label

    if cash_buffer_years > 0:
        desc["Cash Buffer"] = (
            f"{cash_buffer_years:.1f} yr — shift that amount from invested accounts "
            "into cash before retiring (earns bank rate, shields against sequence risk)"
        )
    else:
        desc["Cash Buffer"] = "None (fully invested at retirement)"

    if smile_rate > 0:
        desc["Spending Smile"] = (
            f"Real spending declines {smile_rate:.1%}/yr — spending grows at "
            f"(inflation − {smile_rate:.1%}) nominally, reflecting Blanchett's "
            "finding that retirees naturally spend less in real terms through mid-retirement"
        )
    else:
        desc["Spending Smile"] = "Flat real spending (inflation-adjusted throughout)"

    return desc


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_optimizer_v2(
    accounts_at_retirement: list,
    profile: dict,
    assumptions: dict,
    roth_conversion_baseline: Optional[dict],
    spending_overrides: Optional[dict],
    n_iterations: int = 500,
    legacy_weight: float = 0.20,
    seed: int = 42,
) -> dict:
    """
    Run the v2 strategy optimizer over `n_iterations` random trials.

    Drop-in replacement for optimizer.run_optimizer() — returns the same dict
    structure with additional keys on each result:
        ss_start_age       : int | None
        spouse_ss_start_age: int | None
        cash_buffer_years  : float
        smile_rate         : float
        profile_overrides  : dict
    """
    rng = random.Random(seed)
    spending_overrides = spending_overrides or {}
    inflation = assumptions.get("inflation_rate", 0.03)
    retirement_age = profile["retirement_age"]
    life_expectancy = profile["life_expectancy"]

    # Compute base spending (mirrors simulate_retirement logic exactly)
    total_portfolio = sum(a["balance"] for a in accounts_at_retirement)
    spending_mode = assumptions.get("spending_mode", "swr")
    if spending_mode == "fixed":
        years_to_ret = retirement_age - profile["current_age"]
        base_spending = (
            assumptions.get("annual_spending_target", total_portfolio * assumptions.get("safe_withdrawal_rate", 0.04))
            * (1 + inflation) ** years_to_ret
        )
    else:
        base_spending = total_portfolio * assumptions.get("safe_withdrawal_rate", 0.04)

    # --- Baseline (current settings, unmodified) ---
    try:
        base_df, base_summary = simulate_retirement(
            accounts_at_retirement, profile, assumptions,
            roth_conversion_baseline, spending_overrides,
        )
        base_score = _score(base_df, base_summary, legacy_weight)
    except Exception:
        base_df, base_summary, base_score = pd.DataFrame(), {}, float("-inf")

    baseline_result = {
        "score": base_score,
        "withdrawal_strategy": assumptions.get("withdrawal_strategy", "tax_efficient"),
        "roth_conversion": copy.deepcopy(roth_conversion_baseline) or {"enabled": False},
        "ret_df": base_df,
        "summary": base_summary,
        "label": "Baseline (Current Settings)",
        "profile_overrides": {},
        "ss_start_age": profile.get("social_security_start_age"),
        "spouse_ss_start_age": profile.get("spouse_ss_start_age"),
        "cash_buffer_years": 0.0,
        "smile_rate": 0.0,
    }

    # --- Random search ---
    results = []
    all_scores: list[float] = []
    n_evaluated = 0

    for _ in range(n_iterations):
        w_strat, rc, prof_overrides, cash_buffer_years, smile_rate = _sample_strategy_v2(
            profile, accounts_at_retirement, assumptions, rng
        )

        trial_profile = {**profile, **prof_overrides}
        trial_assumptions = {**assumptions, "withdrawal_strategy": w_strat}
        trial_accounts = _apply_cash_buffer(
            accounts_at_retirement, base_spending, cash_buffer_years
        )
        trial_overrides = _compute_smile_overrides(
            retirement_age, life_expectancy, base_spending,
            smile_rate, inflation, spending_overrides,
        )

        try:
            ret_df, sim_summary = simulate_retirement(
                trial_accounts, trial_profile, trial_assumptions, rc, trial_overrides,
            )
            sc = _score(ret_df, sim_summary, legacy_weight)
            n_evaluated += 1
            all_scores.append(sc)
            results.append({
                "score": sc,
                "withdrawal_strategy": w_strat,
                "roth_conversion": rc,
                "ret_df": ret_df,
                "summary": sim_summary,
                "label": "Optimized",
                "profile_overrides": prof_overrides,
                "ss_start_age": prof_overrides.get("social_security_start_age"),
                "spouse_ss_start_age": prof_overrides.get("spouse_ss_start_age"),
                "cash_buffer_years": cash_buffer_years,
                "smile_rate": smile_rate,
            })
        except Exception:
            continue

    results.sort(key=lambda r: r["score"], reverse=True)
    best_result = results[0] if results else copy.deepcopy(baseline_result)
    best_result["label"] = "Optimized"

    return {
        "baseline_result": baseline_result,
        "best_result": best_result,
        "top_results": results[:10],
        "n_evaluated": n_evaluated,
        "all_scores": all_scores,
    }
