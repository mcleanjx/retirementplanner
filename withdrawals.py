import copy
import pandas as pd
from constants import RMD_TABLE, RMD_START_AGE, STANDARD_DEDUCTION, BRACKET_CEILINGS, IRMAA_TIERS
from taxes import (
    calculate_year_taxes,
    calculate_ss_taxable_amount,
    bracket_ceiling_for_rate,
)

TRADITIONAL_TYPES = {"traditional_401k", "traditional_ira"}
ROTH_TYPES = {"roth_401k", "roth_ira"}
TAXABLE_TYPES = {"taxable", "reit"}
BANK_TYPES = {"bank"}


def _rmd_divisor(age: int) -> float:
    if age < RMD_START_AGE:
        return 0.0
    return RMD_TABLE.get(age, RMD_TABLE.get(min(age, max(RMD_TABLE.keys())), 6.4))


def _gain_ratio(account: dict) -> float:
    bal = account["balance"]
    basis = account.get("basis", bal)
    if bal <= 0:
        return 0.0
    return max(0.0, min(1.0, (bal - basis) / bal))


def _withdraw_from(account: dict, amount: float) -> tuple[float, float, float]:
    """
    Withdraw `amount` from account. Returns (withdrawn, ordinary_income, ltcg_income).
    Adjusts account balance and basis in place.
    """
    amount = min(amount, account["balance"])
    if amount <= 0:
        return 0.0, 0.0, 0.0
    atype = account["type"]
    # Gain ratio MUST be computed before reducing balance — _gain_ratio divides
    # by account["balance"], so post-withdrawal it would give a wrong (too low) ratio.
    pre_balance = account["balance"]
    gr = _gain_ratio(account) if atype in TAXABLE_TYPES | {"rental_property"} else 0.0
    account["balance"] -= amount
    if atype in TRADITIONAL_TYPES:
        return amount, amount, 0.0
    elif atype in ROTH_TYPES:
        return amount, 0.0, 0.0
    elif atype in BANK_TYPES:
        return amount, 0.0, 0.0
    elif atype == "hsa":
        return amount, 0.0, 0.0
    elif atype in TAXABLE_TYPES:
        ltcg = amount * gr
        basis_return = amount * (1 - gr)
        account["basis"] = max(0.0, account.get("basis", pre_balance) - basis_return)
        return amount, 0.0, ltcg
    elif atype == "rental_property":
        account["basis"] = max(0.0, account.get("basis", pre_balance) - amount * (1 - gr))
        return amount, 0.0, amount * gr
    return amount, 0.0, 0.0


def simulate_retirement(
    accounts: list[dict],
    profile: dict,
    assumptions: dict,
    roth_conversion: dict | None = None,
    spending_overrides: dict | None = None,
) -> tuple[pd.DataFrame, dict]:
    """
    Simulate retirement year-by-year.

    Returns:
        df: one row per retirement year with income, taxes, balances
        summary: dict of lifetime aggregates
    """
    accts = copy.deepcopy(accounts)
    retirement_age = profile["retirement_age"]
    life_expectancy = profile["life_expectancy"]
    filing_status = profile["filing_status"]
    state = profile.get("state", "california")
    state_rate = profile.get("state_tax_rate", 0.0)
    inflation = assumptions.get("inflation_rate", 0.03)
    # Inflate SS from today's dollars to retirement-year nominal dollars.
    # SSA's "my Social Security" shows benefits in today's purchasing power;
    # the simulation runs in nominal dollars so we must convert before the loop.
    _years_to_ret = max(0, profile.get("retirement_age", 65) - profile.get("current_age", 0))
    _ss_inflate = (1 + inflation) ** _years_to_ret
    ss_benefit = profile.get("social_security_benefit", 0.0) * _ss_inflate
    ss_start = profile.get("social_security_start_age", 67)
    spouse_ss = profile.get("spouse_ss_benefit", 0.0) * _ss_inflate
    spouse_ss_start = profile.get("spouse_ss_start_age", 67)
    spouse_age_offset = (profile.get("spouse_age", profile.get("current_age", 0))
                         - profile.get("current_age", 0))
    survivor_reduction = profile.get("survivor_spending_reduction", 0.25)
    bracket_inflation = assumptions.get("bracket_inflation_rate", 0.025)
    swr = assumptions.get("safe_withdrawal_rate", 0.04)
    ret_return = assumptions.get("retirement_return_rate", 0.05)
    withdrawal_strategy = assumptions.get("withdrawal_strategy", "tax_efficient")
    current_age = profile["current_age"]

    # Initial spending target (nominal at retirement)
    total_portfolio = sum(a["balance"] for a in accts)
    spending_mode = assumptions.get("spending_mode", "swr")
    if spending_mode == "fixed":
        years_to_retirement = profile["retirement_age"] - profile["current_age"]
        base_spending = assumptions.get("annual_spending_target", total_portfolio * swr) * (1 + inflation) ** years_to_retirement
    else:
        base_spending = total_portfolio * swr
    spending_target = base_spending
    spending_overrides = spending_overrides or {}
    fixed_net_mode = (spending_mode == "fixed")

    # Healthcare costs (in retirement-year nominal dollars)
    pre_medicare_hc = profile.get("pre_medicare_healthcare", 0.0)
    post_medicare_hc = profile.get("post_medicare_healthcare", 0.0)

    # Roth conversion vintages for 5-year rule
    conversion_vintages: dict[int, float] = {}

    # Tracks previous year effective rate for gross-up in fixed_net mode.
    # We track taxes / total_cash_received (not taxes / ordinary_income) so that
    # tax-free Roth withdrawals are included in the denominator — this prevents
    # the gross-up from overshooting when Roth accounts cover part of spending.
    # LTCG rate is tracked separately because qualified dividends are often taxed
    # at 0% for retirees — lumping them with ordinary income grossly overstates
    # the tax provision on passive income.
    prev_eff_rate = 0.15 if fixed_net_mode else 0.22
    prev_ltcg_rate = 0.0  # LTCG on qualified dividends is 0% for most retirees at moderate income

    rows = []
    warnings = []

    survivor_triggered = False
    current_fs = filing_status

    lifetime_taxes = 0.0
    lifetime_healthcare = 0.0
    lifetime_passive_income = 0.0
    portfolio_depleted_age = None

    for age in range(retirement_age, life_expectancy + 1):
        spouse_age = age + spouse_age_offset if filing_status == "married_filing_jointly" else None
        bracket_factor = (1 + bracket_inflation) ** (age - current_age)
        start_portfolio = sum(a["balance"] for a in accts)

        # --- Step 0: Survivor transition ---
        if (not survivor_triggered
                and filing_status == "married_filing_jointly"
                and spouse_age is not None
                and spouse_age >= profile.get("life_expectancy", 90)):
            survivor_triggered = True
            current_fs = "single"
            ss_benefit = max(ss_benefit, spouse_ss)
            spouse_ss = 0.0
            spending_target *= (1 - survivor_reduction)
            warnings.append({
                "age": age,
                "type": "survivor_transition",
                "message": f"Survivor transition at age {age}: filing status → Single, SS → ${ss_benefit:,.0f}/yr, spending reduced {survivor_reduction:.0%}.",
            })

        # Healthcare costs this year (inflation-adjusted from retirement)
        years_in = age - retirement_age
        inflation_factor = (1 + inflation) ** years_in
        if age < 65:
            hc_cost = pre_medicare_hc * inflation_factor
        else:
            hc_cost = post_medicare_hc * inflation_factor
        lifetime_healthcare += hc_cost

        base_this_year = spending_overrides.get(age, spending_target)
        net_target_this_year = base_this_year if fixed_net_mode else None
        # Gross spending need: in fixed_net mode, gross up to cover taxes;
        # the discretionary gap is refined after passive income is known (Step 5).
        if fixed_net_mode:
            # Conservative first estimate; refined in Step 5 once passive income is known
            total_spending_need = base_this_year / max(0.05, 1 - prev_eff_rate) + hc_cost
        else:
            total_spending_need = base_this_year + hc_cost

        # --- Step 1: Mandatory / passive income ---
        ordinary_income = 0.0
        ltcg_income = 0.0
        # RMDs
        rmd_total = 0.0
        rmd_detail: dict[str, float] = {}
        for a in accts:
            if a["type"] in TRADITIONAL_TYPES and age >= RMD_START_AGE:
                divisor = _rmd_divisor(age)
                rmd = a["balance"] / divisor if divisor > 0 else 0.0
                actual, oi, lg = _withdraw_from(a, rmd)
                ordinary_income += oi
                rmd_total += actual
                rmd_detail[a["name"]] = rmd_detail.get(a["name"], 0.0) + actual

        # Social Security
        total_ss = 0.0
        if age >= ss_start:
            total_ss += ss_benefit
        if spouse_age is not None and spouse_age >= spouse_ss_start:
            total_ss += spouse_ss

        # Rental income
        rental_income = 0.0
        for a in accts:
            if a["type"] == "rental_property":
                ri = a.get("net_annual_rental_income", 0.0)
                rental_income += ri
                ordinary_income += ri

        # Recurring investment income (dividends/interest) — does not reduce balance
        inv_ordinary = 0.0
        inv_ltcg = 0.0
        for a in accts:
            if a["type"] in TAXABLE_TYPES:
                inv_ordinary += a["balance"] * a.get("ordinary_income_yield", 0.0)
                inv_ltcg += a["balance"] * a.get("qualified_dividend_yield", 0.0)
        ordinary_income += inv_ordinary
        ltcg_income += inv_ltcg

        passive_income_total = total_ss + rental_income + inv_ordinary + inv_ltcg
        lifetime_passive_income += passive_income_total

        # --- Step 2: SS taxability ---
        provisional = ordinary_income + 0.5 * total_ss
        ss_taxable = calculate_ss_taxable_amount(provisional, total_ss, current_fs)
        ordinary_income += ss_taxable

        # --- Step 3: Roth conversions ---
        roth_conversion_amount = 0.0
        conv_from_detail: dict[str, float] = {}
        conv_to_detail: dict[str, float] = {}
        if roth_conversion and roth_conversion.get("enabled"):
            conv_start = roth_conversion.get("start_age", retirement_age)
            conv_end = roth_conversion.get("end_age", min(ss_start - 1, RMD_START_AGE - 1))
            if conv_start <= age <= conv_end:
                std_ded = STANDARD_DEDUCTION[current_fs] * bracket_factor
                strategy = roth_conversion.get("strategy", "fill_to_bracket")
                if strategy == "fill_to_bracket":
                    target_rate = roth_conversion.get("target_bracket", 0.12)
                    ceiling = bracket_ceiling_for_rate(target_rate, current_fs, bracket_factor) + std_ded
                    headroom = max(0.0, ceiling - ordinary_income)
                elif strategy == "fixed_amount":
                    headroom = roth_conversion.get("fixed_amount", 0.0)
                else:
                    headroom = 0.0

                if headroom > 0:
                    # Support both new multi-source format and old single-source format
                    src_ids = set(roth_conversion.get("source_account_ids") or [])
                    if not src_ids and "source_account_id" in roth_conversion:
                        old = roth_conversion["source_account_id"]
                        if old:
                            src_ids = {old}
                    dst_id = roth_conversion.get("destination_account_id")
                    dst = next((a for a in accts if a["id"] == dst_id), None)
                    src_accts = [
                        a for a in accts
                        if a["id"] in src_ids
                        and a["type"] in TRADITIONAL_TYPES
                        and a["balance"] > 0
                    ]
                    if src_accts and dst:
                        total_src = sum(a["balance"] for a in src_accts)
                        convert = min(headroom, total_src)
                        # Draw proportionally from each source account
                        for a in src_accts:
                            portion = (a["balance"] / total_src) * convert
                            a["balance"] -= portion
                            conv_from_detail[a["name"]] = conv_from_detail.get(a["name"], 0.0) + portion
                        dst["balance"] += convert
                        conv_to_detail[dst["name"]] = conv_to_detail.get(dst["name"], 0.0) + convert
                        ordinary_income += convert
                        roth_conversion_amount = convert
                        conversion_vintages[age] = conversion_vintages.get(age, 0) + convert

        # Conversion taxes must be paid in cash from the portfolio — not just silently reduce
        # after_tax_spending. Estimate using target bracket rate (or prev_eff_rate for fixed_amount)
        # and add to total_spending_need so the surplus-reinvestment check stays accurate.
        conv_tax_estimate = 0.0
        if roth_conversion_amount > 0:
            rc = roth_conversion or {}
            conv_rate = rc.get("target_bracket", 0.22) if rc.get("strategy", "fill_to_bracket") == "fill_to_bracket" else prev_eff_rate
            conv_tax_estimate = roth_conversion_amount * conv_rate
            total_spending_need += conv_tax_estimate

        # --- Step 4: Tax-free capital gains harvesting ---
        # Headroom = how much more LTCG can fit in the 0% federal bracket above what
        # withdrawals will already consume.  We estimate withdrawal LTCG first so we
        # don't harvest gains that would have been at 0% via withdrawals anyway — doing
        # so just shifts those gains into the 15% bucket and adds California state tax
        # on the harvest with no offsetting federal benefit.
        from constants import LTCG_BRACKETS
        std_ded_now = STANDARD_DEDUCTION[current_fs] * bracket_factor
        ltcg_zero_limit = LTCG_BRACKETS[current_fs][0][0] * bracket_factor

        # Estimate the LTCG the upcoming withdrawals will generate so we can reserve
        # that slice of the 0% bucket for them.
        harvest_candidates = [
            a for a in accts
            if a["type"] in TAXABLE_TYPES
            and a["balance"] > 0
            and a.get("withdraw_priority", "normal") != "last"
            and _gain_ratio(a) > 0
        ]
        _taxable_bal = sum(a["balance"] for a in harvest_candidates)
        _taxable_gain = sum(a["balance"] * _gain_ratio(a) for a in harvest_candidates)
        _weighted_gr = _taxable_gain / _taxable_bal if _taxable_bal > 0 else 0.0
        if fixed_net_mode:
            _passive_net_est = inv_ltcg * (1 - prev_ltcg_rate)
            _net_needed_est = max(0.0, base_this_year + hc_cost - _passive_net_est)
            _withdrawal_est = max(0.0, _net_needed_est / max(0.05, 1 - prev_eff_rate) - rmd_total)
        else:
            _withdrawal_est = max(0.0, total_spending_need - passive_income_total - rmd_total)
        # Bank/cash covers withdrawals first with zero LTCG — only the portion that
        # spills into taxable accounts actually generates capital gains.
        _bank_available = sum(a["balance"] for a in accts if a["type"] in BANK_TYPES)
        _from_taxable_est = max(0.0, _withdrawal_est - _bank_available)
        estimated_withdrawal_ltcg = _from_taxable_est * _weighted_gr

        # True headroom = 0%-bracket space above dividends AND estimated withdrawal LTCG.
        ltcg_headroom = max(0.0,
            ltcg_zero_limit
            - (ordinary_income - std_ded_now)
            - ltcg_income                    # dividends already realized
            - estimated_withdrawal_ltcg      # reserve space for withdrawal gains
        )

        harvest_total = 0.0
        harvest_ltcg = 0.0
        total_harvestable = sum(a["balance"] * _gain_ratio(a) for a in harvest_candidates)
        for a in harvest_candidates:
            if ltcg_headroom <= 0:
                break
            harvestable = a["balance"] * _gain_ratio(a)
            share = ltcg_headroom * (harvestable / total_harvestable) if total_harvestable > 0 else 0.0
            harvest = min(harvestable, share)
            if harvest > 0:
                # Sell and rebuy: net basis increase = harvest amount; no cash generated.
                a["basis"] = a.get("basis", 0.0) + harvest
                harvest_total += harvest
        # Harvested gains are realized LTCG and must appear in MAGI
        # so IRMAA and NIIT thresholds are correctly triggered.
        harvest_ltcg = harvest_total
        ltcg_income += harvest_ltcg

        # --- Step 5: Discretionary withdrawals ---
        if fixed_net_mode:
            # Refine gross target now that passive income is known.
            # Use separate rates for LTCG income (qualified dividends, often 0%) and
            # ordinary passive income (SS, rental, interest) to avoid over-grossing
            # in portfolios where most passive income is LTCG.
            passive_ordinary = total_ss + rental_income + inv_ordinary
            passive_ordinary_net = passive_ordinary * (1 - prev_eff_rate)
            passive_ltcg_net = inv_ltcg * (1 - prev_ltcg_rate)
            passive_net_approx = passive_ordinary_net + passive_ltcg_net
            net_still_needed = max(0.0, base_this_year + hc_cost - passive_net_approx)
            remaining_need = net_still_needed / max(0.05, 1 - prev_eff_rate) - rmd_total
            # conv_tax_estimate not in the gross-up above; fund it directly.
            remaining_need = max(0.0, remaining_need) + conv_tax_estimate
        else:
            # total_spending_need already includes conv_tax_estimate (added after Step 3).
            remaining_need = max(0.0, total_spending_need - passive_income_total - rmd_total)
        withdrawal_detail = {}
        total_discretionary_withdrawn = 0.0
        bank_withdrawn = 0.0
        taxable_withdrawn = 0.0
        traditional_withdrawn = 0.0
        roth_withdrawn = 0.0
        withdrawal_ltcg = 0.0

        # 5_bank. Bank/cash accounts first (no tax cost, low return — drain first)
        for a in sorted([a for a in accts if a["type"] in BANK_TYPES], key=lambda x: -x["balance"]):
            if remaining_need <= 0:
                break
            w, oi, lg = _withdraw_from(a, remaining_need)
            remaining_need -= w
            total_discretionary_withdrawn += w
            bank_withdrawn += w
            withdrawal_detail[a["name"]] = withdrawal_detail.get(a["name"], 0) + w

        # 5a. Taxable / REIT — proportional across "normal" priority accounts.
        # Accounts flagged withdraw_priority="last" are held until everything else is exhausted.
        def _withdraw_taxable_proportional(candidates, need):
            nonlocal ordinary_income, ltcg_income, withdrawal_ltcg
            nonlocal total_discretionary_withdrawn, taxable_withdrawn
            active = [a for a in candidates if a["balance"] > 0]
            if not active or need <= 0:
                return need
            total_bal = sum(a["balance"] for a in active)
            to_withdraw = min(need, total_bal)
            for a in active:
                share = to_withdraw * (a["balance"] / total_bal)
                w, oi, lg = _withdraw_from(a, share)
                ordinary_income += oi
                ltcg_income += lg
                withdrawal_ltcg += lg
                total_discretionary_withdrawn += w
                taxable_withdrawn += w
                withdrawal_detail[a["name"]] = withdrawal_detail.get(a["name"], 0) + w
            return max(0.0, need - to_withdraw)

        taxable_normal = [a for a in accts if a["type"] in TAXABLE_TYPES
                          and a.get("withdraw_priority", "normal") != "last"]
        taxable_last   = [a for a in accts if a["type"] in TAXABLE_TYPES
                          and a.get("withdraw_priority", "normal") == "last"]
        remaining_need = _withdraw_taxable_proportional(taxable_normal, remaining_need)

        if withdrawal_strategy == "roth_preservation":
            # 5b. Drain traditional accounts fully before touching Roth.
            # Accepts higher brackets now to let Roth grow tax-free longer.
            for a in sorted([a for a in accts if a["type"] in TRADITIONAL_TYPES], key=lambda x: -x["balance"]):
                if remaining_need <= 0:
                    break
                w, oi, lg = _withdraw_from(a, remaining_need)
                ordinary_income += oi
                remaining_need -= w
                total_discretionary_withdrawn += w
                traditional_withdrawn += w
                withdrawal_detail[a["name"]] = withdrawal_detail.get(a["name"], 0) + w

            # 5c. Roth — only once traditional is exhausted
            for a in sorted([a for a in accts if a["type"] in ROTH_TYPES], key=lambda x: -x["balance"]):
                if remaining_need <= 0:
                    break
                w, oi, lg = _withdraw_from(a, remaining_need)
                remaining_need -= w
                total_discretionary_withdrawn += w
                roth_withdrawn += w
                withdrawal_detail[a["name"]] = withdrawal_detail.get(a["name"], 0) + w

        else:
            # tax_efficient (default): fill traditional to top of 22% bracket, then Roth,
            # then overflow back to traditional if still short.
            std_ded = STANDARD_DEDUCTION[current_fs] * bracket_factor
            traditional_ceiling = BRACKET_CEILINGS[current_fs].get(0.22, 1e9) * bracket_factor + std_ded

            # 5b. Traditional up to 22% ceiling
            for a in sorted([a for a in accts if a["type"] in TRADITIONAL_TYPES], key=lambda x: -x["balance"]):
                if remaining_need <= 0:
                    break
                trad_headroom = max(0.0, traditional_ceiling - ordinary_income)
                w_amount = min(remaining_need, trad_headroom)
                w, oi, lg = _withdraw_from(a, w_amount)
                ordinary_income += oi
                ltcg_income += lg
                remaining_need -= w
                total_discretionary_withdrawn += w
                traditional_withdrawn += w
                withdrawal_detail[a["name"]] = withdrawal_detail.get(a["name"], 0) + w

            # 5c. Roth
            for a in sorted([a for a in accts if a["type"] in ROTH_TYPES], key=lambda x: -x["balance"]):
                if remaining_need <= 0:
                    break
                w, oi, lg = _withdraw_from(a, remaining_need)
                remaining_need -= w
                total_discretionary_withdrawn += w
                roth_withdrawn += w
                withdrawal_detail[a["name"]] = withdrawal_detail.get(a["name"], 0) + w

            # 5d. Fall back to remaining Traditional if still short
            if remaining_need > 0:
                for a in sorted([a for a in accts if a["type"] in TRADITIONAL_TYPES], key=lambda x: -x["balance"]):
                    if remaining_need <= 0:
                        break
                    w, oi, lg = _withdraw_from(a, remaining_need)
                    ordinary_income += oi
                    remaining_need -= w
                    total_discretionary_withdrawn += w
                    traditional_withdrawn += w
                    withdrawal_detail[a["name"]] = withdrawal_detail.get(a["name"], 0) + w

        # 5e. Last-resort taxable accounts (e.g. bond funds held as buffer)
        remaining_need = _withdraw_taxable_proportional(taxable_last, remaining_need)

        # Total cash received from all sources this year.
        # Uses total_ss directly (not ss_taxable) to avoid double-counting.
        # Includes Roth withdrawals and taxable basis returns via total_discretionary_withdrawn.
        total_cash_received = (
            rmd_total + total_discretionary_withdrawn
            + total_ss + rental_income + inv_ordinary + inv_ltcg
        )

        # Reinvest any surplus cash that exceeds the spending target.
        # This covers RMD excess, passive income surplus (SS + dividends > target), etc.
        # Reinvestment happens before Step 7 so the surplus earns returns this year.
        surplus_reinvested = max(0.0, total_cash_received - total_spending_need)
        if surplus_reinvested > 0:
            for a in accts:
                if a["type"] in {"taxable", "bank"}:
                    a["balance"] += surplus_reinvested
                    if a["type"] == "taxable":
                        a["basis"] = a.get("basis", 0.0) + surplus_reinvested
                    break
            if surplus_reinvested > total_spending_need * 0.1:
                warnings.append({
                    "age": age,
                    "type": "rmd_excess",
                    "message": f"Age {age}: Income (${total_cash_received:,.0f}) exceeded spending target by ${surplus_reinvested:,.0f} — excess reinvested.",
                })

        # --- Step 6: IRMAA + NIIT ---
        # Use current_fs (not the original filing_status) so that after the survivor
        # transition we only count one Medicare enrollee, not two.
        num_medicare = 0
        if age >= 65:
            num_medicare += 1
        if current_fs == "married_filing_jointly" and spouse_age is not None and spouse_age >= 65:
            num_medicare += 1

        # NII = ordinary dividends + LTCG income (qualified divs + gains) + passive rental.
        # Excludes: RMDs, traditional withdrawals, SS — those are ordinary income but not NII.
        nii = inv_ordinary + ltcg_income + rental_income

        taxes = calculate_year_taxes(
            ordinary_income=ordinary_income,
            ltcg_income=ltcg_income,
            filing_status=current_fs,
            state=state,
            age=age,
            spouse_age=spouse_age,
            num_medicare_eligible=num_medicare,
            ss_income=total_ss,
            state_tax_rate=state_rate,
            net_investment_income=nii,
            ss_taxable_amount=ss_taxable,
            bracket_factor=bracket_factor,
        )
        lifetime_taxes += taxes["total"]

        if taxes["irmaa_tier_crossed"]:
            warnings.append({
                "age": age,
                "type": "irmaa",
                "message": f"Age {age}: IRMAA surcharge of ${taxes['federal_irmaa']:,.0f} applies (MAGI ${taxes['magi']:,.0f}).",
            })
        # Proactive IRMAA cliff alert — fires when MAGI is within $10,000 of the next tier.
        if age >= 65 and num_medicare > 0:
            _magi = taxes["magi"]
            for _i, (_mfj_u, _sing_u, _pb, _pd) in enumerate(IRMAA_TIERS[:-1]):
                _tier_upper = _mfj_u if current_fs == "married_filing_jointly" else _sing_u
                if _tier_upper is None:
                    continue
                _scaled = _tier_upper * bracket_factor
                if _magi < _scaled and _magi >= _scaled - 10000:
                    _nx = IRMAA_TIERS[_i + 1]
                    _add = (_nx[2] + _nx[3] - _pb - _pd) * 12 * num_medicare
                    if _add > 0:
                        warnings.append({
                            "age": age,
                            "type": "irmaa_approaching",
                            "message": (
                                f"Age {age}: MAGI ${_magi:,.0f} is ${_scaled - _magi:,.0f} below "
                                f"the next IRMAA tier (${_scaled:,.0f}). "
                                f"Staying below saves ${_add:,.0f}/yr in Medicare surcharges."
                            ),
                        })
                    break

        # --- Step 7: Apply returns, inflate, advance ---
        for a in accts:
            always_own = a["type"] in {"rental_property", "bank"}
            if always_own or not a.get("use_global_return_rate", True):
                a["balance"] *= (1 + a.get("return_rate", 0.05))
            else:
                a["balance"] *= (1 + ret_return)

        spending_target *= (1 + inflation)
        # SS COLA — benefits grow roughly with CPI each year, matching the inflation assumption.
        ss_benefit *= (1 + inflation)
        spouse_ss *= (1 + inflation)   # 0 after survivor transition; harmless
        total_balance = sum(a["balance"] for a in accts)

        if total_balance <= 0 and portfolio_depleted_age is None:
            portfolio_depleted_age = age
            warnings.append({
                "age": age,
                "type": "depletion",
                "message": f"Portfolio depleted at age {age}.",
            })

        # After-tax spending = what was actually consumed (cash received minus
        # surplus reinvested minus taxes). Excludes reinvested surplus so that
        # RMD excess and passive income windfalls don't inflate this figure.
        spendable_cash = total_cash_received - surplus_reinvested
        after_tax_spending = spendable_cash - taxes["total"]
        actual_after_tax_net = after_tax_spending - hc_cost

        # Update effective rate against spendable cash (not total) for next year's gross-up.
        prev_eff_rate = max(0.05, taxes["total"] / max(1.0, spendable_cash))
        # Update LTCG rate separately so dividend-heavy portfolios aren't over-grossed.
        if ltcg_income > 0:
            prev_ltcg_rate = min(0.25, taxes["federal_ltcg"] / max(1.0, ltcg_income))

        rows.append({
            "age": age,
            "spending_target": total_spending_need,
            "net_spending_target": net_target_this_year,
            "actual_after_tax_net": actual_after_tax_net,
            "spending_override_active": age in spending_overrides,
            "ss_income": total_ss,
            "rental_income": rental_income,
            "investment_income": inv_ordinary + inv_ltcg,
            "rmd_amount": rmd_total,
            "taxable_withdrawal": taxable_withdrawn,
            "traditional_withdrawal": traditional_withdrawn,
            "roth_withdrawal": roth_withdrawn,
            "bank_withdrawal": bank_withdrawn,
            "roth_conversion": roth_conversion_amount,
            "qual_dividends": inv_ltcg,
            "harvest_ltcg": harvest_ltcg,
            "withdrawal_ltcg": withdrawal_ltcg,
            "ordinary_income": ordinary_income,
            "ltcg_income": ltcg_income,
            "magi": taxes["magi"],
            "federal_ordinary_tax": taxes["federal_ordinary"],
            "federal_ltcg_tax": taxes["federal_ltcg"],
            "federal_niit": taxes["federal_niit"],
            "federal_irmaa": taxes["federal_irmaa"],
            "state_tax": taxes["state_tax"],
            "total_tax": taxes["total"],
            "effective_tax_rate": taxes["effective_rate"],
            "surplus_reinvested": surplus_reinvested,
            "healthcare_cost": hc_cost,
            "after_tax_spending": after_tax_spending,
            "start_portfolio": start_portfolio,
            "total_portfolio": total_balance,
            **{f"bal_{a['name'].replace(' ','_')}": a["balance"] for a in accts},
            **{f"wd_{a['name'].replace(' ','_')}": rmd_detail.get(a["name"], 0.0) + withdrawal_detail.get(a["name"], 0.0) for a in accts},
            **{f"conv_from_{a['name'].replace(' ','_')}": conv_from_detail.get(a["name"], 0.0) for a in accts},
            **{f"conv_to_{a['name'].replace(' ','_')}": conv_to_detail.get(a["name"], 0.0) for a in accts},
        })

    df = pd.DataFrame(rows)

    summary = {
        "lifetime_taxes": lifetime_taxes,
        "lifetime_healthcare": lifetime_healthcare,
        "lifetime_passive_income": lifetime_passive_income,
        "portfolio_depleted_age": portfolio_depleted_age,
        "warnings": warnings,
        "conversion_vintages": conversion_vintages,
        "final_accounts": accts,
    }

    return df, summary
