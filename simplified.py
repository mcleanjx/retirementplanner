"""Simplified mode: 5-step wizard + 4-panel results."""
import uuid
import copy

import streamlit as st
import plotly.graph_objects as go
import pandas as pd

from projections import project_accumulation
from withdrawals import simulate_retirement
from montecarlo_v2 import (
    run_monte_carlo_v2,
    DEFAULT_EQUITY_VOL, DEFAULT_BOND_VOL, DEFAULT_EQUITY_BOND_CORR,
)
from constants import RMD_START_AGE
from scenarios import (
    list_scenarios, save_scenario, load_scenario, delete_scenario,
    set_last_used_scenario,
)

_MC_TRIALS = 1000  # match advanced default trial count
_MC_STOCK_PCT = {"Conservative": 0.30, "Moderate": 0.60, "Aggressive": 0.85}

# ---------------------------------------------------------------------------
# Expert defaults applied silently in simplified mode
# ---------------------------------------------------------------------------

_RETURN_BY_STYLE = {
    "Conservative": 0.05,
    "Moderate": 0.07,
    "Aggressive": 0.09,
}

_SIMPLE_DEFAULTS = {
    "inflation_rate": 0.025,
    "bracket_inflation_rate": 0.025,
    "state_tax_rate": 0.045,
    "pre_medicare_healthcare": 15000.0,
    "post_medicare_healthcare": 12000.0,
    "withdrawal_strategy": "tax_efficient",
    "filing_status_single": "single",
    "filing_status_married": "married_filing_jointly",
}


# ---------------------------------------------------------------------------
# Account type mapping between advanced and simplified
# ---------------------------------------------------------------------------

_SIMPLE_TYPE_LABELS = {
    "tax_deferred": "Tax-Deferred (401k / IRA / 403b)",
    "roth":         "Roth (Roth 401k / Roth IRA)",
    "taxable":      "Taxable Brokerage",
    "bank":         "Bank / Cash",
}

_ADV_TO_SIMPLE_TYPE = {
    "traditional_401k": "tax_deferred",
    "traditional_ira":  "tax_deferred",
    "roth_401k":        "roth",
    "roth_ira":         "roth",
    "hsa":              "roth",
    "taxable":          "taxable",
    "reit":             "taxable",
    "bank":             "bank",
    # rental_property handled separately (income, not balance)
}

_SIMPLE_TO_ADV_TYPE = {
    "tax_deferred": "traditional_401k",
    "roth":         "roth_ira",
    "taxable":      "taxable",
    "bank":         "bank",
}


def _accounts_from_advanced(adv_accounts: list) -> list:
    """Convert advanced account list to simplified wizard account list.

    All per-account rates and settings are preserved so simplified mode
    projections match advanced mode exactly.
    """
    simple = []
    for a in adv_accounts:
        stype = _ADV_TO_SIMPLE_TYPE.get(a.get("type", ""), None)
        if stype is None:
            continue  # rental_property etc. handled via income fields
        simple.append({
            "id": a["id"],
            "name": a["name"],
            "type_simple": stype,
            # Preserve exact advanced type so accumulation (employer match, etc.) stays correct
            "type_advanced": a.get("type", "traditional_401k"),
            "balance": float(a.get("balance", 0)),
            "annual_contribution": float(a.get("annual_contribution", 0)),
            # Preserve all rate/match/priority fields so projections match advanced mode exactly
            "return_rate": float(a.get("return_rate", 0.07)),
            "use_global_return_rate": bool(a.get("use_global_return_rate", True)),
            "contribution_growth_rate": float(a.get("contribution_growth_rate", 0.0)),
            "employer_match_percent": float(a.get("employer_match_percent", 0.0)),
            "employer_match_limit": float(a.get("employer_match_limit", 0.0)),
            "basis": float(a.get("basis", 0.0)),
            "qualified_dividend_yield": float(a.get("qualified_dividend_yield", 0.0)),
            "ordinary_income_yield": float(a.get("ordinary_income_yield", 0.0)),
            "bank_buffer": float(a.get("bank_buffer", 0.0)),
            "withdraw_priority": str(a.get("withdraw_priority", "normal")),
        })
    if not simple:
        simple = [{
            "id": "simple_acc1",
            "name": "Retirement Savings",
            "type_simple": "tax_deferred",
            "balance": 200000.0,
            "annual_contribution": 15000.0,
            "return_rate": 0.07,
            "use_global_return_rate": True,
            "contribution_growth_rate": 0.0,
            "employer_match_percent": 0.0,
            "employer_match_limit": 0.0,
            "basis": 0.0,
            "qualified_dividend_yield": 0.0,
            "ordinary_income_yield": 0.0,
            "bank_buffer": 0.0,
            "withdraw_priority": "normal",
        }]
    return simple


# ---------------------------------------------------------------------------
# Wizard state init / sync
# ---------------------------------------------------------------------------

def _build_wizard_from_state() -> dict:
    """Build a fresh wizard dict from current session state (profile + accounts)."""
    p = st.session_state.get("profile", {})
    adv_accounts = st.session_state.get("accounts", [])
    assumptions = st.session_state.get("assumptions", {})

    # Preserve original rental accounts to retain property value + appreciation
    rental_accounts = [
        copy.deepcopy(a) for a in adv_accounts if a.get("type") == "rental_property"
    ]
    rental_total = sum(a.get("net_annual_rental_income", 0) for a in rental_accounts)

    current_income = float(p.get("current_income", 100000) or 100000)
    spend_target = float(assumptions.get("annual_spending_target", current_income * 0.80))

    # Map advanced global return rate to closest investment style
    adv_ret_rate = float(assumptions.get("retirement_return_rate", 0.07))
    if adv_ret_rate <= 0.06:
        inv_style = "Conservative"
    elif adv_ret_rate <= 0.08:
        inv_style = "Moderate"
    else:
        inv_style = "Aggressive"

    return {
        "scenario_name": "My Plan",
        # Step 1
        "current_age": int(p.get("current_age", 40)),
        "retirement_age": int(p.get("retirement_age", 65)),
        "life_expectancy": int(p.get("life_expectancy", 90)),
        "married": p.get("filing_status") == "married_filing_jointly",
        "spouse_age": int(p.get("spouse_age", 40)),
        "spouse_retirement_age": int(p.get("spouse_retirement_age", p.get("retirement_age", 65))),
        "survivor_spending_reduction": float(p.get("survivor_spending_reduction", 0.25)),
        # Step 2 — individual accounts
        "accounts": _accounts_from_advanced(adv_accounts),
        # Step 3
        "has_ss": float(p.get("social_security_benefit", 0)) > 0,
        "ss_benefit": float(p.get("social_security_benefit", 24000)),
        "ss_start_age": int(p.get("social_security_start_age", 67)),
        "spouse_ss_benefit": float(p.get("spouse_ss_benefit", 0)),
        "spouse_ss_start_age": int(p.get("spouse_ss_start_age", 67)),
        "has_pension": False,
        "pension": 0.0,
        "has_rental": rental_total > 0,
        "rental_income": float(rental_total),
        "rental_accounts": rental_accounts,  # original adv accounts preserved for projection
        # Step 4
        "spending_mode": "dollar",
        "spending_pct": 80,
        "spending_dollar": int(spend_target),
        "current_income": current_income,
        "investment_style": inv_style,
        # Preserve exact global rate from advanced mode
        "global_return_rate": adv_ret_rate,
        # Preserve all advanced assumptions and profile settings so projections match exactly
        "inflation_rate": float(assumptions.get("inflation_rate", 0.025)),
        "bracket_inflation_rate": float(assumptions.get("bracket_inflation_rate", 0.025)),
        "safe_withdrawal_rate": float(assumptions.get("safe_withdrawal_rate", 0.04)),
        "withdrawal_strategy": str(assumptions.get("withdrawal_strategy", "tax_efficient")),
        "state": str(p.get("state", "other")),
        "state_tax_rate": float(p.get("state_tax_rate", 0.045)),
        "pre_medicare_healthcare": float(p.get("pre_medicare_healthcare", 15000.0)),
        "post_medicare_healthcare": float(p.get("post_medicare_healthcare", 12000.0)),
        # Carry through the spending mode so simplified matches advanced exactly
        "engine_spending_mode": str(assumptions.get("spending_mode", "swr")),
    }


def _wizard_has_data(w: dict) -> bool:
    """True if the wizard has enough filled-in data to skip straight to results."""
    accts = w.get("accounts", [])
    return bool(accts) and sum(a.get("balance", 0) for a in accts) > 0


def _init_wizard():
    needs_sync = st.session_state.pop("wizard_needs_sync", False)
    if "wizard" not in st.session_state or needs_sync:
        st.session_state.wizard = _build_wizard_from_state()
        w = st.session_state.wizard
        if _wizard_has_data(w):
            # Pre-populated from advanced mode or loaded scenario — skip to results
            st.session_state.wizard_complete = True
            st.session_state.wizard_ever_completed = True
            st.session_state.wizard_step = 5
        else:
            st.session_state.wizard_complete = False
            st.session_state.wizard_step = 1
    else:
        w = st.session_state.wizard
        # Patch stale wizard dicts that predate the spending_mode field
        if "engine_spending_mode" not in w:
            adv_assumptions = st.session_state.get("assumptions", {})
            w["engine_spending_mode"] = str(adv_assumptions.get("spending_mode", "swr"))
    if "wizard_step" not in st.session_state:
        st.session_state.wizard_step = 1
    if "wizard_complete" not in st.session_state:
        st.session_state.wizard_complete = False
    if "wizard_ever_completed" not in st.session_state:
        st.session_state.wizard_ever_completed = st.session_state.wizard_complete


# ---------------------------------------------------------------------------
# Build plan from wizard data
# ---------------------------------------------------------------------------

def _build_simple_plan(w: dict, extra_savings: float = 0.0,
                       retirement_age_delta: int = 0,
                       spending_delta: float = 0.0,
                       year1_spending_base: float | None = None) -> tuple:
    """Convert wizard answers → (profile, assumptions, accounts, roth_conversion)."""
    ret_age = max(w["current_age"] + 1, w["retirement_age"] + retirement_age_delta)
    ret_age = min(ret_age, 80)

    spending_target = (
        w["current_income"] * w["spending_pct"] / 100
        if w["spending_mode"] == "pct"
        else float(w["spending_dollar"])
    )
    spending_target = max(0.0, spending_target + spending_delta)

    # Use preserved advanced global rate if available; otherwise use style default
    return_rate = w.get("global_return_rate", _RETURN_BY_STYLE[w["investment_style"]])

    filing = (
        _SIMPLE_DEFAULTS["filing_status_married"]
        if w["married"]
        else _SIMPLE_DEFAULTS["filing_status_single"]
    )

    profile = {
        "current_age": w["current_age"],
        "retirement_age": ret_age,
        "life_expectancy": w["life_expectancy"],
        "filing_status": filing,
        "state": w.get("state", "other"),
        "state_tax_rate": w.get("state_tax_rate", _SIMPLE_DEFAULTS["state_tax_rate"]),
        "current_income": w["current_income"],
        "social_security_benefit": w["ss_benefit"] if w["has_ss"] else 0.0,
        "social_security_start_age": w["ss_start_age"],
        "pre_medicare_healthcare": w.get("pre_medicare_healthcare", _SIMPLE_DEFAULTS["pre_medicare_healthcare"]),
        "post_medicare_healthcare": w.get("post_medicare_healthcare", _SIMPLE_DEFAULTS["post_medicare_healthcare"]),
    }
    if w["married"]:
        profile.update({
            "spouse_age": w["spouse_age"],
            "spouse_retirement_age": w.get("spouse_retirement_age", ret_age),
            "spouse_ss_benefit": w["spouse_ss_benefit"],
            "spouse_ss_start_age": w["spouse_ss_start_age"],
            "survivor_spending_reduction": w.get("survivor_spending_reduction", 0.25),
        })

    engine_mode = w.get("engine_spending_mode", "fixed")
    # When spending_delta is applied in SWR mode (lever: "spend less"), switch to fixed
    # mode using the estimated year-1 after-tax spending as the base, so the comparison
    # is meaningful (otherwise spending_delta has no effect in SWR mode).
    if engine_mode == "swr" and spending_delta != 0.0:
        if year1_spending_base is not None:
            engine_mode = "fixed"
            spending_target = max(0.0, year1_spending_base + spending_delta)
        # else: stay SWR, spending_delta can't be applied without portfolio estimate

    assumptions = {
        "inflation_rate": w.get("inflation_rate", _SIMPLE_DEFAULTS["inflation_rate"]),
        "bracket_inflation_rate": w.get("bracket_inflation_rate", _SIMPLE_DEFAULTS["bracket_inflation_rate"]),
        "retirement_return_rate": return_rate,
        "spending_mode": engine_mode,
        "annual_spending_target": spending_target,
        "safe_withdrawal_rate": w.get("safe_withdrawal_rate", 0.04),
        "withdrawal_strategy": w.get("withdrawal_strategy", _SIMPLE_DEFAULTS["withdrawal_strategy"]),
    }

    accounts = []
    first_investable = True
    for wa in w.get("accounts", []):
        # Use the preserved advanced type (maintains employer-match behaviour for roth_401k, etc.)
        # Fall back to the simple→advanced mapping for accounts created fresh in the wizard.
        acct_type = wa.get("type_advanced") or _SIMPLE_TO_ADV_TYPE.get(wa["type_simple"], "traditional_401k")
        # Use the preserved per-account basis if available; fall back to estimate
        if "basis" in wa:
            basis = wa["basis"]
        elif acct_type == "roth_ira":
            basis = wa["balance"]
        elif acct_type == "taxable":
            basis = wa["balance"] * 0.7
        else:
            basis = 0.0
        contrib = wa["annual_contribution"]
        if first_investable and extra_savings:
            contrib += extra_savings
            first_investable = False
        # Use the per-account return rate if available; fall back to style default
        acct_return = wa.get("return_rate", return_rate)
        use_global = wa.get("use_global_return_rate", False)
        accounts.append(_make_acct(
            wa["name"], acct_type, wa["balance"], contrib,
            acct_return,
            basis=basis,
            acct_id=wa["id"],
            contribution_growth_rate=wa.get("contribution_growth_rate", 0.0),
            employer_match_percent=wa.get("employer_match_percent", 0.0),
            employer_match_limit=wa.get("employer_match_limit", 0.0),
            qualified_dividend_yield=wa.get("qualified_dividend_yield",
                                             0.015 if acct_type == "taxable" else 0.0),
            ordinary_income_yield=wa.get("ordinary_income_yield", 0.0),
            use_global_return_rate=use_global,
            bank_buffer=wa.get("bank_buffer", 0.0),
            withdraw_priority=wa.get("withdraw_priority", "normal"),
        ))
        if first_investable:
            first_investable = False

    # Include original rental/property accounts (preserves balance, appreciation, income)
    orig_rentals = w.get("rental_accounts", [])
    if orig_rentals:
        for ra in orig_rentals:
            accounts.append(copy.deepcopy(ra))
        # Add wizard pension as extra income on top of advanced rental income
        if w.get("has_pension") and w.get("pension", 0) > 0:
            accounts.append({
                "id": "simple_pension",
                "name": "Pension",
                "type": "rental_property",
                "balance": 0.0,
                "basis": 0.0,
                "annual_contribution": 0.0,
                "contribution_growth_rate": 0.0,
                "return_rate": 0.0,
                "employer_match_percent": 0.0,
                "employer_match_limit": 0.0,
                "qualified_dividend_yield": 0.0,
                "ordinary_income_yield": 0.0,
                "net_annual_rental_income": w["pension"],
                "use_global_return_rate": False,
                "bank_buffer": 0.0,
                "withdraw_priority": "normal",
            })
    elif w.get("has_rental") and w.get("rental_income", 0) > 0:
        # New wizard-only rental (no advanced accounts to carry over)
        accounts.append({
            "id": "simple_rental",
            "name": "Rental / Pension Income",
            "type": "rental_property",
            "balance": 0.0,
            "basis": 0.0,
            "annual_contribution": 0.0,
            "contribution_growth_rate": 0.0,
            "return_rate": 0.0,
            "employer_match_percent": 0.0,
            "employer_match_limit": 0.0,
            "qualified_dividend_yield": 0.0,
            "ordinary_income_yield": 0.0,
            "net_annual_rental_income": w["rental_income"] + (w["pension"] if w.get("has_pension") else 0.0),
            "use_global_return_rate": False,
            "bank_buffer": 0.0,
            "withdraw_priority": "normal",
        })
    elif w.get("has_pension") and w.get("pension", 0) > 0:
        accounts.append({
            "id": "simple_pension",
            "name": "Pension",
            "type": "rental_property",
            "balance": 0.0,
            "basis": 0.0,
            "annual_contribution": 0.0,
            "contribution_growth_rate": 0.0,
            "return_rate": 0.0,
            "employer_match_percent": 0.0,
            "employer_match_limit": 0.0,
            "qualified_dividend_yield": 0.0,
            "ordinary_income_yield": 0.0,
            "net_annual_rental_income": w["pension"],
            "use_global_return_rate": False,
            "bank_buffer": 0.0,
            "withdraw_priority": "normal",
        })

    rc = {
        "enabled": False,
        "strategy": "fill_to_bracket",
        "target_bracket": 0.12,
        "fixed_amount": 0.0,
        "start_age": ret_age,
        "end_age": min(ret_age + 10, RMD_START_AGE - 1),
        "source_account_ids": [],
        "destination_account_id": "",
        "allow_during_accumulation": False,
    }
    return profile, assumptions, accounts, rc


def _make_acct(name, acct_type, balance, contribution, return_rate, basis=0.0, acct_id=None,
               contribution_growth_rate=0.0, employer_match_percent=0.0,
               employer_match_limit=0.0, qualified_dividend_yield=None,
               ordinary_income_yield=0.0, use_global_return_rate=False,
               bank_buffer=0.0, withdraw_priority="normal"):
    if qualified_dividend_yield is None:
        qualified_dividend_yield = 0.015 if acct_type == "taxable" else 0.0
    return {
        "id": acct_id or f"simple_{acct_type}_{uuid.uuid4().hex[:6]}",
        "name": name,
        "type": acct_type,
        "balance": float(balance),
        "basis": float(basis),
        "annual_contribution": float(contribution),
        "contribution_growth_rate": float(contribution_growth_rate),
        "return_rate": float(return_rate),
        "employer_match_percent": float(employer_match_percent),
        "employer_match_limit": float(employer_match_limit),
        "qualified_dividend_yield": float(qualified_dividend_yield),
        "ordinary_income_yield": float(ordinary_income_yield),
        "net_annual_rental_income": 0.0,
        "use_global_return_rate": bool(use_global_return_rate),
        "bank_buffer": float(bank_buffer),
        "withdraw_priority": str(withdraw_priority),
    }


def _run_projection(profile, assumptions, accounts, rc):
    try:
        acc_df, accts_at_ret = project_accumulation(accounts, profile, assumptions)
        ret_df, summary = simulate_retirement(accts_at_ret, profile, assumptions, rc, {})
        return acc_df, ret_df, summary, accts_at_ret
    except Exception as e:
        return pd.DataFrame(), pd.DataFrame(), {"error": str(e)}, []


def _run_mc(accts_at_ret: list, profile: dict, assumptions: dict, style: str) -> dict:
    if not accts_at_ret:
        return {}
    s = st.session_state
    # Mirror the advanced MC tab parameters exactly, using the same slider defaults.
    # Session state keys (mc_equity_vol, mc_bond_vol, etc.) store the raw integer slider
    # values (e.g. 16 for 16%), matching the widget key names in app.py.
    equity_vol    = s.get("mc_equity_vol",    16) / 100.0   # advanced default: 16%
    bond_vol      = s.get("mc_bond_vol",       6) / 100.0   # advanced default: 6%
    eq_bond_corr  = s.get("mc_eq_bond_corr",  10) / 100.0   # advanced default: 10%
    # Stock allocation: use advanced slider value if set, else style-based default
    raw_sp = s.get("mc_stock_pct", None)
    stock_pct = (raw_sp / 100.0) if raw_sp is not None else _MC_STOCK_PCT.get(style, 0.60)
    try:
        return run_monte_carlo_v2(
            accts_at_ret, profile, assumptions,
            n_runs=_MC_TRIALS,
            stock_pct=stock_pct,
            equity_vol=equity_vol,
            bond_vol=bond_vol,
            equity_bond_corr=eq_bond_corr,
            seed=42,
        )
    except Exception:
        return {}


def _compute_score(ret_df, summary, profile):
    depletion = summary.get("portfolio_depleted_age")
    le = profile["life_expectancy"]
    ret_age = profile["retirement_age"]
    years_needed = max(1, le - ret_age)

    if depletion is None:
        # Survives to LE — check surplus
        le_row = ret_df[ret_df["age"] == le] if not ret_df.empty else pd.DataFrame()
        surplus = float(le_row["total_portfolio"].iloc[0]) if not le_row.empty else 0.0
        return 100, surplus
    else:
        years_funded = max(0, depletion - ret_age)
        score = int(years_funded / years_needed * 100)
        return score, 0.0


# ---------------------------------------------------------------------------
# Wizard UI
# ---------------------------------------------------------------------------

def _progress_bar(step: int):
    """Clickable progress bar. All steps clickable once data has been entered."""
    labels = ["About You", "Accounts", "Income", "Your Goal", "Review"]
    wizard_complete = st.session_state.get("wizard_complete", False)
    ever_completed = st.session_state.get("wizard_ever_completed", False)
    cols = st.columns(len(labels))
    for i, (col, label) in enumerate(zip(cols, labels), 1):
        is_active = (i == step) and not wizard_complete
        is_done = (i < step) or wizard_complete
        # All steps clickable once the wizard has been completed at least once
        is_clickable = is_done or is_active or ever_completed
        btn_label = f"✓ {label}" if is_done else label
        clicked = col.button(
            btn_label,
            key=f"wprog_{i}",
            use_container_width=True,
            type="primary" if is_active else "secondary",
            disabled=not is_clickable,
        )
        if clicked and not is_active:
            st.session_state.wizard_step = i
            st.session_state.wizard_complete = False
            st.rerun()


def _nav_buttons(step: int, can_next: bool = True, next_label: str = "Next →"):
    cols = st.columns([1, 4, 1])
    with cols[0]:
        if step > 1 and st.button("← Back", use_container_width=True):
            st.session_state.wizard_step = step - 1
            st.rerun()
    with cols[2]:
        if st.button(next_label, disabled=not can_next, type="primary", use_container_width=True):
            return True
    return False


def _step1():
    w = st.session_state.wizard
    st.subheader("Step 1 — About You")
    c1, c2 = st.columns(2)
    w["current_age"] = c1.number_input("Your current age", 18, 80, w["current_age"], key="wiz_cur_age")
    ret_min = w["current_age"] + 1
    w["retirement_age"] = c2.number_input(
        "When do you want to retire?", ret_min, 80,
        max(ret_min, w["retirement_age"]), key="wiz_ret_age"
    )
    w["life_expectancy"] = st.slider(
        "How long do you want your plan to last? (planning age)", 75, 100, w["life_expectancy"],
        help="Better to plan long than run short. Most planners use 90–95.",
        key="wiz_le",
    )
    w["married"] = st.toggle("I have a spouse or partner", value=w["married"], key="wiz_married")
    if w["married"]:
        w["spouse_age"] = st.number_input("Spouse's current age", 18, 80, w["spouse_age"], key="wiz_sp_age")

    if _nav_buttons(1, next_label="Next →"):
        st.session_state.wizard_step = 2
        st.rerun()


def _account_card(a: dict, idx: int, to_delete_ref: list):
    """Render a single account card. Appends idx to to_delete_ref if delete clicked."""
    with st.container(border=True):
        c_name, c_del = st.columns([6, 1])
        a["name"] = c_name.text_input("Account name", a["name"], key=f"wiz_aname_{idx}")
        c_del.write("")
        c_del.write("")
        if c_del.button("✕", key=f"wiz_adel_{idx}", help="Remove"):
            to_delete_ref.append(idx)

        type_labels = list(_SIMPLE_TYPE_LABELS.keys())
        cur_idx = type_labels.index(a["type_simple"]) if a["type_simple"] in type_labels else 0
        a["type_simple"] = st.selectbox(
            "Type",
            type_labels,
            index=cur_idx,
            format_func=lambda k: _SIMPLE_TYPE_LABELS[k],
            key=f"wiz_atype_{idx}",
        )

        c_bal, c_contrib = st.columns(2)
        a["balance"] = float(c_bal.number_input(
            "Balance ($)", 0, 10_000_000, int(a["balance"]), 1000, key=f"wiz_abal_{idx}"
        ))
        a["annual_contribution"] = float(c_contrib.number_input(
            "Annual contrib ($)", 0, 200_000, int(a["annual_contribution"]), 500,
            help="Your contributions + employer match",
            key=f"wiz_acontrib_{idx}",
        ))

        if a["type_simple"] == "taxable":
            basis_default = int(a.get("basis", int(a["balance"] * 0.7)))
            a["basis"] = float(st.number_input(
                "Cost basis ($)",
                0, 10_000_000,
                basis_default,
                1000,
                key=f"wiz_abasis_{idx}",
                help=(
                    "Original amount you invested (what you paid in total). "
                    "Used to calculate capital gains taxes on withdrawals. "
                    "If unsure, 70% of balance is a reasonable estimate."
                ),
            ))


def _step2():
    w = st.session_state.wizard
    st.subheader("Step 2 — Your Accounts")
    st.caption(
        "Enter each of your retirement and investment accounts. "
        "Include 401(k), IRA, Roth IRA, brokerage, and bank accounts."
    )

    accts = w.setdefault("accounts", [])
    to_delete: list[int] = []

    # Two accounts per row on wider screens
    for row_start in range(0, len(accts), 2):
        left_col, right_col = st.columns(2)
        for j, col in enumerate([left_col, right_col]):
            idx = row_start + j
            if idx >= len(accts):
                break
            with col:
                _account_card(accts[idx], idx, to_delete)

    if to_delete:
        for idx in sorted(to_delete, reverse=True):
            accts.pop(idx)
        st.rerun()

    col_add, _ = st.columns([1, 3])
    if col_add.button("+ Add Account", key="wiz_add_acct"):
        accts.append({
            "id": f"simple_{uuid.uuid4().hex[:8]}",
            "name": f"Account {len(accts) + 1}",
            "type_simple": "tax_deferred",
            "balance": 0.0,
            "annual_contribution": 0.0,
            "basis": 0.0,
        })
        st.rerun()

    if not accts:
        st.warning("Add at least one account to continue.")

    can_next = len(accts) > 0
    if _nav_buttons(2, can_next=can_next, next_label="Next →"):
        st.session_state.wizard_step = 3
        st.rerun()


def _step3():
    w = st.session_state.wizard
    st.subheader("Step 3 — Retirement Income")

    w["has_ss"] = st.toggle("I expect to receive Social Security", value=w["has_ss"], key="wiz_has_ss")
    if w["has_ss"]:
        c1, c2 = st.columns(2)
        w["ss_benefit"] = float(c1.number_input(
            "Your estimated SS benefit ($/year, today's dollars)", 0, 60000,
            int(w["ss_benefit"]), 500,
            help="Find this at ssa.gov/myaccount. Enter in today's dollars.",
            key="wiz_ss"
        ))
        w["ss_start_age"] = c2.number_input(
            "Age you'll claim SS", 62, 70, w["ss_start_age"], key="wiz_ss_age"
        )
        if w["married"]:
            cs1, cs2 = st.columns(2)
            w["spouse_ss_benefit"] = float(cs1.number_input(
                "Spouse SS benefit ($/year, today's dollars)", 0, 60000,
                int(w["spouse_ss_benefit"]), 500, key="wiz_sp_ss"
            ))
            w["spouse_ss_start_age"] = cs2.number_input(
                "Spouse SS start age", 62, 70, w["spouse_ss_start_age"], key="wiz_sp_ss_age"
            )

    st.divider()
    w["has_pension"] = st.toggle("I have a pension", value=w.get("has_pension", False), key="wiz_has_pension")
    if w["has_pension"]:
        w["pension"] = float(st.number_input(
            "Annual pension income (today's $)", 0, 500000,
            int(w.get("pension", 0)), 500, key="wiz_pension"
        ))

    w["has_rental"] = st.toggle("I have rental property income", value=w.get("has_rental", False), key="wiz_has_rental")
    if w["has_rental"]:
        w["rental_income"] = float(st.number_input(
            "Net annual rental income (today's $)", 0, 500000,
            int(w.get("rental_income", 0)), 500, key="wiz_rental"
        ))

    if _nav_buttons(3, next_label="Next →"):
        st.session_state.wizard_step = 4
        st.rerun()


def _step4():
    w = st.session_state.wizard
    st.subheader("Step 4 — Your Retirement Goal")

    engine_mode = w.get("engine_spending_mode", "fixed")

    if engine_mode == "swr":
        # Advanced mode uses portfolio-based spending (SWR) — carry that through
        swr = w.get("safe_withdrawal_rate", 0.04)
        st.info(
            f"Your plan uses **Safe Withdrawal Rate spending** ({swr*100:.1f}% of your portfolio each year). "
            "This is carried from your Advanced settings — your annual spending scales with your portfolio value. "
            "Switch to Advanced Mode to change the SWR percentage."
        )
        # Estimate approximate spending so the user has a reference number
        r = w.get("global_return_rate", _RETURN_BY_STYLE[w["investment_style"]])
        infl = w.get("inflation_rate", 0.025)
        years = max(1, w["retirement_age"] - w["current_age"])
        total_bal = sum(a.get("balance", 0) for a in w.get("accounts", []))
        total_contrib = sum(a.get("annual_contribution", 0) for a in w.get("accounts", []))
        if r > 1e-6:
            fv = total_bal * (1 + r) ** years + total_contrib * ((1 + r) ** years - 1) / r
        else:
            fv = total_bal + total_contrib * years
        est_nom = fv * swr
        est_today = est_nom / (1 + infl) ** years if years > 0 else est_nom
        st.metric(
            "Estimated retirement spending",
            f"${est_today:,.0f}/yr (today's $)",
            help=f"Approximate: {swr*100:.1f}% × estimated portfolio of ${fv:,.0f} at retirement, discounted to today's dollars",
        )
    else:
        mode = st.radio(
            "How do you want to set your spending goal?",
            ["Percentage of current income", "Specific dollar amount"],
            index=0 if w["spending_mode"] == "pct" else 1,
            horizontal=True,
            key="wiz_spend_mode_radio",
        )
        w["spending_mode"] = "pct" if "Percentage" in mode else "dollar"

        if w["spending_mode"] == "pct":
            w["current_income"] = float(st.number_input(
                "Your current annual income ($)", 0, 2_000_000,
                int(w["current_income"]), 1000, key="wiz_income"
            ))
            w["spending_pct"] = st.slider(
                "Target spending as % of current income", 50, 100, w["spending_pct"],
                help="Most planners use 70–85% of pre-retirement income.",
                key="wiz_spend_pct"
            )
            implied = w["current_income"] * w["spending_pct"] / 100
            st.info(f"This equals **${implied:,.0f}/year** in today's dollars.")
        else:
            w["spending_dollar"] = int(st.number_input(
                "Target after-tax annual spending in retirement ($, today's dollars)",
                10000, 1_000_000, int(w["spending_dollar"]), 1000, key="wiz_spend_dollar"
            ))

    st.divider()
    w["investment_style"] = st.radio(
        "How would you describe your investment approach?",
        list(_RETURN_BY_STYLE.keys()),
        index=list(_RETURN_BY_STYLE.keys()).index(w["investment_style"]),
        horizontal=True,
        key="wiz_style",
    )
    rate = _RETURN_BY_STYLE[w["investment_style"]]
    # Keep global_return_rate in sync with style selection
    w["global_return_rate"] = rate
    st.caption(
        f"We'll use a **{rate*100:.0f}% annual return** assumption. "
        "Conservative = bonds-heavy; Aggressive = stocks-heavy."
    )

    if _nav_buttons(4, next_label="See My Results →"):
        st.session_state.wizard_step = 5
        st.session_state.wizard_complete = True
        st.session_state.wizard_ever_completed = True
        st.rerun()


def _step5_review():
    """Confirm screen before showing results."""
    w = st.session_state.wizard
    st.subheader("Step 5 — Review")

    engine_mode = w.get("engine_spending_mode", "fixed")
    if engine_mode == "swr":
        swr = w.get("safe_withdrawal_rate", 0.04)
        spending_line = f"- Spending method: **Safe Withdrawal Rate ({swr*100:.1f}% of portfolio annually)**"
    else:
        spending_target = (
            w["current_income"] * w["spending_pct"] / 100
            if w["spending_mode"] == "pct"
            else float(w["spending_dollar"])
        )
        spending_line = f"- Retirement spending goal: **${spending_target:,.0f}/year** (today's dollars)"

    total_savings = sum(a["balance"] for a in w.get("accounts", []))
    total_contrib = sum(a["annual_contribution"] for a in w.get("accounts", []))
    acct_lines = "\n".join(
        f"  - **{a['name']}** ({_SIMPLE_TYPE_LABELS.get(a['type_simple'], a['type_simple'])}): "
        f"${a['balance']:,.0f} balance, ${a['annual_contribution']:,.0f}/yr"
        for a in w.get("accounts", [])
    )

    st.markdown(f"""
**Based on what you told us:**
- You'll retire at **{w['retirement_age']}** with a plan running to age **{w['life_expectancy']}**
- Total savings: **${total_savings:,.0f}** across {len(w.get('accounts', []))} account(s), contributing **${total_contrib:,.0f}/year**
{acct_lines}
- Social Security: **${w['ss_benefit']:,.0f}/year** starting at **{w['ss_start_age']}**
{f"- Spouse SS: **${w['spouse_ss_benefit']:,.0f}/year**" if w['married'] and w['has_ss'] else ""}
{f"- Pension: **${w['pension']:,.0f}/year**" if w.get('has_pension') and w.get('pension',0) > 0 else ""}
{f"- Rental income: **${w['rental_income']:,.0f}/year**" if w.get('has_rental') and w.get('rental_income',0) > 0 else ""}
{spending_line}
- Investment approach: **{w['investment_style']}** ({_RETURN_BY_STYLE[w['investment_style']]*100:.0f}% return)
    """)

    c1, _, c2 = st.columns([1, 3, 1])
    with c1:
        if st.button("← Edit Answers", use_container_width=True):
            st.session_state.wizard_step = 1
            st.session_state.wizard_complete = False
            st.rerun()
    with c2:
        if st.button("Show Results →", type="primary", use_container_width=True):
            st.session_state.wizard_complete = True
            st.session_state.wizard_ever_completed = True
            st.rerun()


def _show_wizard():
    step = st.session_state.wizard_step
    if step == 1:
        _step1()
    elif step == 2:
        _step2()
    elif step == 3:
        _step3()
    elif step == 4:
        _step4()
    elif step == 5:
        _step5_review()


# ---------------------------------------------------------------------------
# Results panels
# ---------------------------------------------------------------------------

def _score_color(score: int) -> tuple[str, str, str]:
    """Returns (bg, text, label) for the score."""
    if score >= 95:
        return "#c6f6d5", "#276749", "You're in great shape"
    if score >= 80:
        return "#c6f6d5", "#276749", "On Track"
    if score >= 65:
        return "#fefcbf", "#744210", "Close — some adjustments help"
    if score >= 50:
        return "#feebc8", "#7b341e", "Needs Attention"
    return "#fed7d7", "#9b2c2c", "At Risk"


def _mc_color_band(mc_pct: int | None) -> tuple[str, str, str, str]:
    """Return (bg, fg, label, description) for a Monte Carlo success rate."""
    if mc_pct is None:
        return "#f7fafc", "#718096", "—", ""
    if mc_pct >= 85:
        return (
            "#c6f6d5", "#276749", "Conservative",
            "Ideal if you have little flexibility to cut spending in a down market.",
        )
    if mc_pct >= 75:
        return (
            "#fefcbf", "#744210", "Realistic / Dynamic",
            "Works for retirees who can adjust spending during a severe market downturn.",
        )
    return (
        "#fed7d7", "#9b2c2c", "At Risk",
        "Consider delaying retirement, saving more, or reducing planned fixed expenses.",
    )


def _render_score_card(score: int, surplus: float, profile: dict, depletion_age, mc_result: dict):
    bg, fg, label = _score_color(score)
    le = profile["life_expectancy"]

    if depletion_age:
        detail = (
            f"Median projection: portfolio runs out at age **{depletion_age}** — "
            f"{le - depletion_age} years short of your plan."
        )
    elif surplus > 0:
        detail = f"Median projection: **${surplus:,.0f} surplus** remaining at age {le}."
    else:
        detail = f"Median projection: portfolio lasts through age {le}."

    display_score = min(score, 100)
    success_rate = mc_result.get("success_rate", 0) if mc_result else None
    mc_pct = int(success_rate * 100) if success_rate is not None else None
    mc_bg, mc_fg, mc_label, mc_desc = _mc_color_band(mc_pct)
    n_runs = mc_result.get("n_runs", _MC_TRIALS) if mc_result else _MC_TRIALS
    n_success = int(success_rate * n_runs) if success_rate is not None else 0

    st.markdown(
        f"""
        <div style="border-radius:16px;padding:1.5rem 2rem;margin-bottom:0.5rem;
                    display:flex;align-items:stretch;gap:1.5rem;flex-wrap:wrap;">
            <div style="flex:1;min-width:160px;text-align:center;
                        background:{bg};border-radius:12px;padding:1.2rem 1.5rem;">
                <div style="font-size:0.8rem;color:{fg};font-weight:600;
                            letter-spacing:0.05em;text-transform:uppercase;">
                    Retirement Score
                </div>
                <div style="font-size:3.5rem;font-weight:800;color:{fg};line-height:1.1;">
                    {display_score}%
                </div>
                <div style="font-size:1rem;font-weight:700;color:{fg};">
                    {label}
                </div>
            </div>
            {f'''<div style="flex:1;min-width:200px;text-align:center;
                        background:{mc_bg};border-radius:12px;padding:1.2rem 1.5rem;">
                <div style="font-size:0.8rem;color:{mc_fg};font-weight:600;
                            letter-spacing:0.05em;text-transform:uppercase;">
                    Market Scenarios (CMA Log-Normal)
                </div>
                <div style="font-size:3.5rem;font-weight:800;color:{mc_fg};line-height:1.1;">
                    {mc_pct}%
                </div>
                <div style="font-size:1rem;font-weight:700;color:{mc_fg};margin-bottom:0.3rem;">
                    {mc_label}
                </div>
                <div style="font-size:0.8rem;color:{mc_fg};opacity:0.85;line-height:1.4;">
                    {mc_desc}
                </div>
                <div style="font-size:0.75rem;color:{mc_fg};opacity:0.65;margin-top:0.4rem;">
                    {n_success:,} of {n_runs:,} simulations succeed to age {le}
                </div>
            </div>''' if mc_pct is not None else ''}
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption(detail)
    st.caption(
        "**Market scenario thresholds:** "
        "≥ 85% Conservative — little flexibility needed &nbsp;·&nbsp; "
        "75–84% Realistic — works with some spending flexibility &nbsp;·&nbsp; "
        "< 75% At Risk — intervention recommended"
    )


def _render_spending_summary(ret_df: pd.DataFrame, profile: dict, assumptions: dict):
    if ret_df.empty:
        return

    inflation = assumptions.get("inflation_rate", _SIMPLE_DEFAULTS["inflation_rate"])
    years_to_ret = max(0, profile["retirement_age"] - profile["current_age"])
    spending_mode = assumptions.get("spending_mode", "fixed")
    row1 = ret_df.iloc[0]
    after_tax_yr1 = float(row1["after_tax_spending"])

    st.subheader("What You Can Spend")
    c1, c2, c3 = st.columns(3)

    if spending_mode == "swr":
        swr = assumptions.get("safe_withdrawal_rate", 0.04)
        after_tax_today = after_tax_yr1 / (1 + inflation) ** years_to_ret if years_to_ret > 0 else after_tax_yr1
        c1.metric(
            "Safe Withdrawal Rate",
            f"{swr*100:.1f}%",
            help="Percentage of your portfolio withdrawn each year — spending scales with portfolio value",
        )
        c2.metric(
            f"Year 1 after-tax spending",
            f"${after_tax_yr1:,.0f}/yr",
            help="Actual after-tax cash in year 1 of retirement (nominal dollars)",
        )
        c3.metric(
            "Same in today's dollars",
            f"${after_tax_today:,.0f}/yr",
            help=f"Year 1 spending discounted by {years_to_ret} years of inflation to today's purchasing power",
        )
    else:
        spending_today = assumptions["annual_spending_target"]
        spending_nominal_yr1 = spending_today * (1 + inflation) ** years_to_ret
        c1.metric(
            "Your spending goal",
            f"${spending_today:,.0f}/yr",
            help="In today's dollars — what you entered in the wizard",
        )
        c2.metric(
            f"In retirement (age {profile['retirement_age']})",
            f"${spending_nominal_yr1:,.0f}/yr",
            help=f"Same purchasing power in future (nominal) dollars after {years_to_ret} years of inflation",
        )
        c3.metric(
            "After-tax spending (year 1)",
            f"${after_tax_yr1:,.0f}/yr",
            help="Actual after-tax cash — what the simulation shows you'll receive after taxes",
        )


def _render_simple_income_chart(ret_df: pd.DataFrame, profile: dict, assumptions: dict):
    """Stacked bar of grouped income sources + after-tax spending line — retirement years only."""
    if ret_df.empty:
        return
    st.subheader("Annual Retirement Income & Taxes")

    inflation = assumptions.get("inflation_rate", 0.025)
    ret_age = profile["retirement_age"]
    cur_age = profile["current_age"]

    # Group the detail columns into 5 income buckets
    grouped = {
        "Social Security":    ret_df.get("ss_income",              pd.Series(0, index=ret_df.index)),
        "Tax-Deferred":       ret_df.get("traditional_withdrawal",  pd.Series(0, index=ret_df.index))
                            + ret_df.get("rmd_amount",              pd.Series(0, index=ret_df.index)),
        "Roth":               ret_df.get("roth_withdrawal",         pd.Series(0, index=ret_df.index)),
        "Taxable / Cash":     ret_df.get("taxable_withdrawal",      pd.Series(0, index=ret_df.index))
                            + ret_df.get("bank_withdrawal",         pd.Series(0, index=ret_df.index))
                            + ret_df.get("investment_income",       pd.Series(0, index=ret_df.index)),
        "Rental / Pension":   ret_df.get("rental_income",           pd.Series(0, index=ret_df.index)),
    }

    # Match advanced page color palette
    group_colors = {
        "Social Security":  "#2ca02c",
        "Tax-Deferred":     "#4C72B0",
        "Roth":             "#55A868",
        "Taxable / Cash":   "#DD8452",
        "Rental / Pension": "#8172B2",
    }

    fig = go.Figure()
    for label, series in grouped.items():
        if series.sum() < 1:
            continue
        fig.add_trace(go.Bar(
            x=ret_df["age"], y=series,
            name=label,
            marker_color=group_colors[label],
            hovertemplate=f"<b>{label}</b><br>Age: %{{x}}<br>%{{y:$,.0f}}<extra></extra>",
        ))

    # Taxes as negative bars
    if "total_tax" in ret_df.columns and ret_df["total_tax"].sum() > 0:
        fig.add_trace(go.Bar(
            x=ret_df["age"], y=-ret_df["total_tax"],
            name="Taxes",
            marker_color="#d62728",
            hovertemplate="<b>Taxes</b><br>Age: %{x}<br>%{y:$,.0f}<extra></extra>",
        ))

    # After-tax spending line
    if "after_tax_spending" in ret_df.columns:
        fig.add_trace(go.Scatter(
            x=ret_df["age"], y=ret_df["after_tax_spending"],
            name="After-Tax Spending",
            mode="lines+markers",
            line=dict(color="black", width=2, dash="dot"),
            hovertemplate="<b>After-Tax Spending</b><br>Age: %{x}<br>%{y:$,.0f}<extra></extra>",
        ))
        # Real-dollar overlay
        if inflation > 0:
            real_spend = ret_df["after_tax_spending"] / (1 + inflation) ** (ret_df["age"] - ret_age)
            fig.add_trace(go.Scatter(
                x=ret_df["age"], y=real_spend,
                name="Spending (today's $)",
                mode="lines",
                line=dict(color="gray", width=2, dash="dashdot"),
                hovertemplate="<b>Spending (today's $)</b><br>Age: %{x}<br>%{y:$,.0f}<extra></extra>",
            ))

    if cur_age > ret_age:
        fig.add_vline(x=cur_age, line_dash="dash", line_color="rgba(255,120,0,0.85)",
                      line_width=2, annotation_text=f"Age {cur_age} (now)",
                      annotation_position="top right")

    fig.update_layout(
        barmode="relative",
        xaxis_title="Age",
        yaxis_title="Amount ($)",
        yaxis_tickformat="$,.0f",
        hovermode="x unified",
        height=400,
        margin=dict(l=0, r=0, t=10, b=0),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        plot_bgcolor="white",
        paper_bgcolor="white",
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_simple_balance_chart(acc_df: pd.DataFrame, ret_df: pd.DataFrame,
                                  profile: dict, assumptions: dict,
                                  accounts_at_ret: list):
    """Stacked area of portfolio balance by account-type group — full timeline."""
    if acc_df.empty and ret_df.empty:
        return
    st.subheader("Portfolio Balance by Account Type")

    inflation = assumptions.get("inflation_rate", 0.025)
    ret_age = profile["retirement_age"]
    cur_age = profile["current_age"]

    type_to_bucket = {
        "traditional_401k": "pre_tax", "traditional_ira": "pre_tax",
        "roth_401k": "roth", "roth_ira": "roth", "hsa": "roth",
        "taxable": "taxable", "reit": "taxable",
        "bank": "cash",
        "rental_property": "real_estate",
    }
    bucket_label = {
        "pre_tax":     "Tax-Deferred (401k/IRA)",
        "roth":        "Roth",
        "taxable":     "Taxable",
        "cash":        "Bank / Cash",
        "real_estate": "Real Estate",
    }
    bucket_color = {
        "pre_tax":     "#4C72B0",
        "roth":        "#55A868",
        "taxable":     "#DD8452",
        "cash":        "#A0A0A0",
        "real_estate": "#8172B2",
    }
    bucket_fill = {
        "pre_tax":     "rgba(76,114,176,0.55)",
        "roth":        "rgba(85,168,104,0.55)",
        "taxable":     "rgba(221,132,82,0.55)",
        "cash":        "rgba(160,160,160,0.55)",
        "real_estate": "rgba(129,114,178,0.55)",
    }

    # Accumulation: aggregate acc_df by (age, bucket)
    acc_by_bucket: dict[str, dict[int, float]] = {}
    if not acc_df.empty:
        for _, row in acc_df.iterrows():
            b = type_to_bucket.get(row["account_type"])
            if b is None:
                continue
            age = int(row["age"])
            bucket = acc_by_bucket.setdefault(b, {})
            bucket[age] = bucket.get(age, 0.0) + float(row["balance"])

    # Retirement: map bal_ columns to buckets via accounts_at_ret
    ret_by_bucket: dict[str, dict[int, float]] = {}
    if not ret_df.empty and accounts_at_ret:
        name_to_bucket = {
            a["name"]: type_to_bucket.get(a["type"]) for a in accounts_at_ret
        }
        for a in accounts_at_ret:
            b = type_to_bucket.get(a["type"])
            if b is None:
                continue
            col = "bal_" + a["name"].replace(" ", "_")
            if col not in ret_df.columns:
                continue
            bucket = ret_by_bucket.setdefault(b, {})
            for _, row in ret_df.iterrows():
                age = int(row["age"])
                bucket[age] = bucket.get(age, 0.0) + float(row.get(col, 0.0))

    all_buckets = list(dict.fromkeys(
        b for b in ["pre_tax", "roth", "taxable", "cash", "real_estate"]
        if b in acc_by_bucket or b in ret_by_bucket
    ))
    if not all_buckets:
        return

    all_ages = sorted(
        {a for d in acc_by_bucket.values() for a in d}
        | {a for d in ret_by_bucket.values() for a in d}
    )

    fig = go.Figure()
    for b in all_buckets:
        acc_d = acc_by_bucket.get(b, {})
        ret_d = ret_by_bucket.get(b, {})
        vals = [acc_d.get(age, ret_d.get(age, 0.0)) for age in all_ages]
        if max(vals, default=0) < 1:
            continue
        fig.add_trace(go.Scatter(
            x=all_ages, y=vals,
            name=bucket_label[b],
            mode="lines",
            stackgroup="one",
            fillcolor=bucket_fill[b],
            line=dict(color=bucket_color[b], width=1),
            hovertemplate=f"<b>{bucket_label[b]}</b><br>Age: %{{x}}<br>%{{y:$,.0f}}<extra></extra>",
        ))

    # Real-dollar overlay on total portfolio
    if inflation > 0 and not ret_df.empty and "total_portfolio" in ret_df.columns:
        real_port = ret_df["total_portfolio"] / (1 + inflation) ** (ret_df["age"] - cur_age)
        fig.add_trace(go.Scatter(
            x=ret_df["age"], y=real_port,
            name="Portfolio (today's $)",
            mode="lines",
            line=dict(color="black", width=2, dash="dash"),
            hovertemplate="<b>Portfolio (today's $)</b><br>Age: %{x}<br>%{y:$,.0f}<extra></extra>",
        ))

    fig.add_vline(x=ret_age, line_dash="dot", line_color="#718096",
                  annotation_text=f"Retire ({ret_age})", annotation_position="top right")
    if cur_age > ret_age:
        fig.add_vline(x=cur_age, line_dash="dash", line_color="rgba(255,120,0,0.85)",
                      line_width=2, annotation_text=f"Age {cur_age} (now)",
                      annotation_position="top left")

    fig.update_layout(
        xaxis_title="Age",
        yaxis_title="Remaining Balance",
        yaxis_tickformat="$,.0f",
        hovermode="x unified",
        height=400,
        margin=dict(l=0, r=0, t=10, b=0),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        plot_bgcolor="white",
        paper_bgcolor="white",
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_levers(base_score: int, base_surplus: float, base_depletion, profile, w,
                   ret_df: pd.DataFrame | None = None, assumptions: dict | None = None):
    st.subheader("Move the Needle")
    st.caption("Adjust these sliders to see how small changes affect your score.")

    engine_mode = w.get("engine_spending_mode", "fixed")

    # Pre-compute year-1 spending in today's dollars for the SWR "spend less" lever
    year1_spending_base = None
    if engine_mode == "swr" and ret_df is not None and not ret_df.empty and assumptions is not None:
        yr1_nominal = float(ret_df.iloc[0]["after_tax_spending"])
        infl = assumptions.get("inflation_rate", 0.025)
        years_to_ret = max(0, profile["retirement_age"] - profile["current_age"])
        year1_spending_base = yr1_nominal / (1 + infl) ** years_to_ret if years_to_ret > 0 else yr1_nominal

    c1, c2, c3 = st.columns(3)
    extra_savings = c1.slider(
        "Save more per year ($)", 0, 10000, 0, 500, key="lever_savings",
        help="Additional annual retirement contribution"
    )
    ret_delta = c2.slider(
        "Retire later (years)", 0, 5, 0, 1, key="lever_retire",
        help="Delay retirement by this many years"
    )
    spend_label = "Spend less per year ($)" if engine_mode == "fixed" else "Reduce spending ($/yr vs SWR estimate)"
    spend_delta = c3.slider(
        spend_label, 0, 20000, 0, 1000, key="lever_spend",
        help="Reduce annual retirement spending by this amount" if engine_mode == "fixed" else
             "Reduce spending relative to the SWR estimate by switching to a fixed lower target"
    )

    if extra_savings > 0 or ret_delta > 0 or spend_delta > 0:
        profile_adj, assumptions_adj, accounts_adj, rc_adj = _build_simple_plan(
            w,
            extra_savings=float(extra_savings),
            retirement_age_delta=ret_delta,
            spending_delta=-float(spend_delta),
            year1_spending_base=year1_spending_base,
        )
        _, ret_df_adj, summary_adj, _ = _run_projection(profile_adj, assumptions_adj, accounts_adj, rc_adj)
        new_score, new_surplus = _compute_score(ret_df_adj, summary_adj, profile_adj)
        delta = new_score - base_score
        sign = "+" if delta >= 0 else ""

        bg, fg, label = _score_color(new_score)
        depl = summary_adj.get("portfolio_depleted_age")
        if depl:
            outcome = f"Portfolio runs out at age {depl}"
        elif new_surplus > 0:
            outcome = f"${new_surplus:,.0f} surplus at age {profile_adj['life_expectancy']}"
        else:
            outcome = f"Plan succeeds to age {profile_adj['life_expectancy']}"

        st.markdown(
            f"""<div style="background:{bg};border-radius:10px;padding:0.9rem 1.2rem;margin-top:0.5rem;">
            <span style="font-size:1.4rem;font-weight:800;color:{fg};">{min(new_score,100)}%</span>
            <span style="color:{fg};font-weight:600;margin-left:0.5rem;">{label}</span>
            <span style="color:{fg};margin-left:1rem;font-size:0.9rem;">
              ({sign}{delta} pts) &nbsp;·&nbsp; {outcome}
            </span>
            </div>""",
            unsafe_allow_html=True,
        )


def _render_assumptions_note(w, profile=None, accts_at_ret=None, assumptions=None):
    with st.expander("What assumptions did we use?"):
        rate = w.get("global_return_rate", _RETURN_BY_STYLE[w["investment_style"]])
        infl = w.get("inflation_rate", 0.025)
        pre_hc = w.get("pre_medicare_healthcare", 15000.0)
        post_hc = w.get("post_medicare_healthcare", 12000.0)
        state_tax = w.get("state_tax_rate", 0.045)
        strategy = w.get("withdrawal_strategy", "tax_efficient").replace("_", " ").title()
        engine_mode = w.get("engine_spending_mode", "fixed")
        swr = w.get("safe_withdrawal_rate", 0.04)
        spend_row = (
            f"| Spending method | Portfolio × {swr*100:.1f}% SWR (scales with balance) |"
            if engine_mode == "swr"
            else "| Spending method | Fixed dollar target (after-tax) |"
        )
        st.markdown(f"""
| Assumption | Value |
|---|---|
| Inflation rate | {infl*100:.1f}% |
| Investment return ({w['investment_style']}) | {rate*100:.1f}% nominal |
{spend_row}
| Pre-Medicare healthcare | ${pre_hc:,.0f}/yr |
| Post-Medicare healthcare | ${post_hc:,.0f}/yr |
| State tax rate | {state_tax*100:.1f}% |
| Withdrawal strategy | {strategy} |
| Social Security COLA | {infl*100:.1f}% annually |

These settings are carried over from your Advanced Mode configuration. Switch to **Advanced Mode** to adjust them.
        """)

    s = st.session_state
    with st.expander("MC diagnostic — why might Simple and Advanced differ?"):
        # ── Simplified MC parameters ──────────────────────────────────────────
        eq_vol   = s.get("mc_equity_vol",    16)
        bd_vol   = s.get("mc_bond_vol",       6)
        corr     = s.get("mc_eq_bond_corr",  10)
        raw_sp   = s.get("mc_stock_pct",     60)
        crashes  = s.get("mc_crashes",      False)
        n_trials = s.get("mc_n",           1000)
        w_mode   = s.get("mc_withdrawal_mode", "Constant Real")
        mc_model = s.get("mc_model", "CMA Log-Normal (Advanced)")

        simp_total = sum(a["balance"] for a in accts_at_ret) if accts_at_ret else 0.0
        adv_accts = s.get("accounts", [])
        adv_profile = s.get("profile", {})
        adv_assump  = s.get("assumptions", {})

        # Approximate advanced retirement balance by fast-forwarding if not already retired
        adv_ret_age = adv_profile.get("retirement_age", 65)
        adv_cur_age = adv_profile.get("current_age", 65)
        if adv_cur_age >= adv_ret_age:
            adv_total = sum(a.get("balance", 0) for a in adv_accts)
        else:
            # project_accumulation already ran for advanced — re-use its result via ret_df if available
            # Fall back to simple FV estimate for the diagnostic
            years = adv_ret_age - adv_cur_age
            r = adv_assump.get("retirement_return_rate", 0.07)
            adv_total = sum(
                a.get("balance", 0) * (1 + r) ** years
                + a.get("annual_contribution", 0) * (((1 + r) ** years - 1) / r if r > 1e-6 else years)
                for a in adv_accts if a.get("type") != "rental_property"
            )

        simp_swr    = assumptions.get("safe_withdrawal_rate", 0.04) if assumptions else swr
        simp_spend_mode = assumptions.get("spending_mode", "?") if assumptions else "?"
        simp_initial_spend = (
            simp_total * simp_swr if simp_spend_mode == "swr"
            else (assumptions or {}).get("annual_spending_target", 0)
        )

        adv_spend_mode = adv_assump.get("spending_mode", "swr")
        adv_swr_val    = adv_assump.get("safe_withdrawal_rate", 0.04)
        adv_initial_spend = (
            adv_total * adv_swr_val if adv_spend_mode == "swr"
            else adv_assump.get("annual_spending_target", 0)
        )

        st.markdown(f"""
**Simple MC inputs (this run):**

| Parameter | Simple | Advanced session |
|---|---|---|
| Spending mode | {simp_spend_mode} | {adv_spend_mode} |
| Portfolio at retirement | ${simp_total:,.0f} | ~${adv_total:,.0f} *(est)* |
| Initial spending | ${simp_initial_spend:,.0f}/yr | ${adv_initial_spend:,.0f}/yr |
| SWR | {simp_swr*100:.1f}% | {adv_swr_val*100:.1f}% |
| Return rate | {rate*100:.1f}% | {adv_assump.get("retirement_return_rate", 0.07)*100:.1f}% |
| SS benefit (today's $) | ${(profile or {{}}).get("social_security_benefit", 0):,.0f} | ${adv_profile.get("social_security_benefit", 0):,.0f} |
| Pre-Medicare healthcare | ${pre_hc:,.0f} | ${adv_profile.get("pre_medicare_healthcare", 15000):,.0f} |

**Advanced MC tab settings (shared):**
Model: **{mc_model}** · Equity vol **{eq_vol}%** · Bond vol **{bd_vol}%** · Corr **{corr}%** · Stock **{raw_sp}%** · {n_trials:,} trials · {w_mode} · Crashes: **{"on" if crashes else "off"}**

*Note: Advanced MC uses no fixed seed so results vary by ±1–2% per run.*
""")
        if adv_spend_mode != simp_spend_mode:
            st.warning(f"Spending mode mismatch: Simple uses **{simp_spend_mode}**, Advanced uses **{adv_spend_mode}**. This is the most likely cause of a gap.")
        if crashes:
            st.warning("Advanced MC has **random crashes enabled** — this significantly lowers advanced success rate vs simple (which never uses crashes).")
        if mc_model != "CMA Log-Normal (Advanced)":
            st.warning(f"Advanced MC model is **{mc_model}** — Simple always uses CMA Log-Normal. Re-run Advanced MC with CMA Log-Normal to compare apples-to-apples.")


# ---------------------------------------------------------------------------
# Scenario save / load
# ---------------------------------------------------------------------------

def _render_scenario_controls(w: dict, profile: dict, assumptions: dict,
                               accounts: list, rc: dict):
    """Compact save/load bar shown at the top of the results page."""
    saved = list_scenarios()
    c_name, c_save, c_sel, c_load, c_del = st.columns([3, 1, 3, 1, 1])

    name = c_name.text_input(
        "Scenario name", w.get("scenario_name", "My Plan"),
        label_visibility="collapsed", key="simp_sc_name",
        placeholder="Scenario name…",
    )
    w["scenario_name"] = name

    if c_save.button("💾 Save", key="simp_sc_save", use_container_width=True):
        try:
            save_scenario(name, profile, assumptions, accounts, rc)
            set_last_used_scenario(name)
            st.toast(f"Saved '{name}'", icon="✅")
        except Exception as e:
            st.error(str(e))

    if saved:
        selected = c_sel.selectbox(
            "Load", saved, key="simp_sc_sel", label_visibility="collapsed"
        )
        if c_load.button("Load", key="simp_sc_load", use_container_width=True):
            try:
                data = load_scenario(selected)
                st.session_state.profile = data["profile"]
                st.session_state.assumptions = data["assumptions"]
                st.session_state.accounts = data["accounts"]
                st.session_state.roth_conversion = data.get("roth_conversion", {})
                st.session_state.wizard_needs_sync = True
                set_last_used_scenario(selected)
                st.rerun()
            except Exception as e:
                st.error(str(e))
        if c_del.button("🗑", key="simp_sc_del", use_container_width=True,
                        help="Delete selected scenario"):
            delete_scenario(selected)
            st.rerun()
    else:
        c_sel.caption("No saved scenarios")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_simplified_mode():
    _init_wizard()

    # Progress bar is always visible once data exists
    _progress_bar(st.session_state.wizard_step)

    if not st.session_state.wizard_complete:
        _show_wizard()
        return

    w = st.session_state.wizard
    profile, assumptions, accounts, rc = _build_simple_plan(w)
    acc_df, ret_df, summary, accts_at_ret = _run_projection(profile, assumptions, accounts, rc)

    if "error" in summary:
        st.error(f"Projection error: {summary['error']}")
        if st.button("← Back to Wizard"):
            st.session_state.wizard_complete = False
            st.session_state.wizard_step = 1
            st.rerun()
        return

    # ── Scenario save / load ────────────────────────────────────────────────
    _render_scenario_controls(w, profile, assumptions, accounts, rc)

    st.divider()

    with st.spinner("Running market simulations…"):
        mc_result = _run_mc(accts_at_ret, profile, assumptions, w.get("investment_style", "Moderate"))

    score, surplus = _compute_score(ret_df, summary, profile)
    depletion = summary.get("portfolio_depleted_age")

    # ── Score card ─────────────────────────────────────────────────────────
    _render_score_card(score, surplus, profile, depletion, mc_result)

    st.divider()

    # ── Spending summary (metrics only) ────────────────────────────────────
    _render_spending_summary(ret_df, profile, assumptions)

    st.divider()

    # ── Income sources chart (grouped, year by year) ───────────────────────
    _render_simple_income_chart(ret_df, profile, assumptions)

    st.divider()

    # ── Balance chart (by account type, full timeline) ─────────────────────
    _render_simple_balance_chart(acc_df, ret_df, profile, assumptions, accts_at_ret)

    st.divider()

    # ── Levers ────────────────────────────────────────────────────────────
    _render_levers(score, surplus, depletion, profile, w, ret_df=ret_df, assumptions=assumptions)

    st.divider()

    # ── Advanced mode bridge ────────────────────────────────────────────────
    _, c_adv = st.columns([1, 1])
    with c_adv:
        if st.button("Switch to Advanced Mode →", use_container_width=True, type="primary"):
            _sync_to_advanced(profile, assumptions, accounts, rc)
            st.session_state.ui_mode = "advanced"
            st.rerun()

    _render_assumptions_note(w, profile=profile, accts_at_ret=accts_at_ret, assumptions=assumptions)


def _sync_to_advanced(profile, assumptions, accounts, rc):
    """Copy the simplified plan into the main session state for advanced mode."""
    import copy as _copy
    st.session_state.profile = _copy.deepcopy(profile)
    st.session_state.assumptions = _copy.deepcopy(assumptions)
    st.session_state.accounts = _copy.deepcopy(accounts)
    st.session_state.roth_conversion = _copy.deepcopy(rc)
    # Clear widget keys so advanced mode re-seeds from the new values
    for k in list(st.session_state.keys()):
        if k.startswith(("p_", "a_", "rc_")):
            del st.session_state[k]
    # Seed profile widget keys
    p = profile
    st.session_state["p_age"] = int(p["current_age"])
    st.session_state["p_ret"] = int(p["retirement_age"])
    st.session_state["p_le"] = int(p["life_expectancy"])
    st.session_state["p_income"] = int(p.get("current_income", 0) or 0)
    st.session_state["p_ss"] = int(p.get("social_security_benefit", 0))
    st.session_state["p_ss_age"] = int(p.get("social_security_start_age", 67))
    st.session_state["p_hc_pre"] = int(p.get("pre_medicare_healthcare", 15000))
    st.session_state["p_hc_post"] = int(p.get("post_medicare_healthcare", 12000))
    # Seed assumptions widget keys
    a = assumptions
    st.session_state["a_inf"] = float(round(a.get("inflation_rate", 0.025) * 100, 1))
    st.session_state["a_bracket_inf"] = float(round(a.get("bracket_inflation_rate", 0.025) * 100, 1))
    st.session_state["a_ret"] = float(round(a.get("retirement_return_rate", 0.07) * 100, 1))
    st.session_state["a_swr"] = float(round(a.get("safe_withdrawal_rate", 0.04) * 100, 1))
    st.session_state["a_spend_mode"] = a.get("spending_mode", "swr")
    st.session_state["a_spend_target"] = int(a.get("annual_spending_target", 80000))
    st.session_state["a_withdraw_strat"] = a.get("withdrawal_strategy", "tax_efficient")
    # Seed per-account widget keys using actual account settings
    for acct in accounts:
        aid = acct["id"]
        st.session_state[f"chk_global_{aid}"] = bool(acct.get("use_global_return_rate", True))
        st.session_state[f"a_ret_{aid}"] = round(acct.get("return_rate", 0.07) * 100, 4)
        st.session_state[f"a_cgr_{aid}"] = round(acct.get("contribution_growth_rate", 0.0) * 100, 4)
        st.session_state[f"a_emp_{aid}"] = round(acct.get("employer_match_percent", 0.0) * 100, 4)
        st.session_state[f"a_empl_{aid}"] = int(acct.get("employer_match_limit", 0))
        st.session_state[f"a_wlast_{aid}"] = acct.get("withdraw_priority", "normal") == "last"
        st.session_state[f"a_buf_{aid}"] = int(acct.get("bank_buffer", 0))
