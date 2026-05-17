import uuid
import streamlit as st
import pandas as pd

from projections import project_accumulation
from withdrawals import simulate_retirement
from charts import (
    chart_accumulation,
    chart_composition_at_retirement,
    chart_drawdown,
    chart_annual_income,
    chart_spending_coverage,
    chart_tax_burden,
)
from scenarios import list_scenarios, latest_scenario, save_scenario, load_scenario, delete_scenario
from constants import RMD_START_AGE

st.set_page_config(page_title="Retirement Planner", layout="wide")

# ---------------------------------------------------------------------------
# Default state
# ---------------------------------------------------------------------------

DEFAULT_PROFILE = {
    "current_age": 35,
    "retirement_age": 65,
    "life_expectancy": 90,
    "filing_status": "married_filing_jointly",
    "state": "california",
    "state_tax_rate": 0.0,
    "current_income": 100000.0,
    "social_security_benefit": 24000.0,
    "social_security_start_age": 67,
    "spouse_age": 35,
    "spouse_retirement_age": 65,
    "spouse_ss_benefit": 18000.0,
    "spouse_ss_start_age": 67,
    "survivor_spending_reduction": 0.25,
    "pre_medicare_healthcare": 15000.0,
    "post_medicare_healthcare": 5000.0,
}

DEFAULT_ASSUMPTIONS = {
    "inflation_rate": 0.03,
    "safe_withdrawal_rate": 0.04,
    "retirement_return_rate": 0.05,
    "spending_mode": "swr",
    "annual_spending_target": 80000.0,
}

DEFAULT_ACCOUNTS = [
    {
        "id": "acc1",
        "name": "401(k)",
        "type": "traditional_401k",
        "balance": 150000.0,
        "basis": 0.0,
        "annual_contribution": 15000.0,
        "contribution_growth_rate": 0.03,
        "return_rate": 0.07,
        "employer_match_percent": 0.50,
        "employer_match_limit": 3000.0,
        "qualified_dividend_yield": 0.0,
        "ordinary_income_yield": 0.0,
        "net_annual_rental_income": 0.0,
    },
    {
        "id": "acc2",
        "name": "Roth IRA",
        "type": "roth_ira",
        "balance": 40000.0,
        "basis": 40000.0,
        "annual_contribution": 7000.0,
        "contribution_growth_rate": 0.0,
        "return_rate": 0.07,
        "employer_match_percent": 0.0,
        "employer_match_limit": 0.0,
        "qualified_dividend_yield": 0.0,
        "ordinary_income_yield": 0.0,
        "net_annual_rental_income": 0.0,
    },
]

DEFAULT_ROTH_CONVERSION = {
    "enabled": False,
    "strategy": "fill_to_bracket",
    "target_bracket": 0.12,
    "fixed_amount": 10000.0,
    "start_age": 65,
    "end_age": 72,
    "source_account_ids": [],   # list of traditional account IDs to convert from
    "destination_account_id": "acc2",
    "allow_during_accumulation": False,
}


def _init_state():
    if "profile" not in st.session_state:
        # Auto-load the most recently modified scenario on first run
        recent = latest_scenario()
        if recent:
            try:
                data = load_scenario(recent)
                st.session_state.profile = data["profile"]
                st.session_state.assumptions = data["assumptions"]
                import copy
                st.session_state.accounts = copy.deepcopy(data["accounts"])
                st.session_state.roth_conversion = data.get("roth_conversion", DEFAULT_ROTH_CONVERSION.copy())
                st.session_state.spending_overrides = {}
                return
            except Exception:
                pass
        st.session_state.profile = DEFAULT_PROFILE.copy()
    if "assumptions" not in st.session_state:
        st.session_state.assumptions = DEFAULT_ASSUMPTIONS.copy()
    if "accounts" not in st.session_state:
        import copy
        st.session_state.accounts = copy.deepcopy(DEFAULT_ACCOUNTS)
    if "roth_conversion" not in st.session_state:
        st.session_state.roth_conversion = DEFAULT_ROTH_CONVERSION.copy()
    if "spending_overrides" not in st.session_state:
        st.session_state.spending_overrides = {}
    # Set chk_global_* keys from account dicts so the checkbox renders correctly.
    # Uses chk_global_ prefix (not a_*) so these keys are never deleted by
    # _apply_pending_load's deletion loop, avoiding the delete-then-set problem.
    for _a in st.session_state.accounts:
        key = f"chk_global_{_a['id']}"
        if key not in st.session_state:
            st.session_state[key] = bool(_a.get("use_global_return_rate", True))


def _apply_pending_load():
    """
    Apply a scenario load that was queued on the previous render.
    Must run before any sidebar widgets are created so that deleting
    widget keys (p_*, a_*, rc_*) actually takes effect — Streamlit
    won't let you delete a key while the widget is still rendered.
    """
    if "_pending_load" not in st.session_state:
        return
    data = st.session_state.pop("_pending_load")
    for k in list(st.session_state.keys()):
        if k.startswith(("p_", "a_", "rc_")):
            del st.session_state[k]
    st.session_state.profile = data["profile"]
    st.session_state.assumptions = data["assumptions"]
    st.session_state.accounts = data["accounts"]
    for _a in st.session_state.accounts:
        st.session_state[f"chk_global_{_a['id']}"] = bool(_a.get("use_global_return_rate", True))
    rc = data.get("roth_conversion", DEFAULT_ROTH_CONVERSION.copy())
    # Migrate old single-source format → list format
    if "source_account_id" in rc and "source_account_ids" not in rc:
        old_id = rc.pop("source_account_id", None)
        rc["source_account_ids"] = [old_id] if old_id else []
    st.session_state.roth_conversion = rc
    st.session_state.spending_overrides = {}
    # Update the scenario name text input to match the loaded scenario
    st.session_state["sc_name"] = data.get("scenario_name", "My Scenario")


_init_state()
_apply_pending_load()

# ---------------------------------------------------------------------------
# Sidebar helpers
# ---------------------------------------------------------------------------

ACCOUNT_TYPES = {
    "Traditional 401(k)": "traditional_401k",
    "Roth 401(k)":        "roth_401k",
    "Traditional IRA":    "traditional_ira",
    "Roth IRA":           "roth_ira",
    "Taxable Brokerage":  "taxable",
    "HSA":                "hsa",
    "REIT (Taxable)":     "reit",
    "Rental Property":    "rental_property",
    "Bank Account / Cash": "bank",
}
ACCOUNT_TYPE_LABELS = {v: k for k, v in ACCOUNT_TYPES.items()}
FILING_STATUS_LABELS = {
    "single": "Single",
    "married_filing_jointly": "Married Filing Jointly",
}


def _pct(val: float) -> float:
    return round(val * 100, 4)


def _dec(pct: float) -> float:
    return pct / 100.0


# ---------------------------------------------------------------------------
# Sidebar — Profile
# ---------------------------------------------------------------------------

def sidebar_profile():
    p = st.session_state.profile
    with st.sidebar.expander("👤 Profile", expanded=True):
        p["current_age"] = st.number_input("Current Age", 18, 80, p["current_age"], key="p_age")
        p["retirement_age"] = st.number_input("Retirement Age", p["current_age"] + 1, 85, p["retirement_age"], key="p_ret")
        p["life_expectancy"] = st.number_input("Life Expectancy", p["retirement_age"] + 1, 110, p["life_expectancy"], key="p_le")
        p["filing_status"] = st.selectbox(
            "Filing Status",
            options=list(FILING_STATUS_LABELS.keys()),
            format_func=lambda k: FILING_STATUS_LABELS[k],
            index=list(FILING_STATUS_LABELS.keys()).index(p["filing_status"]),
            key="p_fs",
        )
        state_options = {"california": "California (progressive brackets)", "other": "Other state (flat rate)"}
        p["state"] = st.selectbox(
            "State",
            options=list(state_options.keys()),
            format_func=lambda k: state_options[k],
            index=0 if p.get("state", "california") == "california" else 1,
            key="p_state",
        )
        if p["state"] == "other":
            p["state_tax_rate"] = _dec(st.number_input("State Tax Rate (%)", 0.0, 15.0, _pct(p.get("state_tax_rate", 0.05)), 0.1, key="p_state_rate"))
        else:
            p["state_tax_rate"] = 0.0
        p["current_income"] = st.number_input("Current Annual Income ($)", 0, 1000000, int(p.get("current_income", 0) or 0), 1000, key="p_income")

        st.markdown("**Social Security**")
        p["social_security_benefit"] = st.number_input("Your SS Benefit ($/yr today's $)", 0, 60000, int(p.get("social_security_benefit", 0)), 500, key="p_ss")
        p["social_security_start_age"] = st.number_input("Your SS Start Age", 62, 70, p.get("social_security_start_age", 67), key="p_ss_age")

        if p["filing_status"] == "married_filing_jointly":
            st.markdown("**Spouse**")
            p["spouse_age"] = st.number_input("Spouse Current Age", 18, 80, p.get("spouse_age", p["current_age"]), key="p_sp_age")
            p["spouse_ss_benefit"] = st.number_input("Spouse SS Benefit ($/yr today's $)", 0, 60000, int(p.get("spouse_ss_benefit", 0)), 500, key="p_sp_ss")
            p["spouse_ss_start_age"] = st.number_input("Spouse SS Start Age", 62, 70, p.get("spouse_ss_start_age", 67), key="p_sp_ss_age")
            p["survivor_spending_reduction"] = _dec(st.number_input(
                "Survivor Spending Reduction (%)", 0.0, 50.0, _pct(p.get("survivor_spending_reduction", 0.25)), 1.0, key="p_surv"))

        st.markdown("**Healthcare**")
        p["pre_medicare_healthcare"] = st.number_input("Pre-Medicare Annual Cost ($)", 0, 50000, int(p.get("pre_medicare_healthcare", 15000)), 500, key="p_hc_pre")
        p["post_medicare_healthcare"] = st.number_input("Post-Medicare Annual Cost ($)", 0, 30000, int(p.get("post_medicare_healthcare", 5000)), 500, key="p_hc_post")


# ---------------------------------------------------------------------------
# Sidebar — Assumptions
# ---------------------------------------------------------------------------

def sidebar_assumptions():
    a = st.session_state.assumptions
    with st.sidebar.expander("📊 Assumptions", expanded=False):
        a["inflation_rate"] = _dec(st.number_input("Inflation Rate (%)", 0.0, 15.0, _pct(a["inflation_rate"]), 0.1, key="a_inf"))
        a["retirement_return_rate"] = _dec(st.number_input("Retirement Return Rate — capital appreciation (%)", 0.0, 15.0, _pct(a["retirement_return_rate"]), 0.1, key="a_ret"))
        st.caption("Applied to accounts set to 'use global rate'. Set this to total return minus dividend yield (e.g. 5% if portfolio returns 6.5% total and pays 1.5% dividends).")

        st.markdown("**Income Needed in Retirement**")
        a["spending_mode"] = st.radio(
            "Spending target method",
            ["swr", "fixed"],
            format_func=lambda x: "% of Portfolio (SWR)" if x == "swr" else "Fixed Dollar Amount",
            index=0 if a.get("spending_mode", "swr") == "swr" else 1,
            key="a_spend_mode",
        )
        if a["spending_mode"] == "swr":
            a["safe_withdrawal_rate"] = _dec(st.number_input("Safe Withdrawal Rate (%)", 1.0, 10.0, _pct(a.get("safe_withdrawal_rate", 0.04)), 0.1, key="a_swr"))
            st.caption("Spending = SWR × portfolio at retirement, inflated annually. Healthcare added on top.")
        else:
            a["annual_spending_target"] = float(st.number_input(
                "After-Tax Annual Spending (today's $)", 10000, 1000000,
                int(a.get("annual_spending_target", 80000)), 1000, key="a_spend_target",
            ))
            st.caption("Desired after-tax spending in today's dollars, excluding healthcare. Inflated to retirement date then annually. The simulation grosses up withdrawals to cover taxes.")


# ---------------------------------------------------------------------------
# Sidebar — Accounts
# ---------------------------------------------------------------------------

def sidebar_accounts():
    with st.sidebar.expander("🏦 Accounts", expanded=True):
        accts = st.session_state.accounts
        for i, a in enumerate(accts):
            with st.expander(f"{a['name']} ({ACCOUNT_TYPE_LABELS.get(a['type'], a['type'])})", expanded=False):
                a["name"] = st.text_input("Name", a["name"], key=f"a_name_{a['id']}")
                type_keys = list(ACCOUNT_TYPES.keys())
                type_vals = list(ACCOUNT_TYPES.values())
                cur_idx = type_vals.index(a["type"]) if a["type"] in type_vals else 0
                a["type"] = ACCOUNT_TYPES[st.selectbox("Type", type_keys, index=cur_idx, key=f"a_type_{a['id']}")]

                a["balance"] = float(st.number_input("Current Balance ($)", 0, 10000000, int(a["balance"]), 1000, key=f"a_bal_{a['id']}"))

                always_own_rate = a["type"] in {"rental_property", "bank"}
                if always_own_rate:
                    a["return_rate"] = _dec(st.number_input("Return / Appreciation Rate (%)", 0.0, 20.0, _pct(a["return_rate"]), 0.1, key=f"a_ret_{a['id']}"))
                else:
                    a["return_rate"] = _dec(st.number_input("Return Rate — accumulation (%)", 0.0, 20.0, _pct(a["return_rate"]), 0.1, key=f"a_ret_{a['id']}"))
                    use_global = st.checkbox(
                        "Use global retirement return rate",
                        value=a.get("use_global_return_rate", True),
                        key=f"chk_global_{a['id']}",
                    )
                    a["use_global_return_rate"] = use_global
                    global_ret = st.session_state.assumptions.get("retirement_return_rate", 0.05)
                    if use_global:
                        st.caption(f"Retirement growth: {_pct(global_ret):.1f}% (global rate)")
                    else:
                        st.caption(f"Retirement growth: {_pct(a['return_rate']):.1f}% (this account's rate)")

                if a["type"] not in {"rental_property", "reit"}:
                    a["annual_contribution"] = float(st.number_input("Annual Contribution ($)", 0, 100000, int(a.get("annual_contribution", 0)), 500, key=f"a_contrib_{a['id']}"))
                    a["contribution_growth_rate"] = _dec(st.number_input("Contribution Growth (%/yr)", 0.0, 10.0, _pct(a.get("contribution_growth_rate", 0.0)), 0.1, key=f"a_cgr_{a['id']}"))

                if a["type"] in {"traditional_401k", "roth_401k"}:
                    a["employer_match_percent"] = _dec(st.number_input("Employer Match (%)", 0.0, 100.0, _pct(a.get("employer_match_percent", 0.0)), 1.0, key=f"a_emp_{a['id']}"))
                    a["employer_match_limit"] = float(st.number_input("Employer Match Limit ($/yr)", 0, 20000, int(a.get("employer_match_limit", 0)), 500, key=f"a_empl_{a['id']}"))

                if a["type"] in {"taxable", "reit"}:
                    a["basis"] = float(st.number_input("Cost Basis ($)", 0, 10000000, int(a.get("basis", a["balance"] * 0.5)), 1000, key=f"a_basis_{a['id']}"))
                    a["qualified_dividend_yield"] = _dec(st.number_input("Qualified Dividend Yield (%)", 0.0, 10.0, _pct(a.get("qualified_dividend_yield", 0.015 if a["type"] == "taxable" else 0.0)), 0.1, key=f"a_qdy_{a['id']}"))
                    a["ordinary_income_yield"] = _dec(st.number_input("Ordinary Income Yield (%)", 0.0, 10.0, _pct(a.get("ordinary_income_yield", 0.005 if a["type"] == "taxable" else 0.04)), 0.1, key=f"a_oiy_{a['id']}"))

                if a["type"] == "rental_property":
                    a["basis"] = float(st.number_input("Cost Basis ($)", 0, 10000000, int(a.get("basis", a["balance"] * 0.5)), 1000, key=f"a_basis_{a['id']}"))
                    a["net_annual_rental_income"] = float(st.number_input("Net Annual Rental Income ($)", 0, 500000, int(a.get("net_annual_rental_income", 0)), 500, key=f"a_rent_{a['id']}"))

                if st.button("Remove Account", key=f"a_del_{a['id']}"):
                    accts.pop(i)
                    st.rerun()

        if st.button("➕ Add Account"):
            accts.append({
                "id": str(uuid.uuid4())[:8],
                "name": "New Account",
                "type": "taxable",
                "balance": 0.0,
                "basis": 0.0,
                "annual_contribution": 0.0,
                "contribution_growth_rate": 0.0,
                "return_rate": 0.07,
                "use_global_return_rate": True,
                "employer_match_percent": 0.0,
                "employer_match_limit": 0.0,
                "qualified_dividend_yield": 0.015,
                "ordinary_income_yield": 0.005,
                "net_annual_rental_income": 0.0,
            })
            st.rerun()


# ---------------------------------------------------------------------------
# Sidebar — Roth Conversion
# ---------------------------------------------------------------------------

def sidebar_roth_conversion():
    rc = st.session_state.roth_conversion
    p = st.session_state.profile
    accts = st.session_state.accounts
    with st.sidebar.expander("🔄 Roth Conversion", expanded=False):
        rc["enabled"] = st.checkbox("Enable Roth Conversion Strategy", rc.get("enabled", False), key="rc_en")
        if rc["enabled"]:
            rc["strategy"] = st.radio(
                "Strategy",
                ["fill_to_bracket", "fixed_amount"],
                format_func=lambda x: "Fill to Bracket" if x == "fill_to_bracket" else "Fixed Amount",
                index=0 if rc.get("strategy") == "fill_to_bracket" else 1,
                key="rc_strat",
            )
            if rc["strategy"] == "fill_to_bracket":
                bracket_options = {0.10: "10%", 0.12: "12%", 0.22: "22%", 0.24: "24%"}
                rc["target_bracket"] = st.selectbox(
                    "Fill up to bracket",
                    options=list(bracket_options.keys()),
                    format_func=lambda k: bracket_options[k],
                    index=list(bracket_options.keys()).index(rc.get("target_bracket", 0.12)),
                    key="rc_bracket",
                )
            else:
                rc["fixed_amount"] = float(st.number_input("Annual Conversion ($)", 0, 500000, int(rc.get("fixed_amount", 10000)), 1000, key="rc_fixed"))

            rc["start_age"] = st.number_input("Conversion Start Age", p["retirement_age"], 80, rc.get("start_age", p["retirement_age"]), key="rc_start")
            rc["end_age"] = st.number_input("Conversion End Age", rc["start_age"], 85, rc.get("end_age", min(p.get("social_security_start_age", 67) - 1, RMD_START_AGE - 1)), key="rc_end")

            trad_accts = [a for a in accts if a["type"] in {"traditional_401k", "traditional_ira"}]
            roth_accts = [a for a in accts if a["type"] in {"roth_401k", "roth_ira"}]

            if trad_accts:
                st.markdown("**Convert From** (select one or more)")
                # Default: all traditional accounts selected if list is empty
                saved_ids = set(rc.get("source_account_ids") or [a["id"] for a in trad_accts])
                new_src_ids = []
                for ta in trad_accts:
                    if st.checkbox(ta["name"], value=ta["id"] in saved_ids, key=f"rc_src_{ta['id']}"):
                        new_src_ids.append(ta["id"])
                rc["source_account_ids"] = new_src_ids

            if roth_accts:
                dst_names = [a["name"] for a in roth_accts]
                dst_ids = [a["id"] for a in roth_accts]
                cur_dst = dst_ids.index(rc.get("destination_account_id", dst_ids[0])) if rc.get("destination_account_id") in dst_ids else 0
                rc["destination_account_id"] = dst_ids[st.selectbox("Convert Into", range(len(dst_names)), format_func=lambda i: dst_names[i], index=cur_dst, key="rc_dst")]


# ---------------------------------------------------------------------------
# Sidebar — Scenario save/load
# ---------------------------------------------------------------------------

def sidebar_scenarios():
    with st.sidebar.expander("💾 Scenarios", expanded=False):
        name = st.text_input("Scenario Name", "My Scenario", key="sc_name")
        if st.button("Save", key="sc_save"):
            try:
                # sidebar_roth_conversion() always runs before this handler and
                # writes widget return values directly into st.session_state.roth_conversion
                # via "rc[field] = widget()" assignments — that dict is authoritative.
                # We only need to fix up the two fields that require index→ID translation
                # (rc_dst stores a list index, not an account ID) and the checkbox-derived
                # source list (those keys are individually keyed per account).
                rc = st.session_state.roth_conversion
                _trad = [a for a in st.session_state.accounts
                         if a["type"] in {"traditional_401k", "traditional_ira"}]
                if any(f"rc_src_{a['id']}" in st.session_state for a in _trad):
                    rc["source_account_ids"] = [
                        a["id"] for a in _trad
                        if st.session_state.get(f"rc_src_{a['id']}", False)
                    ]
                _roth = [a for a in st.session_state.accounts
                         if a["type"] in {"roth_401k", "roth_ira"}]
                if "rc_dst" in st.session_state and _roth:
                    idx = st.session_state["rc_dst"]
                    if 0 <= idx < len(_roth):
                        rc["destination_account_id"] = _roth[idx]["id"]
                # Sync all account widget values explicitly — widgets inside
                # collapsed expanders may not have run, so the dict could be stale.
                for a in st.session_state.accounts:
                    aid = a["id"]
                    s = st.session_state
                    if f"a_name_{aid}" in s:
                        a["name"] = s[f"a_name_{aid}"]
                    if f"a_type_{aid}" in s:
                        a["type"] = ACCOUNT_TYPES.get(s[f"a_type_{aid}"], a["type"])
                    if f"a_bal_{aid}" in s:
                        a["balance"] = float(s[f"a_bal_{aid}"])
                    if f"a_ret_{aid}" in s:
                        a["return_rate"] = _dec(s[f"a_ret_{aid}"])
                    if f"chk_global_{aid}" in s:
                        a["use_global_return_rate"] = bool(s[f"chk_global_{aid}"])
                    if f"a_contrib_{aid}" in s:
                        a["annual_contribution"] = float(s[f"a_contrib_{aid}"])
                    if f"a_cgr_{aid}" in s:
                        a["contribution_growth_rate"] = _dec(s[f"a_cgr_{aid}"])
                    if f"a_emp_{aid}" in s:
                        a["employer_match_percent"] = _dec(s[f"a_emp_{aid}"])
                    if f"a_empl_{aid}" in s:
                        a["employer_match_limit"] = float(s[f"a_empl_{aid}"])
                    if f"a_basis_{aid}" in s:
                        a["basis"] = float(s[f"a_basis_{aid}"])
                    if f"a_qdy_{aid}" in s:
                        a["qualified_dividend_yield"] = _dec(s[f"a_qdy_{aid}"])
                    if f"a_oiy_{aid}" in s:
                        a["ordinary_income_yield"] = _dec(s[f"a_oiy_{aid}"])
                    if f"a_rent_{aid}" in s:
                        a["net_annual_rental_income"] = float(s[f"a_rent_{aid}"])
                save_scenario(
                    name,
                    st.session_state.profile,
                    st.session_state.assumptions,
                    st.session_state.accounts,
                    st.session_state.roth_conversion,
                )
                st.success(f"Saved '{name}'")
            except Exception as e:
                st.error(str(e))

        saved = list_scenarios()
        if saved:
            selected = st.selectbox("Load Scenario", saved, key="sc_sel")
            col3, col4 = st.columns(2)
            with col3:
                if st.button("Load", key="sc_load"):
                    try:
                        st.session_state._pending_load = load_scenario(selected)
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))
            with col4:
                if st.button("Delete", key="sc_del"):
                    delete_scenario(selected)
                    st.rerun()


# ---------------------------------------------------------------------------
# Main layout
# ---------------------------------------------------------------------------

def main():
    st.title("Retirement Planner")
    st.caption("Model investment accounts, project growth, and optimize tax-efficient withdrawals.")

    # Sidebar
    sidebar_profile()
    sidebar_assumptions()
    sidebar_accounts()
    sidebar_roth_conversion()
    sidebar_scenarios()

    profile = st.session_state.profile
    assumptions = st.session_state.assumptions
    accounts = st.session_state.accounts
    roth_conversion = st.session_state.roth_conversion

    spending_overrides = st.session_state.spending_overrides

    if not accounts:
        st.warning("Add at least one account to get started.")
        return

    # Run calculations
    try:
        acc_df, accounts_at_retirement = project_accumulation(accounts, profile, assumptions)

        # Stamp use_global_return_rate from session_state directly onto accounts_at_retirement.
        # The deep copy inside project_accumulation drops any field set after the deep copy,
        # so we re-apply it here before simulate_retirement runs.
        rate_prefs = {a["id"]: a.get("use_global_return_rate", True) for a in st.session_state.accounts}
        for a in accounts_at_retirement:
            a["use_global_return_rate"] = rate_prefs.get(a["id"], True)

        ret_df, summary = simulate_retirement(
            accounts_at_retirement, profile, assumptions, roth_conversion, spending_overrides,
        )
    except Exception as e:
        st.error(f"Calculation error: {e}")
        raise

    # ---------------------------------------------------------------------------
    # Summary cards
    # ---------------------------------------------------------------------------
    total_at_retirement = sum(a["balance"] for a in accounts_at_retirement)
    pre_tax_total = sum(a["balance"] for a in accounts_at_retirement if a["type"] in {"traditional_401k", "traditional_ira"})
    roth_total = sum(a["balance"] for a in accounts_at_retirement if a["type"] in {"roth_401k", "roth_ira", "hsa"})
    taxable_total = total_at_retirement - pre_tax_total - roth_total

    depletion = summary["portfolio_depleted_age"]
    longevity_str = f"Age {depletion}" if depletion else f"Lasts to age {profile['life_expectancy']}+"

    fixed_net_mode = assumptions.get("spending_mode") == "fixed"
    if fixed_net_mode and not ret_df.empty:
        annual_withdrawal_label = "After-Tax Spending Target (yr 1)"
        annual_withdrawal = ret_df["net_spending_target"].iloc[0]
    else:
        annual_withdrawal_label = "Annual Withdrawal Target (yr 1)"
        annual_withdrawal = ret_df["spending_target"].iloc[0] if not ret_df.empty else 0

    st.subheader("Summary")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Portfolio at Retirement", f"${total_at_retirement:,.0f}")
    c2.metric("Pre-Tax", f"${pre_tax_total:,.0f}")
    c3.metric("Roth / Tax-Free", f"${roth_total:,.0f}")
    c4.metric("Taxable / Real Estate", f"${taxable_total:,.0f}")
    c5.metric("Portfolio Longevity", longevity_str)

    c6, c7, c8, c9 = st.columns(4)
    c6.metric(annual_withdrawal_label, f"${annual_withdrawal:,.0f}")
    c7.metric("Lifetime Taxes", f"${summary['lifetime_taxes']:,.0f}")
    c8.metric("Lifetime Healthcare", f"${summary['lifetime_healthcare']:,.0f}")
    c9.metric("Lifetime Passive Income", f"${summary['lifetime_passive_income']:,.0f}")

    # ---------------------------------------------------------------------------
    # Tabs
    # ---------------------------------------------------------------------------
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📈 Accumulation", "💰 Retirement", "✏️ Custom Spending", "📋 Data Tables", "⚠️ Warnings"
    ])

    with tab1:
        st.plotly_chart(chart_accumulation(acc_df), use_container_width=True)
        st.plotly_chart(chart_composition_at_retirement(accounts_at_retirement), use_container_width=True)

        if acc_df["tax_drag"].sum() > 0:
            total_drag = acc_df.groupby("age")["tax_drag"].sum().sum()
            st.info(f"📊 Estimated tax drag on taxable accounts during accumulation: ${total_drag:,.0f} total.")

    with tab2:
        st.plotly_chart(chart_drawdown(ret_df, accounts_at_retirement), use_container_width=True)
        st.plotly_chart(chart_spending_coverage(ret_df), use_container_width=True)
        st.plotly_chart(chart_annual_income(ret_df), use_container_width=True)
        st.plotly_chart(chart_tax_burden(ret_df), use_container_width=True)

    with tab3:
        fixed_net_mode = assumptions.get("spending_mode") == "fixed"
        if fixed_net_mode:
            st.subheader("Custom After-Tax Spending by Year")
            st.caption(
                "Enter the desired **after-tax** spending for any year (excluding healthcare, which is added automatically). "
                "The simulation grosses up withdrawals to cover taxes so you net this amount. "
                "Set to 0 to revert to the inflation-adjusted default."
            )
        else:
            st.subheader("Custom Spending by Year")
            st.caption(
                "Enter a gross spending amount for any year (excluding healthcare). "
                "Set to 0 to revert to the inflation-adjusted default."
            )

        # Build display table from current simulation results
        default_spending = ret_df[["age", "spending_target", "healthcare_cost",
                                   "net_spending_target", "actual_after_tax_net"]].copy()
        default_spending["default_excl_healthcare"] = (
            default_spending["spending_target"] - default_spending["healthcare_cost"]
        )
        default_spending["override"] = [
            spending_overrides.get(int(row["age"]), 0)
            for _, row in default_spending.iterrows()
        ]

        if fixed_net_mode:
            editor_df = pd.DataFrame({
                "Age":                             default_spending["age"].astype(int),
                "Target After-Tax":                default_spending["net_spending_target"].round(0),
                "Actual After-Tax":                default_spending["actual_after_tax_net"].round(0),
                "Healthcare (auto)":               default_spending["healthcare_cost"].round(0),
                "Override (0 = use default)":      default_spending["override"].round(0),
            })
        else:
            editor_df = pd.DataFrame({
                "Age":                        default_spending["age"].astype(int),
                "Default Spending":           default_spending["default_excl_healthcare"].round(0),
                "Healthcare (auto)":          default_spending["healthcare_cost"].round(0),
                "Override (0 = use default)": default_spending["override"].round(0),
            })

        col_config = {"Age": st.column_config.NumberColumn(disabled=True)}
        for col in editor_df.columns:
            if col == "Age":
                continue
            elif col == "Override (0 = use default)":
                col_config[col] = st.column_config.NumberColumn(min_value=0, format="$%.0f")
            else:
                col_config[col] = st.column_config.NumberColumn(disabled=True, format="$%.0f")

        edited = st.data_editor(
            editor_df,
            column_config=col_config,
            use_container_width=True,
            hide_index=True,
            num_rows="fixed",
        )

        new_overrides = {
            int(row["Age"]): float(row["Override (0 = use default)"])
            for _, row in edited.iterrows()
            if row["Override (0 = use default)"] > 0
        }
        if new_overrides != spending_overrides:
            st.session_state.spending_overrides = new_overrides
            st.rerun()

        active_overrides = [age for age in spending_overrides if spending_overrides[age] > 0]
        if active_overrides:
            st.info(f"Active overrides: ages {sorted(active_overrides)}")
        if st.button("Clear All Overrides"):
            st.session_state.spending_overrides = {}
            st.rerun()

    with tab4:
        st.subheader("Accumulation Year-by-Year")
        acc_pivot = acc_df.pivot_table(
            index="age", columns="account_name", values="balance", aggfunc="sum"
        ).reset_index()
        st.dataframe(acc_pivot.style.format("${:,.0f}", subset=acc_pivot.columns[1:]), use_container_width=True)

        st.subheader("Retirement Year-by-Year")
        display_cols = [
            "age", "spending_target", "net_spending_target", "actual_after_tax_net",
            "spending_override_active",
            "ss_income", "rental_income", "investment_income",
            "rmd_amount", "taxable_withdrawal", "traditional_withdrawal", "roth_withdrawal", "bank_withdrawal",
            "roth_conversion", "ordinary_income", "ltcg_income",
            "total_tax", "effective_tax_rate", "federal_irmaa", "healthcare_cost",
            "after_tax_spending", "total_portfolio",
        ]
        display_cols = [c for c in display_cols if c in ret_df.columns]
        # Hide fixed-net-mode-only columns when in SWR mode (they're all None)
        if not fixed_net_mode:
            display_cols = [c for c in display_cols if c not in ("net_spending_target", "actual_after_tax_net")]
        fmt = {c: "${:,.0f}" for c in display_cols
               if c not in ("age", "effective_tax_rate", "spending_override_active")}
        fmt["effective_tax_rate"] = "{:.1%}"
        st.dataframe(ret_df[display_cols].style.format(fmt, na_rep="-"), use_container_width=True)

    with tab5:
        st.subheader("Warnings & Notes")
        warnings = summary.get("warnings", [])
        any_rental = any(a["type"] == "rental_property" for a in accounts)

        if not warnings and not any_rental:
            st.success("No warnings — your plan looks solid.")
        else:
            for w in warnings:
                if w["type"] == "depletion":
                    st.error(f"⚠️ {w['message']}")
                elif w["type"] == "irmaa":
                    st.warning(f"📋 {w['message']}")
                elif w["type"] == "survivor_transition":
                    st.info(f"👥 {w['message']}")
                elif w["type"] == "rmd_excess":
                    st.warning(f"🏦 {w['message']}")
            if any_rental:
                st.info("ℹ️ Rental property: depreciation recapture (25%) is not modeled on sale. Consult a tax advisor.")


if __name__ == "__main__":
    main()
