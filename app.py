import uuid
from datetime import date
import streamlit as st
import pandas as pd

from projections import project_accumulation
from withdrawals import simulate_retirement
import charts as _charts
import montecarlo as _mc
from scenarios import list_scenarios, latest_scenario, save_scenario, load_scenario, delete_scenario, load_tracking, save_tracking
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
    "post_medicare_healthcare": 12000.0,
}

DEFAULT_ASSUMPTIONS = {
    "inflation_rate": 0.03,
    "bracket_inflation_rate": 0.025,
    "safe_withdrawal_rate": 0.04,
    "retirement_return_rate": 0.05,
    "spending_mode": "swr",
    "annual_spending_target": 80000.0,
    "withdrawal_strategy": "tax_efficient",
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
        st.caption("Enter your estimated benefit in **today's dollars** (from SSA.gov 'my Social Security'). The simulation inflates to retirement-year nominal dollars and applies annual COLA.")

        if p["filing_status"] == "married_filing_jointly":
            st.markdown("**Spouse**")
            p["spouse_age"] = st.number_input("Spouse Current Age", 18, 80, p.get("spouse_age", p["current_age"]), key="p_sp_age")
            p["spouse_ss_benefit"] = st.number_input("Spouse SS Benefit ($/yr today's $)", 0, 60000, int(p.get("spouse_ss_benefit", 0)), 500, key="p_sp_ss")
            p["spouse_ss_start_age"] = st.number_input("Spouse SS Start Age", 62, 70, p.get("spouse_ss_start_age", 67), key="p_sp_ss_age")
            p["survivor_spending_reduction"] = _dec(st.number_input(
                "Survivor Spending Reduction (%)", 0.0, 50.0, _pct(p.get("survivor_spending_reduction", 0.25)), 1.0, key="p_surv"))

        st.markdown("**Healthcare**")
        p["pre_medicare_healthcare"] = st.number_input("Pre-Medicare Annual Cost ($)", 0, 50000, int(p.get("pre_medicare_healthcare", 15000)), 500, key="p_hc_pre")
        p["post_medicare_healthcare"] = st.number_input("Post-Medicare Annual Cost ($)", 0, 50000, int(p.get("post_medicare_healthcare", 12000)), 500, key="p_hc_post")
        st.caption(
            "Post-Medicare: include **Part B** (~$2,435/yr/person), Part D, supplemental (Medigap), dental/vision, and out-of-pocket. "
            "IRMAA surcharges are computed separately from income and added on top. "
            "A healthy couple with Medigap: ~$15,000–$20,000/yr."
        )


# ---------------------------------------------------------------------------
# Sidebar — Assumptions
# ---------------------------------------------------------------------------

def sidebar_assumptions():
    a = st.session_state.assumptions
    with st.sidebar.expander("📊 Assumptions", expanded=False):
        a["inflation_rate"] = _dec(st.number_input("Inflation Rate (%)", 0.0, 15.0, _pct(a["inflation_rate"]), 0.1, key="a_inf"))
        a["bracket_inflation_rate"] = _dec(st.number_input(
            "Tax Bracket Inflation Rate (%)", 0.0, 10.0,
            float(round(_pct(a.get("bracket_inflation_rate", 0.025)), 1)),
            0.1, key="a_bracket_inf",
        ))
        st.caption("Annual rate at which bracket thresholds, standard deduction, NIIT/IRMAA limits, and state brackets grow. SS taxability thresholds are not indexed — bracket creep on SS is intentional.")
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

        st.markdown("**Withdrawal Strategy**")
        a["withdrawal_strategy"] = st.radio(
            "Account withdrawal order",
            ["tax_efficient", "roth_preservation"],
            format_func=lambda x: "Tax-Efficient (default)" if x == "tax_efficient" else "Roth Preservation",
            index=0 if a.get("withdrawal_strategy", "tax_efficient") == "tax_efficient" else 1,
            key="a_withdraw_strat",
        )
        st.caption(
            "**Tax-Efficient**: fills traditional brackets to 22% before drawing Roth — minimizes current-year taxes. "
            "**Roth Preservation**: drains traditional accounts first, letting Roth grow tax-free longer — higher taxes now, lower RMDs later."
        )


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

    # Build projected portfolio by age (accumulation per-account + retirement totals)
    projected_by_age: dict[str, dict] = {}
    if not acc_df.empty:
        for age_val, grp in acc_df.groupby("age"):
            projected_by_age[str(int(age_val))] = {
                "total": float(grp["balance"].sum()),
                "by_account": {
                    row["account_id"]: {
                        "name": row["account_name"],
                        "type": row["account_type"],
                        "balance": float(row["balance"]),
                    }
                    for _, row in grp.iterrows()
                },
            }
    if not ret_df.empty:
        for _, row in ret_df.iterrows():
            age_str = str(int(row["age"]))
            entry = projected_by_age.get(age_str, {})
            entry["total"] = float(row["total_portfolio"])
            projected_by_age[age_str] = entry

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
    tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
        "📈 Accumulation", "💰 Retirement", "✏️ Custom Spending", "📋 Data Tables", "📊 Progress", "⚠️ Warnings", "🎲 Monte Carlo"
    ])

    with tab1:
        st.plotly_chart(_charts.chart_accumulation(acc_df), use_container_width=True)
        st.plotly_chart(_charts.chart_composition_at_retirement(accounts_at_retirement), use_container_width=True)

        if acc_df["tax_drag"].sum() > 0:
            total_drag = acc_df.groupby("age")["tax_drag"].sum().sum()
            st.info(f"📊 Estimated tax drag on taxable accounts during accumulation: ${total_drag:,.0f} total.")

    with tab2:
        st.plotly_chart(_charts.chart_drawdown(ret_df, accounts_at_retirement, assumptions.get("inflation_rate", 0.03), profile["current_age"]), use_container_width=True)
        st.plotly_chart(_charts.chart_spending_coverage(ret_df), use_container_width=True)
        st.plotly_chart(_charts.chart_annual_income(ret_df, assumptions.get("inflation_rate", 0.03), profile["retirement_age"]), use_container_width=True)
        st.plotly_chart(_charts.chart_tax_burden(ret_df), use_container_width=True)

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

        st.subheader("Retirement Account Balances")
        bal_cols = ["age"] + [c for c in ret_df.columns if c.startswith("bal_")] + ["total_portfolio"]
        bal_cols = [c for c in bal_cols if c in ret_df.columns]
        bal_df = ret_df[bal_cols].copy()
        col_rename = {"age": "Age", "total_portfolio": "Total Portfolio"}
        for a in accounts_at_retirement:
            col_key = f"bal_{a['name'].replace(' ', '_')}"
            if col_key in bal_df.columns:
                col_rename[col_key] = a["name"]
        bal_df = bal_df.rename(columns=col_rename)
        bal_df["Age"] = bal_df["Age"].astype(int)
        dollar_cols = [c for c in bal_df.columns if c != "Age"]
        st.dataframe(bal_df.style.format("${:,.0f}", subset=dollar_cols), use_container_width=True)

        st.subheader("Retirement Year-by-Year")
        display_cols = [
            "age", "spending_target", "net_spending_target", "actual_after_tax_net",
            "spending_override_active",
            "ss_income", "rental_income", "investment_income",
            "rmd_amount", "taxable_withdrawal", "traditional_withdrawal", "roth_withdrawal", "bank_withdrawal",
            "roth_conversion", "harvest_ltcg", "ordinary_income", "ltcg_income",
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
        scenario_name = st.session_state.get("sc_name", "My Scenario")
        tracking = load_tracking(scenario_name)
        baseline = tracking.get("baseline")
        checkins = tracking.get("checkins", [])

        # ── Baseline ──────────────────────────────────────────────────────────
        st.subheader("Baseline Plan")
        if baseline:
            captured = baseline.get("captured_date", "unknown date")
            proj_at_ret = baseline.get("projections_by_age", {}).get(
                str(profile["retirement_age"]), {}
            ).get("total")
            col_bl1, col_bl2, col_bl3 = st.columns([3, 2, 2])
            col_bl1.success(f"Baseline captured on **{captured}**")
            if proj_at_ret:
                col_bl2.metric("Projected at Retirement", f"${proj_at_ret:,.0f}")
            if col_bl3.button("Update Baseline"):
                tracking["baseline"] = {
                    "captured_date": date.today().isoformat(),
                    "projections_by_age": projected_by_age,
                }
                save_tracking(scenario_name, tracking)
                st.success("Baseline updated.")
                st.rerun()
        else:
            col_bl1, col_bl2 = st.columns([4, 2])
            col_bl1.info("No baseline saved yet. Capture the current projection to start tracking progress.")
            if col_bl2.button("Capture Baseline"):
                tracking["baseline"] = {
                    "captured_date": date.today().isoformat(),
                    "projections_by_age": projected_by_age,
                }
                save_tracking(scenario_name, tracking)
                st.success("Baseline captured.")
                st.rerun()

        st.divider()

        # ── Add a check-in ────────────────────────────────────────────────────
        st.subheader("Record Actual Balances")
        col_age, col_note = st.columns([1, 2])
        with col_age:
            ci_age = st.number_input(
                "Your Age at Check-in",
                min_value=profile["current_age"],
                max_value=profile["life_expectancy"],
                value=profile["current_age"],
                key="ci_age",
            )
        with col_note:
            ci_note = st.text_input("Note (optional)", key="ci_note")

        proj_at_ci_age = (baseline or {}).get("projections_by_age", {}).get(str(ci_age), {})
        proj_by_account = proj_at_ci_age.get("by_account", {})

        h1, h2, h3 = st.columns([3, 2, 2])
        h1.markdown("**Account**")
        h2.markdown("**Projected**")
        h3.markdown("**Actual Balance**")

        ci_balances: dict[str, float] = {}
        for a in accounts:
            c1, c2, c3 = st.columns([3, 2, 2])
            c1.write(f"{a['name']}  \n*{ACCOUNT_TYPE_LABELS.get(a['type'], a['type'])}*")
            proj_bal = proj_by_account.get(a["id"], {}).get("balance")
            c2.write(f"${proj_bal:,.0f}" if proj_bal is not None else "—")
            ci_balances[a["id"]] = float(c3.number_input(
                a["name"],
                min_value=0,
                max_value=100_000_000,
                value=0,
                step=1000,
                key=f"ci_bal_{a['id']}",
                label_visibility="collapsed",
            ))

        ci_total = sum(ci_balances.values())
        st.metric("Total Portfolio Entered", f"${ci_total:,.0f}")

        save_disabled = ci_total <= 0
        if st.button("Save Check-in", disabled=save_disabled):
            checkins.append({
                "id": str(uuid.uuid4())[:8],
                "date": date.today().isoformat(),
                "age": int(ci_age),
                "note": ci_note,
                "by_account": ci_balances,
                "total": ci_total,
            })
            tracking["checkins"] = checkins
            save_tracking(scenario_name, tracking)
            st.success(f"Check-in saved — age {ci_age}: ${ci_total:,.0f}")
            st.rerun()

        st.divider()

        # ── Comparison chart & history ─────────────────────────────────────────
        if baseline:
            if checkins:
                st.plotly_chart(
                    _charts.chart_progress_tracking(baseline["projections_by_age"], checkins),
                    use_container_width=True,
                )

                st.subheader("Check-in History")
                for c in sorted(checkins, key=lambda x: x["age"], reverse=True):
                    proj_entry = baseline["projections_by_age"].get(str(c["age"]), {})
                    proj_total = proj_entry.get("total")
                    delta = (c["total"] - proj_total) if proj_total is not None else None
                    pct = (delta / proj_total * 100) if (proj_total and delta is not None) else None

                    status = ""
                    if delta is not None:
                        status = "✅ Ahead" if delta >= 0 else "❌ Behind"

                    with st.expander(
                        f"Age {c['age']} — {c.get('date', '?')}  |  "
                        f"Actual: ${c['total']:,.0f}  |  "
                        f"Projected: ${proj_total:,.0f}  |  "
                        f"{'${:+,.0f} ({:+.1f}%)'.format(delta, pct) if delta is not None else '—'}  "
                        f"{status}"
                    ):
                        # Per-account breakdown (accumulation years only)
                        proj_by_acc = proj_entry.get("by_account", {})
                        if proj_by_acc:
                            rows_acc = []
                            for a in accounts:
                                actual_bal = c["by_account"].get(a["id"], 0.0)
                                proj_bal = proj_by_acc.get(a["id"], {}).get("balance")
                                acc_delta = (actual_bal - proj_bal) if proj_bal is not None else None
                                rows_acc.append({
                                    "Account": a["name"],
                                    "Type": ACCOUNT_TYPE_LABELS.get(a["type"], a["type"]),
                                    "Projected": proj_bal if proj_bal is not None else float("nan"),
                                    "Actual": actual_bal,
                                    "Delta ($)": acc_delta if acc_delta is not None else float("nan"),
                                })
                            df_acc = pd.DataFrame(rows_acc)
                            fmt_acc = {
                                "Projected": "${:,.0f}",
                                "Actual": "${:,.0f}",
                                "Delta ($)": "${:+,.0f}",
                            }
                            st.dataframe(
                                df_acc.style.format(fmt_acc, na_rep="—"),
                                use_container_width=True,
                                hide_index=True,
                            )
                        elif c["by_account"]:
                            # Retirement age check-in — show totals only (no per-account baseline)
                            rows_ret = [
                                {"Account": a["name"], "Actual": c["by_account"].get(a["id"], 0.0)}
                                for a in accounts
                                if c["by_account"].get(a["id"], 0.0) > 0
                            ]
                            st.dataframe(
                                pd.DataFrame(rows_ret).style.format({"Actual": "${:,.0f}"}),
                                use_container_width=True,
                                hide_index=True,
                            )

                        if c.get("note"):
                            st.caption(f"Note: {c['note']}")

                        if st.button("Delete this check-in", key=f"del_ci_{c['id']}"):
                            tracking["checkins"] = [x for x in checkins if x["id"] != c["id"]]
                            save_tracking(scenario_name, tracking)
                            st.rerun()
            else:
                st.plotly_chart(
                    _charts.chart_progress_tracking(baseline["projections_by_age"], []),
                    use_container_width=True,
                )
                st.info("No check-ins recorded yet. Enter actual balances above to compare against the plan.")
        else:
            st.info("Capture a baseline first to see the comparison chart.")

    with tab6:
        st.subheader("Warnings & Notes")
        warnings = summary.get("warnings", [])
        any_rental = any(a["type"] == "rental_property" for a in accounts)

        # Contribution limit checks (2026 IRS limits)
        contrib_warnings = []
        _cur_age = profile["current_age"]
        for _acct in accounts:
            _contrib = _acct.get("annual_contribution", 0)
            if _contrib <= 0:
                continue
            _atype = _acct["type"]
            if _atype in {"traditional_401k", "roth_401k"}:
                _limit = 23500
                if 50 <= _cur_age <= 59 or _cur_age >= 64:
                    _limit += 7500
                elif 60 <= _cur_age <= 63:
                    _limit += 11250
                if _contrib > _limit:
                    contrib_warnings.append(
                        f"**{_acct['name']}**: contribution ${_contrib:,.0f}/yr exceeds the 2026 401(k) limit of ${_limit:,.0f} for age {_cur_age}."
                    )
            elif _atype in {"traditional_ira", "roth_ira"}:
                _limit = 7000 + (1000 if _cur_age >= 50 else 0)
                if _contrib > _limit:
                    contrib_warnings.append(
                        f"**{_acct['name']}**: contribution ${_contrib:,.0f}/yr exceeds the 2026 IRA limit of ${_limit:,.0f} for age {_cur_age}."
                    )
            elif _atype == "hsa":
                _limit = 8550 if profile.get("filing_status") == "married_filing_jointly" else 4300
                if _contrib > _limit:
                    contrib_warnings.append(
                        f"**{_acct['name']}**: contribution ${_contrib:,.0f}/yr exceeds the 2026 HSA limit of ${_limit:,.0f}."
                    )

        has_contrib_warnings = bool(contrib_warnings)
        has_sim_warnings = bool(warnings)

        if not has_contrib_warnings and not has_sim_warnings and not any_rental:
            st.success("No warnings — your plan looks solid.")
        else:
            for cw in contrib_warnings:
                st.warning(f"📋 {cw}")
            for w in warnings:
                if w["type"] == "depletion":
                    st.error(f"⚠️ {w['message']}")
                elif w["type"] == "irmaa":
                    st.warning(f"📋 {w['message']}")
                elif w["type"] == "irmaa_approaching":
                    st.info(f"💡 {w['message']}")
                elif w["type"] == "survivor_transition":
                    st.info(f"👥 {w['message']}")
                elif w["type"] == "rmd_excess":
                    st.warning(f"🏦 {w['message']}")
            if any_rental:
                st.info("ℹ️ Rental property: depreciation recapture (25%) is not modeled on sale. Consult a tax advisor.")


    with tab7:
        st.subheader("Monte Carlo Simulation")
        st.caption(
            "Runs thousands of trials with randomized annual returns (drawn from a normal distribution, "
            "independently per account per year) to show the range of possible outcomes. "
            "**Success** = portfolio never hits $0 before your life expectancy. "
            "Spending, Social Security, and healthcare follow the same assumptions as the main simulation."
        )

        mc_col1, mc_col2 = st.columns([3, 1])
        with mc_col1:
            mc_vol = st.slider(
                "Equity Volatility (std dev %)",
                min_value=1, max_value=30, value=12, step=1,
                help=(
                    "Standard deviation of annual equity returns. "
                    "US equities: ~15–17%. Balanced 60/40 portfolio: ~10–12%. Conservative: ~6–8%. "
                    "Bond volatility is set to 30% of this value. "
                    "Bank and rental accounts use their own lower volatility."
                ),
                key="mc_vol",
            ) / 100.0
        with mc_col2:
            mc_n = int(st.number_input(
                "Trials", min_value=100, max_value=5000, value=1000, step=100, key="mc_n"
            ))

        alloc_col1, alloc_col2 = st.columns(2)
        with alloc_col1:
            mc_stock_pct = st.slider(
                "Stock Allocation (%)",
                min_value=0, max_value=100, value=60, step=5,
                help=(
                    "Portion of each investment account (401k, IRA, Roth, taxable) modeled as equities. "
                    "The remainder is modeled as bonds. Bank accounts and rental property are unaffected."
                ),
                key="mc_stock_pct",
            ) / 100.0
        with alloc_col2:
            mc_bond_return = st.number_input(
                "Bond Annual Return (%)",
                min_value=0.0, max_value=10.0, value=3.5, step=0.1,
                key="mc_bond_return",
                help="Expected annual return on the bond portion. Bonds have lower volatility and do not crash.",
            ) / 100.0

        _stock_ret = assumptions.get("retirement_return_rate", 0.05)
        _blended = mc_stock_pct * _stock_ret + (1 - mc_stock_pct) * mc_bond_return
        st.caption(
            f"Expected blended portfolio return: **{_blended:.1%}** "
            f"({mc_stock_pct:.0%} stocks × {_stock_ret:.1%} + "
            f"{1 - mc_stock_pct:.0%} bonds × {mc_bond_return:.1%}). "
            f"Stock return uses the Retirement Return Rate from Assumptions."
        )

        mc_crashes = st.checkbox(
            "Include market crash events (−20% equity shock every 10–20 years)",
            value=False,
            help=(
                "Each trial independently schedules one or more crashes during retirement, "
                "spaced 10–20 years apart. In a crash year, all equity accounts (401k, IRA, Roth, taxable) "
                "take an additional −20% drop on top of that year's normal random return. "
                "Bank accounts and rental property are not affected."
            ),
            key="mc_crashes",
        )

        if st.button("▶ Run Monte Carlo", type="primary", key="mc_run"):
            with st.spinner(f"Running {mc_n:,} simulations…"):
                mc_result = _mc.run_monte_carlo(
                    accounts_at_retirement=accounts_at_retirement,
                    profile=profile,
                    assumptions=assumptions,
                    n_runs=mc_n,
                    volatility=mc_vol,
                    enable_crashes=mc_crashes,
                    stock_pct=mc_stock_pct,
                    bond_return_rate=mc_bond_return,
                )
            st.session_state["mc_result"] = mc_result

        mc_result = st.session_state.get("mc_result")
        if mc_result:
            # Invalidate cached result if settings changed since last run
            stale = (
                mc_result.get("volatility") != mc_vol
                or mc_result.get("n_runs") != mc_n
                or mc_result.get("enable_crashes") != mc_crashes
                or mc_result.get("stock_pct") != mc_stock_pct
                or mc_result.get("bond_return_rate") != mc_bond_return
            )
            if stale:
                st.info("Settings changed — click **▶ Run Monte Carlo** to refresh results.")

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Success Rate", f"{mc_result['success_rate']:.1%}")
            m2.metric(
                "Median at Life Expectancy",
                f"${mc_result['percentiles'][50][-1]:,.0f}",
            )
            m3.metric(
                "10th Percentile at Life Expectancy",
                f"${mc_result['percentiles'][10][-1]:,.0f}",
            )
            m4.metric(
                "Trials Depleted",
                f"{mc_result['n_depleted']:,} / {mc_result['n_runs']:,}",
            )

            det_portfolio = ret_df["total_portfolio"].tolist() if not ret_df.empty else []
            st.plotly_chart(
                _charts.chart_monte_carlo(mc_result, det_portfolio),
                use_container_width=True,
            )

            if mc_result["n_depleted"] > 0:
                st.plotly_chart(
                    _charts.chart_mc_depletion(mc_result),
                    use_container_width=True,
                )
        else:
            st.info("Configure your plan in the sidebar, then click **▶ Run Monte Carlo** to see results.")


if __name__ == "__main__":
    main()
