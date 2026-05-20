import pandas as pd
from taxes import marginal_rate, calculate_ltcg_tax
from constants import STANDARD_DEDUCTION, CA_ORDINARY_BRACKETS, CA_STANDARD_DEDUCTION


def _ca_marginal_rate(income: float, filing_status: str) -> float:
    """CA marginal rate on ordinary income at a given AGI (used for accumulation tax drag)."""
    ca_taxable = max(0.0, income - CA_STANDARD_DEDUCTION[filing_status])
    for upper, rate in CA_ORDINARY_BRACKETS[filing_status]:
        if upper is None or ca_taxable <= upper:
            return rate
    return CA_ORDINARY_BRACKETS[filing_status][-1][1]


TAXABLE_TYPES = {"taxable", "reit"}
TRADITIONAL_TYPES = {"traditional_401k", "traditional_ira"}
ROTH_TYPES = {"roth_401k", "roth_ira"}
PRETAX_MATCH_TYPES = {"traditional_401k", "roth_401k"}


def _default_tax_rates(filing_status: str, current_income: float | None):
    """Estimate accumulation-phase marginal rates for tax drag calculation."""
    if current_income and current_income > 0:
        # Rough: salary minus std deduction
        from constants import STANDARD_DEDUCTION
        taxable = max(0, current_income - STANDARD_DEDUCTION[filing_status])
        fed_rate = marginal_rate(taxable, filing_status)
    else:
        fed_rate = 0.22  # default assumption
    ltcg_rate = 0.15  # default assumption
    return fed_rate, ltcg_rate


def project_accumulation(accounts: list[dict], profile: dict, assumptions: dict) -> tuple[pd.DataFrame, list[dict]]:
    """
    Project account balances year-by-year from current_age to retirement_age.

    Returns:
        df: DataFrame with columns [age, account_name, balance, basis, annual_passive_income, tax_drag]
        final_accounts: list of account dicts with updated balance/basis at retirement
    """
    current_age = profile["current_age"]
    retirement_age = profile["retirement_age"]
    filing_status = profile["filing_status"]
    current_income = profile.get("current_income")
    state = profile.get("state", "california")
    state_rate = profile.get("state_tax_rate", 0.0)
    fed_rate, ltcg_rate = _default_tax_rates(filing_status, current_income)

    # Deep copy accounts so we mutate local state
    import copy
    accts = copy.deepcopy(accounts)

    rows = []

    for age in range(current_age, retirement_age + 1):
        for a in accts:
            atype = a["type"]
            # Record start-of-year balance so age == current_age shows initial balances
            bal = a["balance"]
            basis = a.get("basis", bal)

            passive_income = 0.0
            tax_drag = 0.0

            if atype == "rental_property":
                passive_income = a.get("net_annual_rental_income", 0.0)
                eff_state = _ca_marginal_rate((current_income or 0) + passive_income, filing_status) if state == "california" else state_rate
                tax_drag = passive_income * (fed_rate + eff_state)

            elif atype in TAXABLE_TYPES:
                qual_div = bal * a.get("qualified_dividend_yield", 0.0)
                ord_inc = bal * a.get("ordinary_income_yield", 0.0)
                passive_income = qual_div + ord_inc
                # CA marginal rate on ordinary income (CA taxes LTCGs as ordinary income too)
                eff_state = _ca_marginal_rate(current_income or 0, filing_status) if state == "california" else state_rate
                tax_drag = (
                    ord_inc * (fed_rate + eff_state)
                    + calculate_ltcg_tax(qual_div, max(0, (current_income or 0) - STANDARD_DEDUCTION[filing_status]), filing_status)
                    + (qual_div * eff_state if state == "california" else 0)
                )

            rows.append({
                "age": age,
                "account_id": a["id"],
                "account_name": a["name"],
                "account_type": atype,
                "balance": bal,
                "basis": basis,
                "unrealized_gain": max(0.0, bal - basis),
                "passive_income": passive_income,
                "tax_drag": tax_drag,
            })

            # Grow balance only during accumulation years; retirement_age row shows
            # start-of-retirement balances and accts retains those values for simulate_retirement.
            if age < retirement_age:
                rate = a.get("return_rate", 0.07)
                bal *= (1 + rate)

                if atype not in {"rental_property", "reit"}:
                    contrib = a.get("annual_contribution", 0.0)
                    match = 0.0
                    if atype in PRETAX_MATCH_TYPES:
                        match_pct = a.get("employer_match_percent", 0.0)
                        match_limit = a.get("employer_match_limit", 0.0)
                        match = min(contrib * match_pct, match_limit)
                    bal += contrib + match
                    if atype in TAXABLE_TYPES:
                        basis += contrib
                    a["annual_contribution"] = contrib * (1 + a.get("contribution_growth_rate", 0.0))

                a["balance"] = bal
                a["basis"] = basis

    df = pd.DataFrame(rows)

    if df.empty:
        return df, accts

    # Summary columns for stacked charts
    df["tax_bucket"] = df["account_type"].map({
        "traditional_401k": "pre_tax",
        "traditional_ira": "pre_tax",
        "roth_401k": "roth",
        "roth_ira": "roth",
        "taxable": "taxable",
        "hsa": "roth",
        "reit": "taxable",
        "rental_property": "real_estate",
        "bank": "cash",
    })

    return df, accts
