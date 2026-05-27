"""
optimizer_v2.py — Strategy optimizer v2.

Extends v1 (optimizer.py) with two additional decision variables that have
real, deterministic dollar impact:

  1. Social Security start age (62–70) for primary and spouse — unchanged from
     the first v2 draft; 8%/yr delay credit is fully modeled in simulate_retirement.

  2. IRMAA-aware Roth conversions — for conversion windows that overlap Medicare
     ages (65+), cap conversions just below the IRMAA Tier-0 income threshold
     ($218K MFJ / $109K single). Breaching that cliff adds $1,148–$6,936/person/yr
     in Medicare Part B+D surcharges; the sim already charges these costs, so the
     optimizer naturally rewards avoiding them.

  3. ACA-aware Roth conversions — for pre-65 retirement windows, cap conversions
     below the ACA 400% FPL cliff (~$84.6K MFJ / $62.7K single). Staying under
     saves $10K–$20K/yr in marketplace premiums (the enhanced subsidies expired
     end of 2025; the cliff is a hard cutoff again in 2026).

What was removed vs. the previous v2 draft:
  - Cash buffer: sequence-of-returns protection has no value in a deterministic
    (fixed-return) simulator; the optimizer would always score buffer = 0.
  - Spending smile: recommending lower spending to improve portfolio score is a
    circular incentive, not a genuine strategy improvement.

Does NOT modify optimizer.py, withdrawals.py, or any scenario files.
"""

import copy
import random
from typing import Optional

import pandas as pd

from withdrawals import simulate_retirement
from constants import RMD_START_AGE, IRMAA_TIERS
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

# SS start age range (delayed retirement credits: +8%/yr from 62 → 70)
SS_AGE_OPTIONS = list(range(62, 71))

# IRMAA Tier-0 income ceilings (2026) — staying below avoids ALL Medicare surcharges
IRMAA_CEILING_MFJ    = 218_000
IRMAA_CEILING_SINGLE = 109_000

# ACA 400% FPL income ceilings (~2026) — staying below preserves Premium Tax Credit
# Enhanced subsidies expired end-2025; cliff is a hard cutoff again in 2026.
ACA_CLIFF_MFJ    = 84_600   # ~400% FPL, household of 2
ACA_CLIFF_SINGLE = 62_700   # ~400% FPL, household of 1


# ---------------------------------------------------------------------------
# Income estimation helpers
# ---------------------------------------------------------------------------

def _estimate_nonconv_income(
    profile: dict,
    accounts: list,
    assumptions: dict,
    at_age: int,
    ss_start_override: Optional[int] = None,
    spouse_ss_start_override: Optional[int] = None,
) -> float:
    """
    Estimate non-Roth-conversion MAGI at `at_age`.

    Includes: Social Security (100% counts for ACA/IRMAA MAGI),
    taxable investment income (dividends/interest), and rental income.
    Excludes: Roth conversions (those are what we are trying to limit),
    Traditional withdrawals, and RMDs (this is called for pre-RMD ages).

    Uses retirement-date account balances as a proxy for investment income;
    growth between now and `at_age` is intentionally omitted to keep the
    estimate conservative (i.e., headroom may be slightly overstated).
    """
    inflation = assumptions.get("inflation_rate", 0.03)
    years_to_ret = profile["retirement_age"] - profile["current_age"]
    years_from_ret = max(0, at_age - profile["retirement_age"])
    inflate = (1 + inflation) ** (years_to_ret + years_from_ret)

    filing = profile.get("filing_status", "single")
    is_mfj = filing == "married_filing_jointly"

    ss_start = ss_start_override or profile.get("social_security_start_age", 67)
    primary_ss = profile.get("social_security_benefit", 0.0) * inflate if at_age >= ss_start else 0.0

    spouse_ss = 0.0
    if is_mfj:
        sp_ss_start = spouse_ss_start_override or profile.get("spouse_ss_start_age", 67)
        sp_offset = profile.get("spouse_age", profile.get("current_age", 0)) - profile.get("current_age", 0)
        if at_age + sp_offset >= sp_ss_start:
            spouse_ss = profile.get("spouse_ss_benefit", 0.0) * inflate

    # Taxable investment income: dividends + interest at retirement-date balances
    inv_income = sum(
        a["balance"] * (a.get("ordinary_income_yield", 0.0) + a.get("qualified_dividend_yield", 0.0))
        for a in accounts
        if a.get("type") in {"taxable", "reit"}
    )

    rental = sum(
        a.get("net_annual_rental_income", 0.0)
        for a in accounts
        if a.get("type") == "rental_property"
    )

    return primary_ss + spouse_ss + inv_income + rental


def _irmaa_headroom(
    profile: dict,
    accounts: list,
    assumptions: dict,
    ss_start: int,
    spouse_ss_start: Optional[int] = None,
) -> float:
    """
    Estimated Roth conversion headroom before hitting IRMAA Tier-0 (no surcharge).

    Uses age 68 as the representative Medicare conversion year: post-65,
    pre-RMD (age 73), likely within the conversion window.
    Returns 0 if estimated non-conversion income already exceeds the ceiling.
    """
    filing = profile.get("filing_status", "single")
    ceiling = IRMAA_CEILING_MFJ if filing == "married_filing_jointly" else IRMAA_CEILING_SINGLE
    rep_age = max(65, profile.get("retirement_age", 65))
    income = _estimate_nonconv_income(profile, accounts, assumptions, rep_age, ss_start, spouse_ss_start)
    return max(0.0, ceiling - income)


def _aca_headroom(
    profile: dict,
    accounts: list,
    assumptions: dict,
    ss_start: int,
    spouse_ss_start: Optional[int] = None,
) -> float:
    """
    Estimated Roth conversion headroom before hitting the ACA 400% FPL cliff.

    Uses the retirement age as the representative pre-65 year: this is when
    marketplace coverage costs are highest (no Medicare yet, no employer plan).
    Returns 0 if income already exceeds the cliff (no ACA headroom available).
    """
    filing = profile.get("filing_status", "single")
    cliff = ACA_CLIFF_MFJ if filing == "married_filing_jointly" else ACA_CLIFF_SINGLE
    rep_age = profile.get("retirement_age", 62)
    income = _estimate_nonconv_income(profile, accounts, assumptions, rep_age, ss_start, spouse_ss_start)
    return max(0.0, cliff - income)


# ---------------------------------------------------------------------------
# Roth conversion sampler (v2 — cliff-aware)
# ---------------------------------------------------------------------------

def _sample_roth_conversion(
    profile: dict,
    accounts: list,
    assumptions: dict,
    rng: random.Random,
    ss_start: int,
    spouse_ss_start: Optional[int] = None,
) -> tuple[dict, Optional[str]]:
    """
    Sample a Roth conversion configuration, adding IRMAA-safe and ACA-safe
    fixed amounts to the standard v1 bracket/amount options.

    Returns (rc_dict, cliff_label) where cliff_label is one of:
        "irmaa"    — fixed_amount capped at IRMAA Tier-0 headroom
        "aca"      — fixed_amount capped at ACA 400%-FPL headroom
        None       — standard v1 fill_to_bracket or arbitrary fixed_amount
    """
    life_expectancy = profile.get("life_expectancy", 90)

    trad = [a for a in accounts if a["type"] in TRADITIONAL_TYPES]
    roth = [a for a in accounts if a["type"] in ROTH_TYPES]

    if not (trad and roth and rng.random() < 0.70):
        return {"enabled": False}, None

    n_sources = rng.randint(1, len(trad))
    source_accounts = rng.sample(trad, n_sources)
    source_ids = [a["id"] for a in source_accounts]

    min_conv_age = max(
        max(_owner_min_conv_age(a, profile) for a in source_accounts),
        60,
    )
    conv_max_end = max(
        min_conv_age + 1,
        min(RMD_START_AGE - 1, ss_start - 1, life_expectancy - 5),
    )
    if min_conv_age > conv_max_end:
        return {"enabled": False}, None

    start_age = rng.randint(min_conv_age, min(min_conv_age + 5, conv_max_end))
    end_age   = rng.randint(start_age, min(conv_max_end, start_age + 15))
    dest_id   = rng.choice([a["id"] for a in roth])

    # --- Determine which cliff strategies are relevant for this window ---
    window_has_pre65   = start_age < 65 and profile.get("retirement_age", 65) < 65
    window_has_medicare = end_age >= 65

    irmaa_amount = _irmaa_headroom(profile, accounts, assumptions, ss_start, spouse_ss_start)
    aca_amount   = _aca_headroom(profile, accounts, assumptions, ss_start, spouse_ss_start)

    # Build a weighted strategy menu.
    # Each entry: (strategy_type, target_bracket_or_None, fixed_amount_or_None, cliff_label)
    menu = [
        ("fill_to_bracket", rng.choice(BRACKET_OPTIONS), None, None),
        ("fill_to_bracket", rng.choice(BRACKET_OPTIONS), None, None),
        ("fill_to_bracket", rng.choice(BRACKET_OPTIONS), None, None),
        ("fixed_amount", None, float(rng.choice([5_000, 10_000, 20_000, 30_000, 50_000, 75_000, 100_000])), None),
    ]
    if window_has_medicare and irmaa_amount > 5_000:
        menu.append(("fixed_amount", None, round(irmaa_amount, -3), "irmaa"))
        menu.append(("fixed_amount", None, round(irmaa_amount, -3), "irmaa"))  # 2× weight
    if window_has_pre65 and aca_amount > 5_000:
        menu.append(("fixed_amount", None, round(aca_amount, -3), "aca"))
        menu.append(("fixed_amount", None, round(aca_amount, -3), "aca"))  # 2× weight

    strat_type, target_bracket, fixed_amount, cliff_label = rng.choice(menu)

    rc: dict = {
        "enabled": True,
        "strategy": strat_type,
        "start_age": int(start_age),
        "end_age": int(end_age),
        "source_account_ids": source_ids,
        "destination_account_id": dest_id,
    }
    if strat_type == "fill_to_bracket":
        rc["target_bracket"] = target_bracket
    else:
        rc["fixed_amount"] = fixed_amount

    return rc, cliff_label


# ---------------------------------------------------------------------------
# Top-level sampler
# ---------------------------------------------------------------------------

def _sample_strategy_v2(
    profile: dict,
    accounts: list,
    assumptions: dict,
    rng: random.Random,
) -> tuple[str, dict, dict, Optional[str]]:
    """
    Sample a complete v2 strategy.

    Returns:
        withdrawal_strategy : str
        roth_conversion     : dict
        profile_overrides   : dict
        cliff_label         : "irmaa" | "aca" | None
    """
    withdrawal_strategy = rng.choice(WITHDRAWAL_STRATEGIES)

    ss_start = rng.choice(SS_AGE_OPTIONS)
    profile_overrides: dict = {"social_security_start_age": ss_start}

    spouse_ss_start = None
    if profile.get("filing_status") == "married_filing_jointly":
        spouse_ss_start = rng.choice(SS_AGE_OPTIONS)
        profile_overrides["spouse_ss_start_age"] = spouse_ss_start

    rc, cliff_label = _sample_roth_conversion(
        profile, accounts, assumptions, rng, ss_start, spouse_ss_start
    )

    return withdrawal_strategy, rc, profile_overrides, cliff_label


# ---------------------------------------------------------------------------
# Strategy description (v2 extends v1 with SS and cliff-aware rows)
# ---------------------------------------------------------------------------

def describe_strategy_v2(
    withdrawal_strategy: str,
    roth_conversion: dict,
    accounts: list,
    profile_overrides: dict,
    base_profile: dict,
    cliff_label: Optional[str] = None,
    irmaa_headroom: float = 0.0,
    aca_headroom: float = 0.0,
) -> dict:
    """Human-readable description of a v2 strategy, extending v1's output."""
    desc = _describe_strategy(withdrawal_strategy, roth_conversion, accounts)

    # SS start ages
    orig_ss = base_profile.get("social_security_start_age", 67)
    new_ss  = profile_overrides.get("social_security_start_age", orig_ss)
    ss_label = f"Age {new_ss}"
    if new_ss != orig_ss:
        delta_pct = (new_ss - 62) * 8
        ss_label += f"  (≈ +{delta_pct}% vs. claiming at 62)"
    desc["SS Start Age (primary)"] = ss_label

    if base_profile.get("filing_status") == "married_filing_jointly":
        orig_sp = base_profile.get("spouse_ss_start_age", 67)
        new_sp  = profile_overrides.get("spouse_ss_start_age", orig_sp)
        sp_label = f"Age {new_sp}"
        if new_sp != orig_sp:
            delta_pct = (new_sp - 62) * 8
            sp_label += f"  (≈ +{delta_pct}% vs. claiming at 62)"
        desc["SS Start Age (spouse)"] = sp_label

    # Cliff awareness
    if cliff_label == "irmaa" and irmaa_headroom > 0:
        desc["IRMAA Management"] = (
            f"Roth conversions capped at ~${irmaa_headroom:,.0f}/yr — "
            f"keeps MAGI below the ${IRMAA_CEILING_MFJ if base_profile.get('filing_status') == 'married_filing_jointly' else IRMAA_CEILING_SINGLE:,} "
            f"IRMAA Tier-0 ceiling, avoiding $1,148–$6,936/person/yr in Medicare surcharges."
        )
    elif cliff_label == "aca" and aca_headroom > 0:
        cliff_val = ACA_CLIFF_MFJ if base_profile.get("filing_status") == "married_filing_jointly" else ACA_CLIFF_SINGLE
        desc["ACA Subsidy Management"] = (
            f"Roth conversions capped at ~${aca_headroom:,.0f}/yr — "
            f"keeps MAGI below the ${cliff_val:,} ACA 400%-FPL cliff, "
            f"preserving marketplace premium subsidies ($10K–$20K/yr) until Medicare at 65."
        )
    else:
        desc["Cliff Management"] = "Standard (not constrained by IRMAA or ACA cliff)"

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

    Drop-in replacement for optimizer.run_optimizer(). Returns the same dict
    structure with additional per-result keys:
        profile_overrides   : dict   — SS age changes applied for this trial
        ss_start_age        : int | None
        spouse_ss_start_age : int | None
        cliff_label         : "irmaa" | "aca" | None
        irmaa_headroom      : float  — estimated conversion room below IRMAA ceiling
        aca_headroom        : float  — estimated conversion room below ACA cliff
    """
    rng = random.Random(seed)
    spending_overrides = spending_overrides or {}

    # Pre-compute headroom estimates (fixed for all trials; SS start varies per trial
    # but the representative-age estimate doesn't change dramatically)
    _irmaa_h = _irmaa_headroom(
        profile, accounts_at_retirement, assumptions,
        profile.get("social_security_start_age", 67),
        profile.get("spouse_ss_start_age"),
    )
    _aca_h = _aca_headroom(
        profile, accounts_at_retirement, assumptions,
        profile.get("social_security_start_age", 67),
        profile.get("spouse_ss_start_age"),
    )

    # --- Baseline ---
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
        "cliff_label": None,
        "irmaa_headroom": _irmaa_h,
        "aca_headroom": _aca_h,
    }

    # --- Random search ---
    results = []
    all_scores: list[float] = []
    n_evaluated = 0

    for _ in range(n_iterations):
        w_strat, rc, prof_overrides, cliff_label = _sample_strategy_v2(
            profile, accounts_at_retirement, assumptions, rng
        )
        trial_profile     = {**profile, **prof_overrides}
        trial_assumptions = {**assumptions, "withdrawal_strategy": w_strat}

        try:
            ret_df, sim_summary = simulate_retirement(
                accounts_at_retirement, trial_profile, trial_assumptions,
                rc, spending_overrides,
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
                "cliff_label": cliff_label,
                "irmaa_headroom": _irmaa_h,
                "aca_headroom": _aca_h,
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
