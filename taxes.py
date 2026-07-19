from constants import (
    STANDARD_DEDUCTION, ORDINARY_BRACKETS, LTCG_BRACKETS,
    NIIT_RATE, NIIT_THRESHOLD, IRMAA_TIERS,
    SS_TAXABILITY,
    CA_STANDARD_DEDUCTION, CA_ORDINARY_BRACKETS,
    MT_STANDARD_DEDUCTION, MT_ORDINARY_BRACKETS, MT_LTCG_BRACKETS,
    FPL_BASE, FPL_PER_ADDITIONAL, ACA_FPL_CLIFF_RATIO, ACA_APPLICABLE_PCT,
)


def calculate_ordinary_tax(taxable_income: float, filing_status: str, brackets: list | None = None) -> float:
    """Federal ordinary income tax on taxable income (after standard deduction)."""
    return _apply_brackets(taxable_income, brackets or ORDINARY_BRACKETS[filing_status])


def calculate_ltcg_tax(
    ltcg_income: float,
    ordinary_taxable_income: float,
    filing_status: str,
    brackets: list | None = None,
) -> float:
    """
    Federal LTCG tax. LTCG brackets stack on top of ordinary income —
    the rate is determined by where (ordinary + ltcg) falls in the LTCG schedule.
    """
    if ltcg_income <= 0:
        return 0.0
    brackets = brackets or LTCG_BRACKETS[filing_status]
    tax = 0.0
    # LTCG income sits on top of ordinary income in the bracket stack
    ltcg_start = ordinary_taxable_income
    ltcg_end = ordinary_taxable_income + ltcg_income
    prev = 0.0
    for upper, rate in brackets:
        top = upper if upper is not None else ltcg_end
        bracket_top = min(ltcg_end, top)
        bracket_bottom = max(ltcg_start, prev)
        if bracket_bottom < bracket_top:
            tax += (bracket_top - bracket_bottom) * rate
        prev = top
        if ltcg_end <= top:
            break
    return tax


def calculate_niit(magi: float, net_investment_income: float, filing_status: str, threshold: float | None = None) -> float:
    """3.8% Net Investment Income Tax on lesser of NII or excess MAGI over threshold."""
    threshold = threshold if threshold is not None else NIIT_THRESHOLD[filing_status]
    if magi <= threshold:
        return 0.0
    excess = magi - threshold
    return min(net_investment_income, excess) * NIIT_RATE


def calculate_irmaa(magi: float, filing_status: str, num_medicare_eligible: int, tiers: list | None = None) -> float:
    """
    Annual IRMAA surcharge. Returns total annual amount for all Medicare-eligible people.
    num_medicare_eligible: 1 or 2 (both spouses on Medicare).
    """
    if num_medicare_eligible == 0:
        return 0.0
    monthly_b = 0.0
    monthly_d = 0.0
    for mfj_upper, single_upper, part_b, part_d in (tiers or IRMAA_TIERS):
        upper = mfj_upper if filing_status == "married_filing_jointly" else single_upper
        if upper is None or magi <= upper:
            monthly_b = part_b
            monthly_d = part_d
            break
    return (monthly_b + monthly_d) * 12 * num_medicare_eligible


def aca_fpl(household_size: int, bracket_factor: float = 1.0) -> float:
    """Federal Poverty Level for a household of the given size, scaled by inflation."""
    n = max(1, int(household_size))
    return (FPL_BASE + FPL_PER_ADDITIONAL * (n - 1)) * bracket_factor


def _aca_applicable_pct(fpl_ratio: float) -> float:
    """Expected-contribution percentage of MAGI, interpolated on the FPL-ratio schedule."""
    anchors = ACA_APPLICABLE_PCT
    if fpl_ratio <= anchors[0][0]:
        return anchors[0][1]
    if fpl_ratio >= anchors[-1][0]:
        return anchors[-1][1]
    for (lo_r, lo_p), (hi_r, hi_p) in zip(anchors, anchors[1:]):
        if lo_r <= fpl_ratio <= hi_r:
            span = hi_r - lo_r
            frac = (fpl_ratio - lo_r) / span if span > 0 else 0.0
            return lo_p + frac * (hi_p - lo_p)
    return anchors[-1][1]


def calculate_aca_ptc(
    magi: float,
    benchmark_premium: float,
    household_size: int,
    bracket_factor: float = 1.0,
) -> float:
    """
    Annual ACA Premium Tax Credit (subsidy) for pre-65 marketplace coverage.

    The credit equals the benchmark (second-lowest-cost silver) premium minus the
    household's expected contribution (applicable % of MAGI), floored at $0 and capped at
    the premium itself. Above the 400%-FPL cliff the credit is $0 (2026 law — the ARPA/IRA
    8.5% cap has expired). `benchmark_premium` should already be in the year's nominal
    dollars; `bracket_factor` inflation-indexes the FPL thresholds to match.
    """
    if benchmark_premium <= 0:
        return 0.0
    fpl = aca_fpl(household_size, bracket_factor)
    if fpl <= 0:
        return 0.0
    fpl_ratio = magi / fpl
    if fpl_ratio > ACA_FPL_CLIFF_RATIO:
        return 0.0  # 400% FPL cliff — no subsidy
    expected_contribution = _aca_applicable_pct(fpl_ratio) * max(0.0, magi)
    return max(0.0, min(benchmark_premium, benchmark_premium - expected_contribution))


def calculate_ss_taxable_amount(
    provisional_income: float,
    ss_benefit: float,
    filing_status: str,
) -> float:
    """
    Returns the taxable portion of Social Security benefits.
    provisional_income = AGI (excluding SS) + 0.5 * ss_benefit.
    """
    if ss_benefit <= 0:
        return 0.0
    thresholds = SS_TAXABILITY[filing_status]
    t1, t2 = thresholds["tier1"], thresholds["tier2"]
    if provisional_income <= t1:
        return 0.0
    elif provisional_income <= t2:
        taxable_pct = 0.50 * min(provisional_income - t1, ss_benefit)
        return min(taxable_pct, 0.50 * ss_benefit)
    else:
        base = 0.50 * min(t2 - t1, ss_benefit)
        extra = 0.85 * min(provisional_income - t2, ss_benefit)
        return min(base + extra, 0.85 * ss_benefit)


def bracket_ceiling_for_rate(rate: float, filing_status: str, bracket_factor: float = 1.0) -> float:
    """Returns the taxable income ceiling (top of the bracket) for a given marginal rate.

    Derived from the authoritative ORDINARY_BRACKETS table rather than the partial
    BRACKET_CEILINGS lookup, which only carried the 10/12/22/24% ceilings — every other
    rate (notably 32% and 35%) silently returned 0.0, so a "fill to 32%/35% bracket"
    Roth conversion filled only to the standard deduction and converted almost nothing.
    The top bracket (37%, upper bound None) has no ceiling and returns +inf (unbounded).
    """
    for upper, r in ORDINARY_BRACKETS[filing_status]:
        if r == rate:
            return float("inf") if upper is None else upper * bracket_factor
    return 0.0


def marginal_rate(taxable_income: float, filing_status: str) -> float:
    """Returns the marginal federal rate at a given taxable income level."""
    brackets = ORDINARY_BRACKETS[filing_status]
    for upper, rate in brackets:
        if upper is None or taxable_income <= upper:
            return rate
    return 0.37


def _apply_brackets(taxable_income: float, brackets: list) -> float:
    """Generic progressive bracket calculator."""
    tax = 0.0
    prev = 0.0
    for upper, rate in brackets:
        if taxable_income <= prev:
            break
        top = upper if upper is not None else taxable_income
        tax += (min(taxable_income, top) - prev) * rate
        prev = top
    return tax


def calculate_ca_state_tax(
    ordinary_income: float,
    ltcg_income: float,
    ss_income: float,
    filing_status: str,
    ca_std: float | None = None,
    brackets: list | None = None,
) -> float:
    """
    California state income tax.
    - Capital gains taxed as ordinary income (combined with ordinary_income)
    - Social Security (ss_income) is excluded — CA does not tax SS
    - Uses CA standard deduction and CA progressive brackets
    """
    ca_std = ca_std if ca_std is not None else CA_STANDARD_DEDUCTION[filing_status]
    brackets = brackets or CA_ORDINARY_BRACKETS[filing_status]
    ca_gross = ordinary_income + ltcg_income
    ca_taxable = max(0.0, ca_gross - ca_std)
    return _apply_brackets(ca_taxable, brackets)


def calculate_mt_state_tax(
    ordinary_income: float,
    ltcg_income: float,
    filing_status: str,
    mt_std: float | None = None,
    brackets: list | None = None,
    ltcg_brackets: list | None = None,
) -> float:
    """
    Montana state income tax.
    - Long-term capital gains taxed at preferential rates (3.0% / 4.1%), stacked
      on top of ordinary income to determine the rate (mirrors the federal method)
    - Social Security taxable at same rate as federal (not excluded)
    - Standard deduction mirrors federal
    """
    mt_std = mt_std if mt_std is not None else MT_STANDARD_DEDUCTION[filing_status]
    brackets = brackets or MT_ORDINARY_BRACKETS[filing_status]
    ltcg_brackets = ltcg_brackets or MT_LTCG_BRACKETS[filing_status]

    # Standard deduction applies to combined income; when ordinary income is below
    # the deduction, the residual shelters some LTCG (same worksheet as federal).
    ordinary_taxable = max(0.0, ordinary_income - mt_std)
    total_taxable = max(0.0, ordinary_income + ltcg_income - mt_std)
    ltcg_taxable = max(0.0, total_taxable - ordinary_taxable)

    ordinary_tax = _apply_brackets(ordinary_taxable, brackets)
    ltcg_tax = calculate_ltcg_tax(ltcg_taxable, ordinary_taxable, filing_status, ltcg_brackets)
    return ordinary_tax + ltcg_tax


def effective_tax_rate(total_tax: float, gross_income: float) -> float:
    if gross_income <= 0:
        return 0.0
    return total_tax / gross_income


def calculate_year_taxes(
    ordinary_income: float,
    ltcg_income: float,
    filing_status: str,
    state: str,
    age: int,
    spouse_age: int | None,
    num_medicare_eligible: int,
    ss_income: float = 0.0,
    state_tax_rate: float = 0.0,
    net_investment_income: float | None = None,
    ss_taxable_amount: float | None = None,
    bracket_factor: float = 1.0,
) -> dict:
    """
    Full annual tax calculation. Returns a dict with each component and total.
    ordinary_income and ltcg_income are pre-standard-deduction gross amounts
    (ordinary_income should already include taxable SS).

    state: 'california' uses CA progressive brackets (no SS tax, LTCG as ordinary).
           'montana' uses MT progressive brackets (SS taxable same as federal, LTCG as ordinary).
           Any other value falls back to flat state_tax_rate.
    ss_income: gross SS collected this year (used only by CA to exclude from state tax).
    bracket_factor: cumulative inflation multiplier applied to all bracket thresholds and
                    standard deduction. SS taxability thresholds are intentionally not scaled
                    (they are not CPI-indexed under current law).
    """
    std_ded = STANDARD_DEDUCTION[filing_status] * bracket_factor
    ordinary_taxable = max(0.0, ordinary_income - std_ded)

    scaled_ord = [(u * bracket_factor if u is not None else None, r) for u, r in ORDINARY_BRACKETS[filing_status]]
    federal_ordinary = calculate_ordinary_tax(ordinary_taxable, filing_status, scaled_ord)

    # LTCG taxable income: standard deduction applies to combined income; when ordinary
    # income is below the deduction, the residual deduction shelters some LTCG.
    # IRS worksheet: taxable_ltcg = total_taxable - ordinary_taxable
    total_taxable = max(0.0, ordinary_income + ltcg_income - std_ded)
    ltcg_taxable = max(0.0, total_taxable - ordinary_taxable)
    scaled_ltcg = [(u * bracket_factor if u is not None else None, r) for u, r in LTCG_BRACKETS[filing_status]]
    federal_ltcg = calculate_ltcg_tax(ltcg_taxable, ordinary_taxable, filing_status, scaled_ltcg)

    magi = ordinary_income + ltcg_income
    # NII for NIIT: qualified dividends, capital gains, ordinary dividends, passive rental.
    # Caller should pass net_investment_income explicitly; fall back to ltcg_income only if omitted.
    nii = net_investment_income if net_investment_income is not None else ltcg_income
    niit_threshold = NIIT_THRESHOLD[filing_status] * bracket_factor
    federal_niit = calculate_niit(magi, nii, filing_status, niit_threshold)

    scaled_irmaa_tiers = [
        (mfj * bracket_factor if mfj is not None else None,
         sing * bracket_factor if sing is not None else None,
         pb, pd)
        for mfj, sing, pb, pd in IRMAA_TIERS
    ]
    federal_irmaa = calculate_irmaa(magi, filing_status, num_medicare_eligible, scaled_irmaa_tiers)

    if state == "california":
        # ordinary_income includes only the taxable portion of SS (ss_taxable_amount).
        # Subtract exactly that amount so CA sees non-SS ordinary income — CA excludes SS entirely.
        ss_excl = ss_taxable_amount if ss_taxable_amount is not None else ss_income
        scaled_ca_std = CA_STANDARD_DEDUCTION[filing_status] * bracket_factor
        scaled_ca_brackets = [(u * bracket_factor if u is not None else None, r) for u, r in CA_ORDINARY_BRACKETS[filing_status]]
        state_tax = calculate_ca_state_tax(
            ordinary_income=ordinary_income - ss_excl,
            ltcg_income=ltcg_income,
            ss_income=ss_income,
            filing_status=filing_status,
            ca_std=scaled_ca_std,
            brackets=scaled_ca_brackets,
        )
    elif state == "montana":
        scaled_mt_std = MT_STANDARD_DEDUCTION[filing_status] * bracket_factor
        scaled_mt_brackets = [(u * bracket_factor if u is not None else None, r) for u, r in MT_ORDINARY_BRACKETS[filing_status]]
        scaled_mt_ltcg = [(u * bracket_factor if u is not None else None, r) for u, r in MT_LTCG_BRACKETS[filing_status]]
        state_tax = calculate_mt_state_tax(
            ordinary_income=ordinary_income,
            ltcg_income=ltcg_income,
            filing_status=filing_status,
            mt_std=scaled_mt_std,
            brackets=scaled_mt_brackets,
            ltcg_brackets=scaled_mt_ltcg,
        )
    else:
        state_tax = (ordinary_income + ltcg_income) * state_tax_rate

    total = federal_ordinary + federal_ltcg + federal_niit + federal_irmaa + state_tax

    return {
        "federal_ordinary": federal_ordinary,
        "federal_ltcg": federal_ltcg,
        "federal_niit": federal_niit,
        "federal_irmaa": federal_irmaa,
        "state_tax": state_tax,
        "total": total,
        "effective_rate": effective_tax_rate(total, max(1, ordinary_income + ltcg_income)),
        "magi": magi,
        "ordinary_taxable": ordinary_taxable,
        "irmaa_tier_crossed": federal_irmaa > 0,
    }
