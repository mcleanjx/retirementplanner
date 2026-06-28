"""
Strategy optimizer: searches over retirement strategy configurations to maximize
after-tax lifetime wealth. Uses random search (Monte Carlo optimization) over:
  - Withdrawal strategy (tax_efficient vs roth_preservation)
  - Roth conversion parameters (enabled, bracket target, timing, amounts)

Does NOT modify any scenario files or session state.
"""

import copy
import random
from typing import Optional

import pandas as pd

from withdrawals import simulate_retirement
from constants import RMD_START_AGE

TRADITIONAL_TYPES = {"traditional_401k", "traditional_ira"}
ROTH_TYPES = {"roth_401k", "roth_ira"}
TAXABLE_TYPES = {"taxable", "reit"}
BRACKET_OPTIONS = [0.10, 0.12, 0.22, 0.24]
WITHDRAWAL_STRATEGIES = ["tax_efficient", "roth_preservation"]
REBALANCE_OPTIONS = [0, 0, 0, 10_000, 25_000, 50_000, 75_000, 100_000, 150_000, 200_000]

# 401(k) accounts require separation from service before the funds can be moved at all.
# Traditional IRAs have no such restriction and can be converted at any age.
SEPARATION_REQUIRED_TYPES = {"traditional_401k"}


def _owner_min_conv_age(account: dict, profile: dict) -> int:
    """
    Return the earliest primary-person simulation age at which the given account may
    legally be used as a Roth conversion source.

    Key rules:
    - Traditional IRA → no age restriction on Roth conversions. Owner pays ordinary income
      tax on converted amounts; no 10% early-withdrawal penalty. Min = owner's retirement
      age (the earliest this plan models liquidity).
    - Traditional 401(k) → requires separation from service before the money can be moved.
      Once separated (i.e. at/after the owner's retirement age), the funds can be rolled
      directly to a Roth IRA under the rollover/conversion exemption (IRC §402(c)) — no
      10% penalty regardless of age. The Rule of 55 governs penalty-free *cash distributions*
      from a 401(k); it does NOT apply to rollover conversions, which are exempt on their own.
      Min = owner's retirement age (first year they are separated from service).

    The result is expressed as the *primary person's* simulation age.
    """
    primary_current = profile.get("current_age", 65)
    primary_ret = profile.get("retirement_age", 65)
    spouse_current = profile.get("spouse_age", primary_current)
    spouse_ret = profile.get("spouse_retirement_age", primary_ret)

    owner = account.get("owner", "self")

    if owner == "spouse":
        # Translate spouse's retirement age to the primary person's simulation age.
        # When primary is at age X, spouse is at X + (spouse_current − primary_current).
        # Spouse reaches spouse_ret when primary age = spouse_ret − spouse_current + primary_current.
        owner_ret_as_primary_age = spouse_ret - spouse_current + primary_current
    else:
        owner_ret_as_primary_age = primary_ret

    # Both IRA and 401(k): min = owner's retirement age (separation from service).
    # 401(k) needs separation to access the funds at all; once separated the
    # rollover/conversion exemption removes any 10% penalty concern.
    return int(owner_ret_as_primary_age)


def _sample_strategy(profile: dict, accounts: list, rng: random.Random) -> tuple[str, dict, float]:
    """Randomly sample a complete retirement strategy configuration."""
    life_expectancy = profile.get("life_expectancy", 90)
    ss_start = profile.get("social_security_start_age", 67)

    withdrawal_strategy = rng.choice(WITHDRAWAL_STRATEGIES)

    trad_accounts = [a for a in accounts if a["type"] in TRADITIONAL_TYPES]
    roth_accounts = [a for a in accounts if a["type"] in ROTH_TYPES]

    # Bias toward trying Roth conversion when accounts exist (70% of trials)
    try_roth = bool(trad_accounts) and bool(roth_accounts) and rng.random() < 0.70

    rc: dict = {"enabled": False}
    if try_roth:
        # A meaningful fraction of conversion trials use the "aggressive full-drain" shape:
        # convert from ALL traditional accounts, starting at the earliest legal age and
        # running the full gap-year window up to the RMD/SS ceiling. For large traditional
        # balances this is the configuration that empties the pre-tax accounts before RMDs
        # and SS stack into the top brackets — but it's a low-probability combination under
        # fully-uniform sampling (all sources AND earliest start AND widest window), so the
        # search rarely lands it on its own. Seeding it directly keeps the default
        # iteration count enough to find it while the remaining trials still explore.
        aggressive = rng.random() < 0.40

        # Choose source accounts first so we can derive the correct min start age
        if aggressive:
            source_accounts = list(trad_accounts)
        else:
            n_sources = rng.randint(1, len(trad_accounts))
            source_accounts = rng.sample(trad_accounts, n_sources)
        source_ids = [a["id"] for a in source_accounts]

        # Minimum conversion start age = latest "ready" age across all source accounts
        # (separation-from-service / IRA access), floored at the simulation start so we
        # never convert in an already-elapsed year. No artificial age-60 floor: the
        # Roth 5-year clock does not require waiting to convert, and the 59½ early-
        # withdrawal penalty does not apply to conversions — so the $0-ordinary-income
        # gap years immediately after an early retirement are prime conversion years.
        min_conv_age = max(
            max(_owner_min_conv_age(a, profile) for a in source_accounts),
            profile.get("current_age", 60),
        )

        # Conversion window ceiling: stop before RMDs kick in or SS starts
        conv_max_end = max(
            min_conv_age + 1,
            min(RMD_START_AGE - 1, ss_start - 1, life_expectancy - 5),
        )

        if min_conv_age > conv_max_end:
            # No viable window — skip Roth conversion for this trial
            return withdrawal_strategy, {"enabled": False}

        if aggressive:
            # Earliest start, full window, fill to a bracket (never a small fixed amount).
            start_age = min_conv_age
            end_age = conv_max_end
            strategy = "fill_to_bracket"
            # Bias toward the higher brackets that actually drain a large balance.
            target_bracket = rng.choice([0.22, 0.24, 0.24])
        else:
            start_age = rng.randint(min_conv_age, min(min_conv_age + 5, conv_max_end))
            end_age = rng.randint(start_age, min(conv_max_end, start_age + 15))
            # Bias strongly toward fill_to_bracket
            strategy = rng.choice(["fill_to_bracket", "fill_to_bracket", "fill_to_bracket", "fixed_amount"])
            target_bracket = rng.choice(BRACKET_OPTIONS)

        fixed_amount = float(rng.choice([5_000, 10_000, 20_000, 30_000, 50_000, 75_000, 100_000]))
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

    taxable_accounts = [a for a in accounts if a["type"] in TAXABLE_TYPES]
    has_gains = any(a["balance"] > a.get("basis", a["balance"]) for a in taxable_accounts)
    annual_rebalance_gain = float(rng.choice(REBALANCE_OPTIONS)) if has_gains else 0.0

    return withdrawal_strategy, rc, annual_rebalance_gain


def _score(ret_df: pd.DataFrame, summary: dict, legacy_weight: float) -> float:
    """
    Score a simulation result. Higher is better.

    Objective: maximize lifetime after-tax spending net of healthcare,
    penalize taxes, reward final portfolio value (legacy), hard-penalize depletion.
    """
    if ret_df is None or ret_df.empty:
        return float("-inf")

    lifetime_spending = float(ret_df["actual_after_tax_net"].sum())
    lifetime_taxes = float(ret_df["total_tax"].sum())
    final_portfolio = float(
        ret_df["tax_adj_total_portfolio"].iloc[-1]
        if "tax_adj_total_portfolio" in ret_df.columns
        else ret_df["total_portfolio"].iloc[-1]
    )
    depleted = summary.get("portfolio_depleted_age") is not None
    depletion_penalty = 1_000_000.0 if depleted else 0.0

    return (
        lifetime_spending
        - lifetime_taxes * 0.30
        + final_portfolio * legacy_weight
        - depletion_penalty
    )


# ---------------------------------------------------------------------------
# Robustness to the return-rate guess
# ---------------------------------------------------------------------------
# The Roth conversion decision is acutely sensitive to the assumed return on the
# Roth bucket: converting moves money into a tax-free account, so a higher assumed
# Roth return mechanically makes conversion look better, with decades of compounding
# leverage on a large balance. Because the return rate is a *guess* (and, under an
# asset-location strategy, deliberately set higher because the Roth is spent last),
# a point-estimate optimizer overfits it and produces a fragile corner solution that
# flips between "convert aggressively" and "don't" when the assumed rate moves a
# tenth of a point.
#
# Robust mode evaluates each candidate strategy across a *band* of Roth-return
# assumptions and scores it on a downside-aware blend of the resulting outcomes,
# so the recommendation reflects the return uncertainty instead of a single guess.


def _effective_roth_return(accounts: list, assumptions: dict) -> float:
    """The assumed long-run return on the Roth bucket (the fragile asset-location guess).

    Uses the highest effective return across Roth accounts — that is the aggressive
    rate the user has assigned to the bucket that's spent last. Falls back to the
    global retirement return when no Roth account is present.
    """
    global_rate = assumptions.get("retirement_return_rate", 0.07)
    roth_rates = [
        (a.get("return_rate", global_rate) if not a.get("use_global_return_rate", True) else global_rate)
        for a in accounts
        if a["type"] in ROTH_TYPES
    ]
    return max(roth_rates) if roth_rates else global_rate


def default_return_band(
    accounts: list, assumptions: dict, width: float = 0.01, points: int = 3
) -> list[float]:
    """Symmetric band of Roth-return assumptions centered on the current guess.

    e.g. a 7% assumption with width=0.01, points=3 → [0.06, 0.07, 0.08]. Rates are
    floored at 0. The center point (returned at the middle index) is the user's
    actual assumption and is the one whose plan is surfaced for display.
    """
    center = _effective_roth_return(accounts, assumptions)
    if points < 2:
        return [center]
    half = (points - 1) / 2.0
    step = width / half
    return [max(0.0, center + (i - half) * step) for i in range(points)]


def _apply_roth_return(accounts: list, roth_return: float) -> list:
    """Return a fresh account list with every Roth account's return set to `roth_return`.

    Pre-tax/taxable/cash accounts are untouched, so this varies only the Roth premium
    (the asset-location guess). Shallow-copies each account dict; never mutates input.
    """
    out = []
    for a in accounts:
        b = dict(a)
        if b["type"] in ROTH_TYPES:
            b["return_rate"] = roth_return
            b["use_global_return_rate"] = False
        out.append(b)
    return out


def _robust_score(scores: list[float], robustness: float) -> float:
    """Blend a strategy's per-band-point scores into a single robust score.

    robustness (λ) interpolates between expected value and worst case:
        λ = 0 → mean(scores)          (risk-neutral; picks the highest-upside corner)
        λ = 1 → min(scores)           (max-min robust; picks the safest plan)
        0<λ<1 → (1-λ)·mean + λ·min     (neutral default 0.5 = average of the two)

    A single-element list reproduces the plain point score exactly.
    """
    if not scores:
        return float("-inf")
    worst = min(scores)
    if worst == float("-inf"):
        return float("-inf")
    mean = sum(scores) / len(scores)
    robustness = min(1.0, max(0.0, robustness))
    return (1.0 - robustness) * mean + robustness * worst


def _point_metrics(ret_df: pd.DataFrame, summary: dict) -> dict:
    """Interpretable dollar outcomes for one band point (for display, not ranking)."""
    if ret_df is None or ret_df.empty:
        return {"final_portfolio": 0.0, "lifetime_spend": 0.0, "lifetime_tax": 0.0, "depleted": True}
    col = "tax_adj_total_portfolio" if "tax_adj_total_portfolio" in ret_df.columns else "total_portfolio"
    return {
        "final_portfolio": float(ret_df[col].iloc[-1]),
        "lifetime_spend": float(ret_df["actual_after_tax_net"].sum()),
        "lifetime_tax": float(ret_df["total_tax"].sum()),
        "depleted": summary.get("portfolio_depleted_age") is not None,
    }


def _evaluate_across_band(
    account_variants: list,
    profile: dict,
    trial_assumptions: dict,
    rc: dict,
    spending_overrides: Optional[dict],
    legacy_weight: float,
    robustness: float,
    center_idx: int,
) -> tuple[float, list[float], list[dict], pd.DataFrame, dict]:
    """Simulate a strategy under each return-band variant.

    Returns (robust_score, per_point_scores, per_point_metrics, center_ret_df,
    center_summary). `per_point_metrics` holds interpretable dollar outcomes (legacy,
    lifetime spend/tax, depletion) aligned with the band, for the robustness display.
    The center variant's simulation is the representative plan surfaced to the user.
    """
    scores: list[float] = []
    band_metrics: list[dict] = []
    center_df: pd.DataFrame = pd.DataFrame()
    center_summary: dict = {}
    for i, accts in enumerate(account_variants):
        df, summ = simulate_retirement(accts, profile, trial_assumptions, rc, spending_overrides)
        scores.append(_score(df, summ, legacy_weight))
        band_metrics.append(_point_metrics(df, summ))
        if i == center_idx:
            center_df, center_summary = df, summ
    return _robust_score(scores, robustness), scores, band_metrics, center_df, center_summary


def _describe_strategy(withdrawal_strategy: str, rc: dict, accounts: list, annual_rebalance_gain: float = 0.0) -> dict:
    """Build a human-readable description of a strategy configuration."""
    ws_label = "Tax Efficient" if withdrawal_strategy == "tax_efficient" else "Roth Preservation"

    rebalance_label = f"${annual_rebalance_gain:,.0f}/yr (sell-and-rebuy taxable positions)" if annual_rebalance_gain > 0 else "Disabled"

    if not rc.get("enabled"):
        return {
            "Withdrawal Strategy": ws_label,
            "Roth Conversion": "Disabled",
            "Taxable Rebalancing": rebalance_label,
        }

    strat = rc.get("strategy", "fill_to_bracket")
    if strat == "fill_to_bracket":
        conv_detail = f"Fill to {rc.get('target_bracket', 0.12):.0%} bracket"
    else:
        conv_detail = f"Fixed ${rc.get('fixed_amount', 0):,.0f}/yr"

    # Look up account names and types for display
    acc_by_id = {a["id"]: a for a in accounts}
    source_accounts = [acc_by_id[aid] for aid in rc.get("source_account_ids", []) if aid in acc_by_id]
    source_names = ", ".join(a["name"] for a in source_accounts)
    dest_acc = acc_by_id.get(rc.get("destination_account_id", ""))
    dest_name = dest_acc["name"] if dest_acc else "Roth account"

    # Eligibility note for the user
    has_401k = any(a.get("type") in SEPARATION_REQUIRED_TYPES for a in source_accounts)
    has_ira = any(a.get("type") == "traditional_ira" for a in source_accounts)
    start_age = rc.get("start_age", "?")
    eligibility_notes = []
    if has_401k:
        eligibility_notes.append(
            "401(k): requires separation from service (retirement). Once separated, funds can be "
            "rolled directly to a Roth IRA (rollover/conversion exemption — no 10% penalty, "
            "ordinary income tax applies). The Rule of 55 applies only to cash distributions, "
            "not to rollover conversions."
        )
    if has_ira:
        eligibility_notes.append(
            "Traditional IRA: no age restriction on conversions. Ordinary income tax applies; "
            "no 10% early-withdrawal penalty on the converted amount."
        )

    return {
        "Withdrawal Strategy": ws_label,
        "Roth Conversion": "Enabled",
        "Conversion Method": conv_detail,
        "Convert From": source_names or "—",
        "Convert Into": dest_name,
        "Conversion Ages (primary person)": f"{start_age} – {rc.get('end_age', '?')}",
        "Eligibility Notes": " | ".join(eligibility_notes),
        "Taxable Rebalancing": rebalance_label,
    }


def build_actions_table(ret_df: pd.DataFrame, rc: dict, accounts: list) -> pd.DataFrame:
    """
    Per-year cash-flow table.

    Sign convention for account columns:
      negative = money leaving the account (withdrawal, RMD, Roth conversion source)
      positive = money entering the account (Roth conversion receipt)

    "Portfolio Draw" = sum of all account columns = net reduction to the portfolio
    for that year (Roth conversion internal transfers cancel to zero).

    Expense/income context columns are shown separately and are NOT included in
    Portfolio Draw to avoid double-counting (the account withdrawals ARE the source
    that funds taxes, healthcare, and living expenses).
    """
    if ret_df is None or ret_df.empty:
        return pd.DataFrame()

    def _safe(name: str) -> str:
        return name.replace(" ", "_")

    rows = []
    for _, row in ret_df.iterrows():
        rec: dict = {"Age": int(row["age"])}

        portfolio_draw = 0.0
        for a in accounts:
            sn = _safe(a["name"])
            wd        = float(row.get(f"wd_{sn}",        0.0))
            conv_from = float(row.get(f"conv_from_{sn}", 0.0))
            conv_to   = float(row.get(f"conv_to_{sn}",   0.0))
            net = -(wd + conv_from) + conv_to
            rec[a["name"]] = net
            portfolio_draw += net

        # Subtotal: net cash drawn from the portfolio this year
        rec["Portfolio Draw"] = portfolio_draw

        # Income that offsets the portfolio draw (positive = reduces how much accounts must cover)
        ss      = float(row.get("ss_income",        0.0))
        rental  = float(row.get("rental_income",     0.0))
        inv     = float(row.get("investment_income", 0.0))
        rec["SS & Passive Income"] = ss + rental + inv

        rec["Ordinary Income"]  = float(row.get("ordinary_income",   0.0))
        rec["Realized Gains"]   = (float(row.get("withdrawal_ltcg",  0.0))
                                   + float(row.get("harvest_ltcg",   0.0))
                                   + float(row.get("rebalance_ltcg", 0.0)))
        rec["Gain Harvest"]     = float(row.get("harvest_ltcg",      0.0))
        rec["Rebalance Gain"]   = float(row.get("rebalance_ltcg",    0.0))

        # Expense breakdown (informational — funded by account withdrawals above)
        rec["Taxes"]       = -float(row.get("total_tax",            0.0))
        rec["Healthcare"]  = -float(row.get("healthcare_cost",     0.0))
        rec["Total Spend"] =  float(row.get("actual_after_tax_net", 0.0))

        rec["Eff. Tax Rate"] = float(row.get("effective_tax_rate", 0.0))
        rows.append(rec)

    return pd.DataFrame(rows)


def build_balances_table(ret_df: pd.DataFrame, accounts: list) -> pd.DataFrame:
    """Build per-account balance table for the optimized scenario (mirrors Data Tables tab)."""
    if ret_df is None or ret_df.empty:
        return pd.DataFrame()

    bal_cols = ["age"] + [c for c in ret_df.columns if c.startswith("bal_")] + ["total_portfolio"]
    bal_cols = [c for c in bal_cols if c in ret_df.columns]
    bal_df = ret_df[bal_cols].copy()

    rename = {"age": "Age", "total_portfolio": "Total Portfolio"}
    for a in accounts:
        key = f"bal_{a['name'].replace(' ', '_')}"
        if key in bal_df.columns:
            rename[key] = a["name"]
    bal_df.rename(columns=rename, inplace=True)
    return bal_df


def run_optimizer(
    accounts_at_retirement: list,
    profile: dict,
    assumptions: dict,
    roth_conversion_baseline: Optional[dict],
    spending_overrides: Optional[dict],
    n_iterations: int = 500,
    legacy_weight: float = 0.20,
    seed: int = 42,
    return_band: Optional[list[float]] = None,
    robustness: float = 0.0,
) -> dict:
    """
    Run the strategy optimizer over `n_iterations` random trials.

    Robust mode (opt-in): pass `return_band` (a list of Roth-return assumptions,
    e.g. from `default_return_band`) to score every candidate across that band
    instead of a single guess. `robustness` (λ, 0–1) blends each candidate's
    band outcomes: 0 = expected value (upside-seeking corner), 1 = worst case
    (max-min robust), 0.5 = neutral. With `return_band=None` (default) behavior
    is unchanged — a single point-estimate run.

    Returns a dict with:
        baseline_result  – simulation of current (unchanged) settings
        best_result      – highest-scoring configuration found
        top_results      – top 10 configurations
        n_evaluated      – number of successful simulation runs
        all_scores       – list of all valid scores (for distribution)
        return_band      – the band used (None if not in robust mode)
        robustness       – the λ used
    """
    rng = random.Random(seed)

    robust_mode = bool(return_band) and len(return_band) > 1
    if robust_mode:
        account_variants = [_apply_roth_return(accounts_at_retirement, r) for r in return_band]
        center_idx = len(account_variants) // 2
    else:
        account_variants = [accounts_at_retirement]
        center_idx = 0

    # --- Baseline (current settings, unmodified) ---
    try:
        base_assumptions = {**assumptions}
        base_score, base_band_scores, base_band_metrics, base_df, base_summary = _evaluate_across_band(
            account_variants, profile, base_assumptions, roth_conversion_baseline or {"enabled": False},
            spending_overrides, legacy_weight, robustness, center_idx,
        )
    except Exception:
        base_df, base_summary, base_score = pd.DataFrame(), {}, float("-inf")
        base_band_scores, base_band_metrics = [], []

    baseline_result = {
        "score": base_score,
        "band_scores": base_band_scores,
        "band_metrics": base_band_metrics,
        "withdrawal_strategy": assumptions.get("withdrawal_strategy", "tax_efficient"),
        "roth_conversion": copy.deepcopy(roth_conversion_baseline) or {"enabled": False},
        "annual_rebalance_gain": assumptions.get("annual_rebalance_gain", 0.0),
        "ret_df": base_df,
        "summary": base_summary,
        "label": "Baseline (Current Settings)",
    }

    # --- Random search ---
    results = []
    all_scores: list[float] = []
    n_evaluated = 0

    for _ in range(n_iterations):
        w_strat, rc, annual_rebalance_gain = _sample_strategy(profile, accounts_at_retirement, rng)
        trial_assumptions = {**assumptions, "withdrawal_strategy": w_strat, "annual_rebalance_gain": annual_rebalance_gain}

        try:
            sc, band_scores, band_metrics, ret_df, sim_summary = _evaluate_across_band(
                account_variants, profile, trial_assumptions, rc,
                spending_overrides, legacy_weight, robustness, center_idx,
            )
            n_evaluated += 1
            all_scores.append(sc)
            results.append({
                "score": sc,
                "band_scores": band_scores,
                "band_metrics": band_metrics,
                "withdrawal_strategy": w_strat,
                "roth_conversion": rc,
                "annual_rebalance_gain": annual_rebalance_gain,
                "ret_df": ret_df,
                "summary": sim_summary,
                "label": "Optimized",
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
        "return_band": return_band if robust_mode else None,
        "robustness": robustness,
    }
