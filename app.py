import copy
import uuid
from datetime import date
import streamlit as st
import pandas as pd

from projections import project_accumulation
from withdrawals import simulate_retirement
import charts as _charts
import montecarlo as _mc
import montecarlo_v2 as _mc2
import plotly.graph_objects as go
import optimizer as _opt
import optimizer_v2 as _opt_v2
from scenarios import list_scenarios, latest_scenario, save_scenario, load_scenario, delete_scenario, load_tracking, save_tracking, get_last_used_scenario, set_last_used_scenario, validate_scenario_name
from constants import RMD_START_AGE

st.set_page_config(page_title="Retirement Planner", layout="wide")

# Prevent Streamlit's built-in 'C' shortcut (Clear cache) from firing during Ctrl+C (copy).
st.html(
    """
    <script>
    document.addEventListener('keydown', function(e) {
        if ((e.ctrlKey || e.metaKey) && (e.key === 'c' || e.key === 'C')) {
            e.stopImmediatePropagation();
        }
    }, true);
    </script>
    """
)

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
    "retirement_return_rate": 0.065,
    "spending_mode": "swr",
    "annual_spending_target": 80000.0,
    "withdrawal_strategy": "tax_efficient",
}

DEFAULT_ACCOUNTS = [
    {
        "id": "acc1",
        "name": "401(k)",
        "type": "traditional_401k",
        "balance": 0.0,
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
        "balance": 0.0,
        "basis": 0.0,
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
        # Auto-load the last explicitly used scenario on first run / page refresh
        recent = get_last_used_scenario()
        if recent:
            try:
                data = load_scenario(recent)
                st.session_state.profile = data["profile"]
                st.session_state.assumptions = data["assumptions"]
                st.session_state.accounts = copy.deepcopy(data["accounts"])
                st.session_state.roth_conversion = data.get("roth_conversion", DEFAULT_ROTH_CONVERSION.copy())
                st.session_state.spending_overrides = {}
                st.session_state["sc_name"] = data.get("scenario_name", recent)
                return
            except Exception:
                pass
        st.session_state.profile = DEFAULT_PROFILE.copy()
    if "assumptions" not in st.session_state:
        st.session_state.assumptions = DEFAULT_ASSUMPTIONS.copy()
    if "accounts" not in st.session_state:
        st.session_state.accounts = copy.deepcopy(DEFAULT_ACCOUNTS)
    if "roth_conversion" not in st.session_state:
        st.session_state.roth_conversion = DEFAULT_ROTH_CONVERSION.copy()
    if "spending_overrides" not in st.session_state:
        st.session_state.spending_overrides = {}


def _apply_pending_load():
    if "_pending_load" not in st.session_state:
        return
    data = st.session_state.pop("_pending_load")
    st.session_state.profile = data["profile"]
    st.session_state.assumptions = data["assumptions"]
    st.session_state.accounts = data["accounts"]
    rc = data.get("roth_conversion", DEFAULT_ROTH_CONVERSION.copy())
    if "source_account_id" in rc and "source_account_ids" not in rc:
        old_id = rc.pop("source_account_id", None)
        rc["source_account_ids"] = [old_id] if old_id else []
    st.session_state.roth_conversion = rc
    st.session_state.spending_overrides = {}
    st.session_state.pop("cmp_result", None)
    _loaded_name = data.get("scenario_name", "My Scenario")
    st.session_state["sc_name"] = _loaded_name
    set_last_used_scenario(_loaded_name)


def _apply_pending_new_scenario():
    if "_pending_new_scenario" not in st.session_state:
        return
    new_name = st.session_state.pop("_pending_new_scenario")
    st.session_state.profile = DEFAULT_PROFILE.copy()
    st.session_state.assumptions = DEFAULT_ASSUMPTIONS.copy()
    st.session_state.accounts = copy.deepcopy(DEFAULT_ACCOUNTS)
    st.session_state.roth_conversion = DEFAULT_ROTH_CONVERSION.copy()
    st.session_state.spending_overrides = {}
    st.session_state.pop("cmp_result", None)
    st.session_state.pop("mc_result", None)
    st.session_state.pop("mc_result_v2", None)
    st.session_state["sc_name"] = new_name
    save_scenario(
        new_name,
        st.session_state.profile,
        st.session_state.assumptions,
        st.session_state.accounts,
        st.session_state.roth_conversion,
    )
    set_last_used_scenario(new_name)


_init_state()
_apply_pending_load()
_apply_pending_new_scenario()

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


def _count_warnings(accounts, profile, summary) -> int:
    """Return total number of active warnings (simulation + contribution limit)."""
    count = len(summary.get("warnings", []))
    cur_age = profile["current_age"]
    for _a in accounts:
        _contrib = _a.get("annual_contribution", 0)
        if _contrib <= 0:
            continue
        _atype = _a["type"]
        if _atype in {"traditional_401k", "roth_401k"}:
            _limit = 23500
            if 50 <= cur_age <= 59 or cur_age >= 64:
                _limit += 7500
            elif 60 <= cur_age <= 63:
                _limit += 11250
            if _contrib > _limit:
                count += 1
        elif _atype in {"traditional_ira", "roth_ira"}:
            if _contrib > 7000 + (1000 if cur_age >= 50 else 0):
                count += 1
        elif _atype == "hsa":
            _limit = 8550 if profile.get("filing_status") == "married_filing_jointly" else 4300
            if _contrib > _limit:
                count += 1
    return count


def _pct(val: float) -> float:
    return round(val * 100, 4)


def _dec(pct: float) -> float:
    return pct / 100.0


# ---------------------------------------------------------------------------
# Sidebar — Profile
# ---------------------------------------------------------------------------

def sidebar_profile():
    p = st.session_state.profile
    with st.sidebar.expander("1. 👤 Profile", expanded=True):
        p["current_age"] = st.number_input("Current Age", 18, 100, p["current_age"])
        p["retirement_age"] = st.number_input("Retirement Age", 18, 100, p["retirement_age"])
        _p_le_min = max(p["retirement_age"], p["current_age"]) + 1
        _p_le_val = max(p["life_expectancy"], _p_le_min)
        p["life_expectancy"] = st.number_input("Life Expectancy", _p_le_min, 110, _p_le_val)
        if p["retirement_age"] < p["current_age"]:
            st.warning("Retirement age is before current age — the app treats this as already retired.")
        if p["life_expectancy"] <= p["retirement_age"]:
            st.error("Life expectancy must be greater than retirement age.")
        p["filing_status"] = st.selectbox(
            "Filing Status",
            options=list(FILING_STATUS_LABELS.keys()),
            format_func=lambda k: FILING_STATUS_LABELS[k],
            index=list(FILING_STATUS_LABELS.keys()).index(p["filing_status"]),
        )
        state_options = {
            "california": "California (progressive brackets)",
            "montana": "Montana (progressive brackets)",
            "other": "Other state (flat rate)",
        }
        _state_keys = list(state_options.keys())
        _cur_state = p.get("state", "california")
        p["state"] = st.selectbox(
            "State",
            options=_state_keys,
            format_func=lambda k: state_options[k],
            index=_state_keys.index(_cur_state) if _cur_state in _state_keys else _state_keys.index("other"),
        )
        if p["state"] == "other":
            p["state_tax_rate"] = _dec(st.number_input("State Tax Rate (%)", 0.0, 15.0, _pct(p.get("state_tax_rate", 0.05)), 0.1))
        else:
            p["state_tax_rate"] = 0.0
        p["current_income"] = st.number_input("Current Annual Income ($)", 0, 1000000, int(p.get("current_income", 0) or 0), 1000)

        st.markdown("**Social Security**")
        p["social_security_benefit"] = st.number_input("Your SS Benefit ($/yr today's $)", 0, 60000, int(p.get("social_security_benefit", 0)), 500)
        p["social_security_start_age"] = st.number_input("Your SS Start Age", 62, 70, p.get("social_security_start_age", 67))
        st.caption("Enter your estimated benefit in **today's dollars** (from SSA.gov 'my Social Security'). The simulation inflates to retirement-year nominal dollars and applies annual COLA.")

        if p["filing_status"] == "married_filing_jointly":
            st.markdown("**Spouse**")
            p["spouse_age"] = st.number_input("Spouse Current Age", 18, 80, p.get("spouse_age", p["current_age"]))
            p["spouse_retirement_age"] = st.number_input("Spouse Retirement Age", 18, 100, p.get("spouse_retirement_age", 65))
            p["spouse_ss_benefit"] = st.number_input("Spouse SS Benefit ($/yr today's $)", 0, 60000, int(p.get("spouse_ss_benefit", 0)), 500)
            p["spouse_ss_start_age"] = st.number_input("Spouse SS Start Age", 62, 70, p.get("spouse_ss_start_age", 67))
            p["survivor_spending_reduction"] = _dec(st.number_input(
                "Survivor Spending Reduction (%)", 0.0, 50.0, _pct(p.get("survivor_spending_reduction", 0.25)), 1.0))

        st.markdown("**Healthcare**")
        p["pre_medicare_healthcare"] = st.number_input("Pre-Medicare Annual Cost ($)", 0, 50000, int(p.get("pre_medicare_healthcare", 15000)), 500)
        p["post_medicare_healthcare"] = st.number_input("Post-Medicare Annual Cost ($)", 0, 50000, int(p.get("post_medicare_healthcare", 12000)), 500)
        st.markdown(
            "<div style='font-size:0.8rem;color:#888;overflow-wrap:break-word;word-break:break-word;'>"
            "Post-Medicare: include <b>Part B</b> (~$2,435/yr/person), Part D, supplemental (Medigap), "
            "dental/vision, and out-of-pocket. "
            "IRMAA surcharges are computed separately from income and added on top. "
            "A healthy couple with Medigap: ~$15,000–$20,000/yr."
            "</div>",
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# Sidebar — Assumptions
# ---------------------------------------------------------------------------

def sidebar_assumptions():
    a = st.session_state.assumptions
    with st.sidebar.expander("2. 📊 Assumptions", expanded=False):
        a["inflation_rate"] = _dec(st.number_input("Inflation Rate (%)", 0.0, 15.0, _pct(a["inflation_rate"]), 0.1))
        a["bracket_inflation_rate"] = _dec(st.number_input(
            "Tax Bracket Inflation Rate (%)", 0.0, 10.0,
            float(round(_pct(a.get("bracket_inflation_rate", 0.025)), 1)),
            0.1,
        ))
        st.caption("Annual rate at which bracket thresholds, standard deduction, NIIT/IRMAA limits, and state brackets grow. SS taxability thresholds are not indexed — bracket creep on SS is intentional.")
        a["retirement_return_rate"] = _dec(st.number_input("Retirement Return Rate — capital appreciation (%)", 0.0, 15.0, _pct(a["retirement_return_rate"]), 0.1))
        st.caption(
            "Applied to accounts set to 'use global rate'. "
            "Default 6.5% reflects Shiller historical real equity total return of ~7.1–7.3% (1871–2025) less ~0.5–1% for a blended stock/bond portfolio. "
            "If your portfolio pays meaningful dividends, reduce this by the yield (e.g. use 5.0% if total return is 6.5% and dividend yield is 1.5%). "
            "Note: as of early 2026, U.S. equity valuations (Shiller CAPE) are historically elevated, "
            "which has tended to precede below-average forward returns — you may want a more conservative rate."
        )

        st.markdown("**Income Needed in Retirement**")
        a["spending_mode"] = st.radio(
            "Spending target method",
            ["swr", "fixed"],
            format_func=lambda x: "% of Portfolio (SWR)" if x == "swr" else "Fixed Dollar Amount",
            index=0 if a.get("spending_mode", "swr") == "swr" else 1,
        )
        if a["spending_mode"] == "swr":
            a["safe_withdrawal_rate"] = _dec(st.number_input("Safe Withdrawal Rate (%)", 1.0, 10.0, _pct(a.get("safe_withdrawal_rate", 0.04)), 0.1))
            st.caption("Spending = SWR × portfolio at retirement, inflated annually. Healthcare added on top.")
            if a["safe_withdrawal_rate"] > 0.065:
                st.warning("Rates above 6.5% have historically high failure rates. Most research supports 3.5–4.5%.")
        else:
            a["annual_spending_target"] = float(st.number_input(
                "After-Tax Annual Spending (today's $)", 10000, 1000000,
                int(a.get("annual_spending_target", 80000)), 1000,
            ))
            st.caption("Desired after-tax spending in today's dollars, excluding healthcare. Inflated to retirement date then annually. The simulation grosses up withdrawals to cover taxes.")

        st.markdown("**Withdrawal Strategy**")
        a["withdrawal_strategy"] = st.radio(
            "Account withdrawal order",
            ["tax_efficient", "roth_preservation"],
            format_func=lambda x: "Tax-Efficient (default)" if x == "tax_efficient" else "Roth Preservation",
            index=0 if a.get("withdrawal_strategy", "tax_efficient") == "tax_efficient" else 1,
        )
        st.caption(
            "**Tax-Efficient**: fills traditional brackets to 22% before drawing Roth — minimizes current-year taxes. "
            "**Roth Preservation**: drains traditional accounts first, letting Roth grow tax-free longer — higher taxes now, lower RMDs later."
        )


# ---------------------------------------------------------------------------
# Sidebar — Accounts
# ---------------------------------------------------------------------------

OWNER_ACCOUNT_TYPES = {"traditional_401k", "roth_401k", "traditional_ira", "roth_ira", "hsa"}


def sidebar_accounts():
    with st.sidebar.expander("3. 🏦 Accounts", expanded=True):
        accts = st.session_state.accounts
        is_mfj = st.session_state.profile.get("filing_status") == "married_filing_jointly"
        for i, a in enumerate(accts):
            with st.expander(f"{a['name']} ({ACCOUNT_TYPE_LABELS.get(a['type'], a['type'])})", expanded=False):
                a["name"] = st.text_input("Name", a["name"], key=f"a_name_{a['id']}")
                type_keys = list(ACCOUNT_TYPES.keys())
                type_vals = list(ACCOUNT_TYPES.values())
                cur_idx = type_vals.index(a["type"]) if a["type"] in type_vals else 0
                a["type"] = ACCOUNT_TYPES[st.selectbox("Type", type_keys, index=cur_idx, key=f"a_type_{a['id']}")]

                if is_mfj and a["type"] in OWNER_ACCOUNT_TYPES:
                    owner_options = ["self", "spouse"]
                    cur_owner_idx = 1 if a.get("owner", "self") == "spouse" else 0
                    a["owner"] = st.selectbox(
                        "Owner", owner_options,
                        format_func=lambda x: "You (primary)" if x == "self" else "Spouse",
                        index=cur_owner_idx,
                        key=f"a_owner_{a['id']}",
                        help="Determines whose retirement age governs when this account can be accessed for Roth conversions.",
                    )
                else:
                    a["owner"] = "self"

                a["balance"] = float(st.number_input("Current Balance ($)", 0, 10000000, int(a["balance"]), 1000, key=f"a_bal_{a['id']}"))

                always_own_rate = a["type"] in {"rental_property", "bank"}
                if always_own_rate:
                    a["return_rate"] = _dec(st.number_input("Return / Appreciation Rate (%)", 0.0, 20.0, _pct(a["return_rate"]), 0.1, key=f"a_ret_{a['id']}"))
                else:
                    a["return_rate"] = _dec(st.number_input("Return Rate — accumulation (%)", 0.0, 20.0, _pct(a["return_rate"]), 0.1, key=f"a_ret_{a['id']}"))
                    if a["type"] in {"taxable", "reit"}:
                        _qdy = _pct(a.get("qualified_dividend_yield", 0.0))
                        _oiy = _pct(a.get("ordinary_income_yield", 0.0))
                        _total_ret = _pct(a["return_rate"]) + _qdy + _oiy
                        st.caption(
                            f"Price appreciation only. "
                            f"Total return = this rate + qualified dividend yield + ordinary income yield "
                            f"({_pct(a['return_rate']):.2f}% + {_qdy:.2f}% + {_oiy:.2f}% = **{_total_ret:.2f}%** total)."
                        )
                    use_global = st.checkbox(
                        "Use global retirement return rate",
                        value=a.get("use_global_return_rate", True),
                        key=f"chk_global_{a['id']}",
                    )
                    a["use_global_return_rate"] = use_global
                    global_ret = st.session_state.assumptions.get("retirement_return_rate", 0.065)
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
                    _hold_last = st.checkbox("Hold for last resort (sell only when all other sources exhausted)", value=a.get("withdraw_priority", "normal") == "last", key=f"a_wlast_{a['id']}")
                    a["withdraw_priority"] = "last" if _hold_last else "normal"

                if a["type"] == "rental_property":
                    a["basis"] = float(st.number_input("Cost Basis ($)", 0, 10000000, int(a.get("basis", a["balance"] * 0.5)), 1000, key=f"a_basis_{a['id']}"))
                    a["net_annual_rental_income"] = float(st.number_input("Net Annual Rental Income ($)", 0, 500000, int(a.get("net_annual_rental_income", 0)), 500, key=f"a_rent_{a['id']}"))

                if a["type"] == "bank":
                    a["bank_buffer"] = float(st.number_input(
                        "Cash Buffer ($)",
                        min_value=0, max_value=500000,
                        value=int(a.get("bank_buffer", 0)),
                        step=5000,
                        key=f"a_buf_{a['id']}",
                        help="Amount kept in reserve — never withdrawn during planned funding. "
                             "Used only by the Step-6 correction to absorb tax-estimation errors "
                             "so actual after-tax spending stays on target.",
                    ))

                if st.button("Remove Account", key=f"a_del_{a['id']}"):
                    accts.pop(i)
                    st.rerun()

        if st.button("➕ Add Account"):
            accts.append({
                "id": str(uuid.uuid4())[:8],
                "name": "New Account",
                "type": "taxable",
                "owner": "self",
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
    with st.sidebar.expander("4. 🔄 Roth Conversion (optional)", expanded=False):
        rc["enabled"] = st.checkbox("Enable Roth Conversion Strategy", rc.get("enabled", False))
        if rc["enabled"]:
            rc["strategy"] = st.radio(
                "Strategy",
                ["fill_to_bracket", "fixed_amount"],
                format_func=lambda x: "Fill to Bracket" if x == "fill_to_bracket" else "Fixed Amount",
                index=0 if rc.get("strategy") == "fill_to_bracket" else 1,
            )
            if rc["strategy"] == "fill_to_bracket":
                bracket_options = {0.10: "10%", 0.12: "12%", 0.22: "22%", 0.24: "24%"}
                rc["target_bracket"] = st.selectbox(
                    "Fill up to bracket",
                    options=list(bracket_options.keys()),
                    format_func=lambda k: bracket_options[k],
                    index=list(bracket_options.keys()).index(rc.get("target_bracket", 0.12)),
                )
            else:
                rc["fixed_amount"] = float(st.number_input("Annual Conversion ($)", 0, 500000, int(rc.get("fixed_amount", 10000)), 1000))

            _rc_start_min = p["retirement_age"]
            _rc_start_val = max(rc.get("start_age", _rc_start_min), _rc_start_min)
            rc["start_age"] = st.number_input("Conversion Start Age", _rc_start_min, 80, _rc_start_val)
            _rc_end_min = rc["start_age"]
            _rc_end_val = max(rc.get("end_age", _rc_end_min), _rc_end_min)
            rc["end_age"] = st.number_input("Conversion End Age", _rc_end_min, 85, _rc_end_val)

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
                rc["destination_account_id"] = dst_ids[st.selectbox("Convert Into", range(len(dst_names)), format_func=lambda i: dst_names[i], index=cur_dst)]


# ---------------------------------------------------------------------------
# Sidebar — Scenario save/load
# ---------------------------------------------------------------------------

def _do_save(name: str) -> None:
    save_scenario(
        name,
        st.session_state.profile,
        st.session_state.assumptions,
        st.session_state.accounts,
        st.session_state.roth_conversion,
    )
    set_last_used_scenario(name)
    st.session_state.pop("cmp_result", None)


def sidebar_scenarios():
    with st.sidebar.expander("💾 Scenarios", expanded=False):
        st.session_state.setdefault("sc_name", "My Scenario")
        name = st.text_input("Scenario Name", key="sc_name")
        try:
            validate_scenario_name(name)
            _sc_name_valid = True
        except ValueError as _ve:
            _sc_name_valid = False
            st.caption(f"⚠️ {_ve}")
        if st.button("Save", key="sc_save", disabled=not _sc_name_valid):
            try:
                _do_save(name)
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
    st.markdown(
        """
        <div style="
            border-radius: 12px;
            padding: 1.1rem 1.6rem;
            margin-bottom: 1rem;
            background: linear-gradient(135deg, #1a365d 0%, #2b6cb0 60%, #3182ce 100%);
            box-shadow: 0 4px 16px rgba(49, 130, 206, 0.25);
            display: flex;
            align-items: center;
            gap: 1rem;
        ">
            <div style="font-size: 2rem; line-height: 1;">📈</div>
            <div>
                <div style="
                    font-size: 1.55rem;
                    font-weight: 800;
                    color: #ffffff;
                    letter-spacing: -0.01em;
                    line-height: 1.15;
                ">Retirement Planner</div>
                <div style="
                    font-size: 0.82rem;
                    color: rgba(255,255,255,0.72);
                    margin-top: 0.15rem;
                    letter-spacing: 0.01em;
                ">Model investment accounts · project growth · optimize tax-efficient withdrawals</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # First-run onboarding banner — shown when no scenarios have been saved yet
    if not list_scenarios() and not st.session_state.get("onboarding_dismissed"):
        _ob_msg, _ob_btn = st.columns([8, 1])
        _ob_msg.info(
            "**Getting Started** — fill in the sidebar to personalise your plan: "
            "**1.** Profile (ages, income, Social Security) → "
            "**2.** Assumptions (inflation, spending target) → "
            "**3.** Accounts (401k, Roth IRA, etc.) → "
            "**4.** Save your scenario with the 💾 button"
        )
        if _ob_btn.button("✕", key="dismiss_onboarding", help="Dismiss"):
            st.session_state["onboarding_dismissed"] = True
            st.rerun()

    # Sidebar
    sc_display = st.session_state.get("sc_name", "My Scenario")
    _sb_name_col, _sb_save_col, _sb_new_col = st.sidebar.columns([3, 1, 1])
    _sb_name_col.markdown(
        f"<div style='font-size:0.78rem;color:#888;margin-bottom:0.1rem;'>Scenario</div>"
        f"<div style='font-size:1rem;font-weight:600;margin-bottom:0.75rem;'>{sc_display}</div>",
        unsafe_allow_html=True,
    )
    try:
        validate_scenario_name(sc_display)
        _name_valid = True
    except ValueError:
        _name_valid = False
    if _sb_save_col.button("💾 Save", key="sc_quicksave", help=f"Save '{sc_display}'", width='stretch', disabled=not _name_valid):
        try:
            _do_save(sc_display)
            st.sidebar.success("Saved ✓", icon="💾")
        except Exception as e:
            st.sidebar.error(str(e))
    if _sb_new_col.button("➕ New", key="sc_new_btn", help="Create a new blank scenario", width='stretch'):
        st.session_state["new_scenario_form_open"] = True
        st.rerun()
    if not _name_valid:
        st.sidebar.caption("⚠️ Scenario name contains invalid characters. Use only letters, numbers, spaces, hyphens, and underscores.")

    if st.session_state.get("new_scenario_form_open"):
        with st.sidebar.form("new_scenario_form", border=True):
            st.markdown("**New Scenario**")
            _new_name = st.text_input("Name", value="My Scenario", key="new_sc_name_input")
            _col_create, _col_cancel = st.columns(2)
            _submitted = _col_create.form_submit_button("Create", type="primary", use_container_width=True)
            _cancelled = _col_cancel.form_submit_button("Cancel", use_container_width=True)
        if _cancelled:
            st.session_state.pop("new_scenario_form_open", None)
            st.rerun()
        if _submitted:
            try:
                validate_scenario_name(_new_name)
                st.session_state.pop("new_scenario_form_open", None)
                st.session_state["_pending_new_scenario"] = _new_name
                st.rerun()
            except ValueError as _ve:
                st.sidebar.error(str(_ve))
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
            entry["total"] = float(row["start_portfolio"])
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

    le_age = profile["life_expectancy"]
    if not ret_df.empty:
        le_row = ret_df[ret_df["age"] == le_age]
        portfolio_at_le = float(le_row["total_portfolio"].iloc[0]) if not le_row.empty else 0.0
    else:
        portfolio_at_le = 0.0

    hdr_col, tog_col = st.columns([5, 1])
    hdr_col.subheader("Summary")
    compact_view = tog_col.toggle("Snapshot", key="summary_compact", value=False)

    if compact_view:
        # ── Compact snapshot view ──────────────────────────────────────────────
        today_portfolio = sum(a["balance"] for a in accounts)
        # Mode-aware: in fixed mode show the after-tax target (today's $); in SWR mode
        # annual_spending_target is unused/stale, so show the SWR-implied year-1 withdrawal.
        if fixed_net_mode:
            spending_label = "Spending Goal"
            spending_goal = assumptions.get("annual_spending_target", 0.0)
            spending_help = "Your after-tax discretionary spending target in retirement (today's dollars, healthcare separate)."
        else:
            _swr = assumptions.get("safe_withdrawal_rate", 0.04)
            spending_label = "Withdrawal (yr 1)"
            spending_goal = total_at_retirement * _swr
            spending_help = f"SWR mode: {_swr:.1%} × portfolio at retirement (gross, retirement-year dollars; taxes and healthcare come out of this)."

        c_now, c_ret, c_eol = st.columns(3)
        with c_now:
            st.markdown(f"**Today  (Age {profile['current_age']})**")
            st.metric("Portfolio", f"${today_portfolio:,.0f}")
            st.metric(spending_label, f"${spending_goal:,.0f}", help=spending_help)
        with c_ret:
            st.markdown(f"**Retirement Day 1  (Age {profile['retirement_age']})**")
            st.metric("Portfolio", f"${total_at_retirement:,.0f}")
        with c_eol:
            st.markdown(f"**End of Life  (Age {le_age})**")
            if portfolio_at_le <= 0:
                st.markdown(
                    f"""<div style="border:2px solid #cc0000;border-radius:8px;padding:10px 14px;background:#fff0f0;margin-bottom:1rem;">
                    <div style="font-size:0.85rem;color:#888;margin-bottom:4px;">Portfolio</div>
                    <div style="font-size:1.6rem;font-weight:700;color:#cc0000;">$0 — Depleted</div>
                    </div>""",
                    unsafe_allow_html=True,
                )
            else:
                st.metric("Portfolio", f"${portfolio_at_le:,.0f}")
    else:
        # ── Full summary view ──────────────────────────────────────────────────
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Portfolio at Retirement", f"${total_at_retirement:,.0f}")
        c2.metric("Pre-Tax", f"${pre_tax_total:,.0f}")
        c3.metric("Roth / Tax-Free", f"${roth_total:,.0f}")
        c4.metric("Taxable / Real Estate", f"${taxable_total:,.0f}")
        c5.metric("Portfolio Longevity", longevity_str)

        c6, c7, c8, c9, c10 = st.columns(5)
        _infl_pct = assumptions.get("inflation_rate", 0.03) * 100
        c6.metric(
            annual_withdrawal_label,
            f"${annual_withdrawal:,.0f}",
            help=f"Your spending target ({_infl_pct:.1f}% inflation applied from today's dollars to retirement year 1)." if fixed_net_mode else None,
        )
        c7.metric("Lifetime Taxes", f"${summary['lifetime_taxes']:,.0f}")
        c8.metric("Lifetime Healthcare", f"${summary['lifetime_healthcare']:,.0f}")
        c9.metric("Lifetime Passive Income", f"${summary['lifetime_passive_income']:,.0f}")
        with c10:
            if portfolio_at_le <= 0:
                st.markdown(
                    f"""<div style="border:2px solid #cc0000;border-radius:8px;padding:10px 14px;background:#fff0f0;">
                    <div style="font-size:0.85rem;color:#888;margin-bottom:4px;">Portfolio at Age {le_age}</div>
                    <div style="font-size:1.6rem;font-weight:700;color:#cc0000;">$0</div>
                    </div>""",
                    unsafe_allow_html=True,
                )
            else:
                st.metric(f"Portfolio at Age {le_age}", f"${portfolio_at_le:,.0f}")

    if portfolio_at_le <= 0:
        st.error(
            "Your portfolio is depleted before your life expectancy — this plan likely won't work. "
            "Consider increasing your retirement age, reducing spending assumptions, or saving more."
        )

    # ---------------------------------------------------------------------------
    # Tabs
    # ---------------------------------------------------------------------------
    # ---------------------------------------------------------------------------
    # Scenario comparison
    # ---------------------------------------------------------------------------
    _saved_scenarios = list_scenarios()
    _cur_sc_name = st.session_state.get("sc_name", "")
    _other_scenarios = [s for s in _saved_scenarios if s != _cur_sc_name]
    if _other_scenarios:
        with st.expander("🔀 Compare with another scenario", expanded=False):
            _cmp_sel = st.selectbox("Select scenario to compare:", _other_scenarios, key="cmp_sel")
            if st.button("Run Comparison", key="cmp_run"):
                with st.spinner("Running comparison…"):
                    try:
                        import copy as _copy
                        _cmp_data = load_scenario(_cmp_sel)
                        _cmp_accs, _cmp_accts_ret = project_accumulation(
                            _cmp_data["accounts"], _cmp_data["profile"], _cmp_data["assumptions"]
                        )
                        _cmp_ret_df, _cmp_sum = simulate_retirement(
                            _cmp_accts_ret, _cmp_data["profile"], _cmp_data["assumptions"],
                            _cmp_data.get("roth_conversion", DEFAULT_ROTH_CONVERSION.copy()), {}
                        )
                        _cmp_le = _cmp_data["profile"]["life_expectancy"]
                        _cmp_depl = _cmp_sum.get("portfolio_depleted_age")
                        _cmp_le_row = _cmp_ret_df[_cmp_ret_df["age"] == _cmp_le] if not _cmp_ret_df.empty else _cmp_ret_df.iloc[0:0]
                        # Mirror the current-scenario year-1 spend logic (lines ~750-756): in
                        # fixed-net mode report the after-tax target, otherwise the gross
                        # withdrawal. Using gross unconditionally made two fixed-net scenarios
                        # with identical after-tax targets but different tax (e.g. MT vs no state
                        # tax) appear to have different year-1 spend.
                        _cmp_fixed_net = _cmp_data["assumptions"].get("spending_mode") == "fixed"
                        _cmp_spend_col = "net_spending_target" if _cmp_fixed_net else "spending_target"
                        st.session_state["cmp_result"] = {
                            "name": _cmp_sel,
                            "total_at_retirement": sum(a["balance"] for a in _cmp_accts_ret),
                            "longevity": f"Age {_cmp_depl}" if _cmp_depl else f"Lasts to {_cmp_le}+",
                            "spend_yr1": float(_cmp_ret_df[_cmp_spend_col].iloc[0]) if not _cmp_ret_df.empty else 0.0,
                            "portfolio_at_le": float(_cmp_le_row["total_portfolio"].iloc[0]) if not _cmp_le_row.empty else 0.0,
                            "lifetime_taxes": _cmp_sum.get("lifetime_taxes", 0),
                            "lifetime_healthcare": _cmp_sum.get("lifetime_healthcare", 0),
                        }
                    except Exception as _cmp_e:
                        st.error(f"Comparison failed: {_cmp_e}")

            _cmp_result = st.session_state.get("cmp_result")
            if _cmp_result:
                if _cmp_result["name"] != st.session_state.get("cmp_sel", ""):
                    st.caption("Showing comparison with a previously run scenario — click Run Comparison to refresh.")
                _cmp_table = {
                    "Metric": [
                        "Portfolio at Retirement",
                        "Portfolio Longevity",
                        "Year 1 Annual Spending",
                        "Portfolio at End of Plan",
                        "Lifetime Taxes",
                        "Lifetime Healthcare",
                    ],
                    _cur_sc_name or "Current": [
                        f"${total_at_retirement:,.0f}",
                        longevity_str,
                        f"${annual_withdrawal:,.0f}",
                        f"${portfolio_at_le:,.0f}",
                        f"${summary['lifetime_taxes']:,.0f}",
                        f"${summary['lifetime_healthcare']:,.0f}",
                    ],
                    _cmp_result["name"]: [
                        f"${_cmp_result['total_at_retirement']:,.0f}",
                        _cmp_result["longevity"],
                        f"${_cmp_result['spend_yr1']:,.0f}",
                        f"${_cmp_result['portfolio_at_le']:,.0f}",
                        f"${_cmp_result['lifetime_taxes']:,.0f}",
                        f"${_cmp_result['lifetime_healthcare']:,.0f}",
                    ],
                }
                st.dataframe(pd.DataFrame(_cmp_table), width='stretch', hide_index=True)

    def _kpi_bar():
        st.markdown(
            f"<div style='font-size:0.82rem;color:#555;background:#f0f2f6;border-radius:6px;"
            f"padding:6px 14px;margin-bottom:10px;line-height:1.8;'>"
            f"Portfolio at retirement: <b>${total_at_retirement:,.0f}</b> &nbsp;·&nbsp; "
            f"Longevity: <b>{longevity_str}</b> &nbsp;·&nbsp; "
            f"Year 1 spending: <b>${annual_withdrawal:,.0f}</b>"
            f"</div>",
            unsafe_allow_html=True,
        )

    _warn_count = _count_warnings(accounts, profile, summary)
    _warn_tab_label = f"⚠️ Warnings ({_warn_count})" if _warn_count > 0 else "⚠️ Warnings"

    tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab9 = st.tabs([
        "📈 Accumulation", "💰 Retirement", "✏️ Custom Spending", "📋 Data Tables", "📊 Progress",
        _warn_tab_label, "🎲 Monte Carlo", "🔍 Optimizer", "🏦 Accounts"
    ])

    with tab1:
        _kpi_bar()
        if profile["retirement_age"] <= profile["current_age"]:
            st.info("Already retired — no accumulation phase. See the Retirement tab for projections.")
            st.plotly_chart(_charts.chart_composition_at_retirement(accounts_at_retirement), width='stretch')
        else:
            st.plotly_chart(_charts.chart_accumulation(acc_df), width='stretch')
            st.plotly_chart(_charts.chart_composition_at_retirement(accounts_at_retirement), width='stretch')

            if acc_df["tax_drag"].sum() > 0:
                total_drag = acc_df.groupby("age")["tax_drag"].sum().sum()
                st.info(f"📊 Estimated tax drag on taxable accounts during accumulation: ${total_drag:,.0f} total.")

    with tab2:
        _kpi_bar()
        _cur_age = profile["current_age"]
        _ret_age = profile["retirement_age"]
        st.plotly_chart(_charts.chart_drawdown(ret_df, accounts_at_retirement, assumptions.get("inflation_rate", 0.03), _cur_age, _ret_age), width='stretch')
        st.plotly_chart(_charts.chart_spending_coverage(ret_df, _cur_age, _ret_age), width='stretch')
        st.plotly_chart(_charts.chart_annual_income(ret_df, assumptions.get("inflation_rate", 0.03), _ret_age, _cur_age), width='stretch')
        st.plotly_chart(_charts.chart_tax_burden(ret_df, _cur_age, _ret_age), width='stretch')

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
                col_config[col] = st.column_config.NumberColumn(min_value=0, format="$%,.0f")
            else:
                col_config[col] = st.column_config.NumberColumn(disabled=True, format="$%,.0f")

        edited = st.data_editor(
            editor_df,
            column_config=col_config,
            width='stretch',
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
        if acc_df.empty:
            st.info("No accumulation phase — already retired.")
        else:
            acc_pivot = acc_df.pivot_table(
                index="age", columns="account_name", values="balance", aggfunc="sum"
            ).reset_index()
            st.dataframe(acc_pivot.style.format("${:,.0f}", subset=acc_pivot.columns[1:]), width='stretch')

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
        st.dataframe(bal_df.style.format("${:,.0f}", subset=dollar_cols), width='stretch')

        st.subheader("Retirement Year-by-Year")
        # Withdrawal % = gross spending need / start-of-year portfolio.
        # Year 1 start = total_at_retirement; subsequent = prior year's end balance.
        _display_df = ret_df.copy()
        _display_df["withdrawal_pct"] = _display_df["spending_target"] / _display_df["start_portfolio"].clip(lower=1.0)
        _display_df["net_spending_delta"] = _display_df["actual_after_tax_net"] - _display_df["net_spending_target"]

        display_cols = [
            # ── Context ──────────────────────────────────────────
            "age", "start_portfolio",
            # ── Spending targets ─────────────────────────────────
            "spending_target", "net_spending_target", "withdrawal_pct", "spending_override_active",
            # ── Passive / mandatory income ────────────────────────
            "ss_income", "rental_income", "investment_income", "rmd_amount",
            # ── Discretionary withdrawals (tax-free first) ────────
            "bank_withdrawal", "taxable_withdrawal", "traditional_withdrawal", "roth_withdrawal",
            # ── Roth conversion ───────────────────────────────────
            "roth_conversion",
            # ── LTCG detail ───────────────────────────────────────
            "qual_dividends", "harvest_ltcg", "withdrawal_ltcg",
            # ── Tax calculation inputs ────────────────────────────
            "ordinary_income", "ltcg_income", "magi",
            # ── Tax bill ─────────────────────────────────────────
            "total_tax", "effective_tax_rate", "federal_irmaa", "healthcare_cost",
            # ── Result ────────────────────────────────────────────
            "after_tax_spending", "actual_after_tax_net", "net_spending_delta", "surplus_reinvested",
            # ── End state ─────────────────────────────────────────
            "total_portfolio",
        ]
        display_cols = [c for c in display_cols if c in _display_df.columns]
        # Hide fixed-net-mode-only columns when in SWR mode (they're all None)
        if not fixed_net_mode:
            display_cols = [c for c in display_cols if c not in ("net_spending_target", "actual_after_tax_net", "net_spending_delta")]
        fmt = {c: "${:,.0f}" for c in display_cols
               if c not in ("age", "effective_tax_rate", "spending_override_active", "withdrawal_pct")}
        fmt["effective_tax_rate"] = "{:.1%}"
        fmt["withdrawal_pct"] = "{:.2%}"

        def _color_delta(val):
            if not isinstance(val, (int, float)) or val == 0:
                return ""
            return "color: red" if val < -1 else "color: green" if val > 1 else ""

        styled = _display_df[display_cols].style.format(fmt, na_rep="-")
        if "net_spending_delta" in display_cols:
            styled = styled.map(_color_delta, subset=["net_spending_delta"])
        st.dataframe(styled, width='stretch')

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
            if st.session_state.get("ci_age", profile["current_age"]) < profile["current_age"]:
                st.session_state["ci_age"] = profile["current_age"]
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

        ci_update_accounts = st.checkbox(
            "Also update account balances in scenario from this check-in",
            key="ci_update_accounts",
        )

        basis_accounts = [a for a in accounts if a["type"] in {"taxable", "reit", "rental_property"}]
        ci_new_basis: dict[str, float] = {}
        if ci_update_accounts and basis_accounts:
            ci_update_basis = st.checkbox(
                "Also update cost basis for taxable accounts",
                key="ci_update_basis",
            )
            if ci_update_basis:
                st.markdown("**New Cost Basis**")
                bh1, bh2 = st.columns([3, 2])
                bh1.markdown("*Account*")
                bh2.markdown("*Cost Basis ($)*")
                for a in basis_accounts:
                    bc1, bc2 = st.columns([3, 2])
                    bc1.write(a["name"])
                    ci_new_basis[a["id"]] = float(bc2.number_input(
                        a["name"],
                        min_value=0,
                        max_value=100_000_000,
                        value=int(a.get("basis", 0)),
                        step=1000,
                        key=f"ci_basis_{a['id']}",
                        label_visibility="collapsed",
                    ))

        if ci_update_accounts:
            st.warning(
                f"Saving will update each account's balance to the values entered above "
                f"and will set your **current age in the profile to {int(ci_age)}**. "
                f"This changes your scenario's starting point for future projections."
            )

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

            if ci_update_accounts:
                for a in st.session_state.accounts:
                    if a["id"] in ci_balances:
                        a["balance"] = ci_balances[a["id"]]
                    if a["id"] in ci_new_basis:
                        a["basis"] = ci_new_basis[a["id"]]
                st.session_state.profile["current_age"] = int(ci_age)
                save_scenario(
                    scenario_name,
                    st.session_state.profile,
                    st.session_state.assumptions,
                    st.session_state.accounts,
                    st.session_state.roth_conversion,
                )
                set_last_used_scenario(scenario_name)
                st.success(
                    f"Check-in saved and scenario updated — age set to {int(ci_age)}, "
                    f"balances updated: ${ci_total:,.0f}"
                )
            else:
                st.success(f"Check-in saved — age {ci_age}: ${ci_total:,.0f}")
            st.rerun()

        st.divider()

        # ── Comparison chart & history ─────────────────────────────────────────
        mc_median = tracking.get("mc_median")

        if baseline:
            if checkins:
                st.plotly_chart(
                    _charts.chart_progress_tracking(baseline["projections_by_age"], checkins, mc_median),
                    width='stretch',
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
                                width='stretch',
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
                                width='stretch',
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
                    _charts.chart_progress_tracking(baseline["projections_by_age"], [], mc_median),
                    width='stretch',
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

        with st.expander("ℹ️ Understanding common warnings — glossary", expanded=False):
            st.markdown("""
**IRMAA** (Income-Related Monthly Adjustment Amount)
: An extra Medicare surcharge for higher-income retirees, added on top of standard Part B/D premiums. In 2026 it applies when MAGI exceeds $106,000 (single) / $212,000 (MFJ). The simulation adds IRMAA to your projected healthcare costs automatically.

**RMDs** (Required Minimum Distributions)
: The IRS requires minimum annual withdrawals from pre-tax accounts (Traditional 401k/IRA) starting at age 73. The required percentage increases with age. If your RMD exceeds your spending need, the excess is a taxable event you can't avoid — Roth conversions before 73 can reduce this.

**Tax drag**
: Taxable brokerage accounts pay taxes on dividends and realised gains each year, reducing compounding. The simulation deducts estimated annual taxes from taxable account growth.

**NIIT** (Net Investment Income Tax)
: A 3.8% surtax on net investment income (dividends, interest, capital gains) for individuals with MAGI above $200,000 (single) / $250,000 (MFJ). Applied on top of ordinary income and LTCG taxes.

**Roth conversion**
: Moving money from a pre-tax account (Traditional) to a post-tax account (Roth). You pay ordinary income tax now, but future growth and qualified withdrawals are tax-free. Most effective in low-income years before Social Security starts or before RMDs kick in at 73.

**Contribution limits**
: IRS annual maximums for 401(k) ($23,500 in 2026, +$7,500 catch-up age 50–59 and 64+, +$11,250 catch-up age 60–63), IRA ($7,000, +$1,000 catch-up age 50+), and HSA ($4,300 individual / $8,550 family). Exceeding limits triggers penalties.
""")


    with tab7:
        _kpi_bar()
        st.subheader("Monte Carlo Simulation")

        mc_model = st.radio(
            "Return model",
            ["CMA Log-Normal (Recommended)", "Standard (Normal) ⚠ Experimental"],
            horizontal=True,
            key="mc_model",
            help=(
                "CMA Log-Normal: log-normal returns with correlated equity/bond factors, "
                "stochastic inflation, and CMA-calibrated default volatilities. "
                "Standard: independent normal draws per account, single volatility parameter. "
                "stochastic inflation, and CMA-calibrated default volatilities."
            ),
        )
        use_v2 = "CMA" in mc_model

        if use_v2:
            st.caption(
                "**CMA Log-Normal model** draws returns from log-normal distributions "
                "(corrects the arithmetic/geometric mean gap, bounds the left tail at −100%). "
                "Equity and bond factors are correlated via Cholesky decomposition — "
                "bad equity years hit all accounts simultaneously. "
                "Inflation is stochastic (~1.5% std dev around your assumed rate) so real spending "
                "power varies across trials. "
                "Default volatilities are calibrated to JPMorgan/Vanguard/BlackRock 10–15yr CMA consensus."
            )
        else:
            st.caption(
                "**Standard model** draws returns independently from a normal distribution "
                "per account per year. Simple and fast; underestimates left-tail risk slightly "
                "because it ignores cross-account correlation and uses fixed inflation. "
                "**Success** = portfolio never hits $0 before your life expectancy."
            )
            st.warning(
                "**Experimental — not recommended.** The Standard model will be deprecated in a future release. "
                "Use CMA Log-Normal for more realistic results.",
                icon="⚠️",
            )

        # --- Parameters ---
        _ret = assumptions.get("retirement_return_rate", 0.065)
        if use_v2:
            # CMA preset selector — when not "User-defined", overrides equity/bond
            # vol+mean for global-rate accounts using a published 2026 CMA set.
            from montecarlo_v2 import CMA_PRESETS as _CMA_PRESETS
            _cma_options = ["User-defined"] + [v["label"] for v in _CMA_PRESETS.values()]
            _cma_keys = [None] + list(_CMA_PRESETS.keys())
            _cma_label = st.selectbox(
                "Capital market assumptions",
                _cma_options,
                index=0,
                key="mc_cma_preset",
                help=(
                    "User-defined uses the Retirement Return Rate ± 3pp equity risk premium "
                    "and the vol sliders below. Presets override both with published forward-looking "
                    "10-year CMAs from major asset managers. Per-account override rates "
                    "(use_global_return_rate=False) are unaffected by presets."
                ),
            )
            mc_cma_preset = _cma_keys[_cma_options.index(_cma_label)]
            if mc_cma_preset is not None:
                _p = _CMA_PRESETS[mc_cma_preset]
                st.caption(
                    f"**{_p['label']}** — equity mean **{_p['equity_mean']:.1%}** "
                    f"({_p['equity_vol']:.1%} vol), bond mean **{_p['bond_mean']:.1%}** "
                    f"({_p['bond_vol']:.1%} vol). {_p['description']} "
                    f"_Overrides the vol sliders below._"
                )
            vol_col1, vol_col2, vol_col3, n_col = st.columns([2, 2, 2, 1])
            with vol_col1:
                mc_equity_vol = st.slider(
                    "Equity Volatility (%)", min_value=5, max_value=30, value=16, step=1,
                    help="Std dev of annual equity returns. CMA consensus: US large-cap ~15–16%.",
                    key="mc_equity_vol",
                ) / 100.0
            with vol_col2:
                mc_bond_vol = st.slider(
                    "Bond Volatility (%)", min_value=1, max_value=15, value=6, step=1,
                    help="Std dev of annual bond returns. CMA consensus: US Agg ~5–6%.",
                    key="mc_bond_vol",
                ) / 100.0
            with vol_col3:
                mc_eq_bond_corr = st.slider(
                    "Equity-Bond Corr (%)", min_value=-20, max_value=40, value=10, step=5,
                    help="Long-run equity/bond correlation. CMA consensus: ~0–15%.",
                    key="mc_eq_bond_corr",
                ) / 100.0
            with n_col:
                mc_n = int(st.number_input(
                    "Trials", min_value=100, max_value=10000, value=1000, step=100, key="mc_n",
                ))
        else:
            vol_col, n_col = st.columns([3, 1])
            with vol_col:
                mc_vol = st.slider(
                    "Equity Volatility (%)", min_value=1, max_value=30, value=12, step=1,
                    help=(
                        "Std dev of annual equity returns. US equities: ~15–17%. "
                        "Balanced 60/40: ~10–12%. Bond volatility = 30% of this value."
                    ),
                    key="mc_vol",
                ) / 100.0
            with n_col:
                mc_n = int(st.number_input(
                    "Trials", min_value=100, max_value=10000, value=1000, step=100, key="mc_n",
                ))

        mc_stock_pct = st.slider(
            "Stock Allocation (%)", min_value=0, max_value=100, value=60, step=5,
            help=(
                "Fraction of each investment account modeled as equities; remainder as bonds. "
                "Controls path volatility only — expected return stays equal to Retirement Return Rate."
            ),
            key="mc_stock_pct",
        ) / 100.0

        if use_v2:
            from montecarlo_v2 import EQUITY_RISK_PREMIUM
            _eq_mean = _ret + (1 - mc_stock_pct) * EQUITY_RISK_PREMIUM
            _bd_mean = _ret - mc_stock_pct * EQUITY_RISK_PREMIUM
            _eff_vol_v2 = mc_stock_pct * mc_equity_vol + (1 - mc_stock_pct) * mc_bond_vol
            st.caption(
                f"Expected portfolio return: **{_ret:.1%}** (matches Retirement Return Rate). "
                f"Component means: equity **{_eq_mean:.1%}**, bond **{_bd_mean:.1%}** "
                f"(3pp equity risk premium preserved). "
                f"Effective portfolio volatility: **{_eff_vol_v2:.1%}**. "
                f"Inflation draws: {assumptions.get('inflation_rate', 0.03):.1%} ± 1.5% per year. "
                f"Geometric mean ≈ {_ret - _eff_vol_v2**2/2:.1%}."
            )
            mc_withdrawal_mode = st.radio(
                "Withdrawal rule",
                ["Constant Real", "Guyton-Klinger Guardrails"],
                horizontal=True,
                key="mc_withdrawal_mode",
                help=(
                    "**Constant Real**: spending grows with drawn inflation every year — "
                    "the classic 'constant purchasing power' approach. "
                    "**Guyton-Klinger Guardrails**: cut spending 10% when the portfolio withdrawal rate "
                    "exceeds 120% of its initial level (Capital Preservation Rule); "
                    "raise spending 10% when it falls below 80% (Prosperity Rule). "
                    "Guardrails substantially improve success rates by letting spending flex "
                    "with market outcomes instead of continuing on a fixed trajectory."
                ),
            )
            mc_withdrawal_mode_key = "guardrails" if mc_withdrawal_mode.startswith("Guyton") else "constant_real"
            if mc_withdrawal_mode_key == "guardrails":
                mc_spending_floor = st.number_input(
                    "Spending floor (today's $, 0 = no floor)",
                    min_value=0,
                    max_value=500_000,
                    value=0,
                    step=1_000,
                    key="mc_spending_floor",
                    help=(
                        "The minimum discretionary living-expense spending allowed, expressed in today's dollars. "
                        "Guardrail cuts will never reduce spending below this real floor. "
                        "Healthcare and taxes are always paid on top of this amount. "
                        "Set to 0 to disable."
                    ),
                )
            else:
                mc_spending_floor = 0.0
        else:
            mc_spending_floor = 0.0
            _eff_vol = mc_stock_pct * mc_vol + (1 - mc_stock_pct) * (mc_vol * 0.30)
            st.caption(
                f"Expected portfolio return: **{_ret:.1%}** (matches Retirement Return Rate). "
                f"Effective portfolio volatility: **{_eff_vol:.1%}** "
                f"({mc_stock_pct:.0%} stocks × {mc_vol:.0%} + "
                f"{1 - mc_stock_pct:.0%} bonds × {mc_vol * 0.30:.0%}). "
                f"Geometric mean ≈ {_ret - _eff_vol**2/2:.1%}."
            )

        mc_crashes = st.checkbox(
            "Include a market crash in the first year of retirement (−20% equity shock)",
            value=False,
            help=(
                "Stress-tests sequence-of-returns risk: in every trial, equity accounts take "
                "an additional −20% drop in the first year of retirement, on top of that year's "
                "normal return draw. Bank accounts and rental property are unaffected."
            ),
            key="mc_crashes",
        )

        if use_v2:
            with st.expander("Variance reduction (advanced)", expanded=False):
                mc_quasi = st.checkbox(
                    "Sobol quasi-random draws (recommended)",
                    value=True,
                    key="mc_quasi",
                    help=(
                        "Replaces pseudorandom Mersenne Twister draws with a scrambled Sobol "
                        "sequence — the sample space fills more uniformly so success-rate and "
                        "percentile estimates converge faster. Falls back to pseudorandom if scipy "
                        "is unavailable."
                    ),
                )
                mc_antithetic = st.checkbox(
                    "Antithetic variates",
                    value=True,
                    key="mc_antithetic",
                    help=(
                        "Each random draw is paired with its negation, cutting standard error for "
                        "statistics that depend monotonically on returns. Cheap, composes with Sobol."
                    ),
                )
        else:
            mc_quasi = True
            mc_antithetic = True

        det_portfolio = ret_df["total_portfolio"].tolist() if not ret_df.empty else []

        # --- Run button ---
        run_key = "mc_result_v2" if use_v2 else "mc_result"
        # Signature of the underlying plan inputs (not the MC knobs). If any of these change
        # after a run — spending, balances, ages, conversions, overrides — the cached MC fan
        # and metrics are stale relative to the freshly-recomputed deterministic baseline,
        # which is exactly what makes the chart and the numbers disagree. Captured at run time
        # and compared on display so such changes also trip the staleness guard below.
        _mc_plan_sig = repr((profile, accounts_at_retirement, assumptions,
                             roth_conversion, spending_overrides))
        if st.button("▶ Run Monte Carlo", type="primary", key="mc_run"):
            with st.spinner(f"Running {mc_n:,} simulations…"):
                if use_v2:
                    result = _mc2.run_monte_carlo_v2(
                        accounts_at_retirement=accounts_at_retirement,
                        profile=profile,
                        assumptions=assumptions,
                        n_runs=mc_n,
                        equity_vol=mc_equity_vol,
                        bond_vol=mc_bond_vol,
                        equity_bond_corr=mc_eq_bond_corr,
                        enable_crashes=mc_crashes,
                        stock_pct=mc_stock_pct,
                        withdrawal_mode=mc_withdrawal_mode_key,
                        spending_floor=mc_spending_floor,
                        roth_conversion=roth_conversion,
                        spending_overrides=spending_overrides,
                        cma_preset=mc_cma_preset,
                        quasi_random=mc_quasi,
                        antithetic=mc_antithetic,
                    )
                else:
                    result = _mc.run_monte_carlo(
                        accounts_at_retirement=accounts_at_retirement,
                        profile=profile,
                        assumptions=assumptions,
                        n_runs=mc_n,
                        volatility=mc_vol,
                        enable_crashes=mc_crashes,
                        stock_pct=mc_stock_pct,
                        roth_conversion=roth_conversion,
                        spending_overrides=spending_overrides,
                    )
            result["plan_sig"] = _mc_plan_sig
            st.session_state[run_key] = result

        # --- Results for selected model ---
        mc_result = st.session_state.get(run_key)
        if mc_result and use_v2:
            # When a preset is selected the engine ignores the vol sliders, so excluding
            # those from the staleness signature avoids spurious re-run prompts after the
            # user slides them while a preset is active.
            _vol_stale = mc_cma_preset is None and (
                mc_result.get("equity_vol") != mc_equity_vol
                or mc_result.get("bond_vol") != mc_bond_vol
            )
            stale = (
                _vol_stale
                or mc_result.get("equity_bond_corr") != mc_eq_bond_corr
                or mc_result.get("n_runs") != mc_n
                or mc_result.get("enable_crashes") != mc_crashes
                or mc_result.get("stock_pct") != mc_stock_pct
                or mc_result.get("withdrawal_mode") != mc_withdrawal_mode_key
                or mc_result.get("spending_floor", 0.0) != mc_spending_floor
                or mc_result.get("cma_preset") != mc_cma_preset
                or mc_result.get("quasi_random", True) != mc_quasi
                or mc_result.get("antithetic", True) != mc_antithetic
                or mc_result.get("plan_sig") != _mc_plan_sig
            )
        elif mc_result:
            stale = (
                mc_result.get("volatility") != mc_vol
                or mc_result.get("n_runs") != mc_n
                or mc_result.get("enable_crashes") != mc_crashes
                or mc_result.get("stock_pct") != mc_stock_pct
                or mc_result.get("plan_sig") != _mc_plan_sig
            )
        else:
            stale = False

        # Suppress stale results entirely rather than merely flagging them: otherwise a
        # prior run's metrics (e.g. a ~100% Guyton-Klinger guardrails success rate) keep
        # showing next to changed-but-unrun settings — making it look like, say, Constant
        # Real itself returned 100%. Show only the refresh prompt until the user re-runs.
        if mc_result and stale:
            st.info("Settings changed — click **▶ Run Monte Carlo** to refresh results.")
        elif mc_result:
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Success Rate", f"{mc_result['success_rate']:.1%}")
            m2.metric("Median at Life Expectancy", f"${mc_result['percentiles'][50][-1]:,.0f}")
            m3.metric("10th Percentile at Life Expectancy", f"${mc_result['percentiles'][10][-1]:,.0f}")
            m4.metric("Trials Depleted", f"{mc_result['n_depleted']:,} / {mc_result['n_runs']:,}")

            # Echo back exactly which withdrawal rule this result was computed under, so the
            # displayed numbers can never be mistaken for a different mode than was run.
            _ran_mode = mc_result.get("withdrawal_mode", "constant_real")
            if _ran_mode == "guardrails":
                _floor = mc_result.get("spending_floor", 0.0)
                _floor_txt = f" with a ${_floor:,.0f} spending floor" if _floor else " (no spending floor — spending can be cut without limit, which inflates the success rate)"
                st.caption(f"↳ Computed with **Guyton-Klinger Guardrails**{_floor_txt}.")
            else:
                st.caption("↳ Computed with **Constant Real** spending (no guardrail flexing).")

            # Adjustment metrics — Kitces-style reframing of pure success rate. Under
            # guardrails "failure" usually means a spending cut, not running dry; these
            # numbers surface how often and how much the retiree's real spending flexed.
            _adj = mc_result.get("adjustment_metrics") or {}
            if _ran_mode == "guardrails" and _adj:
                st.markdown("**Adjustment Profile** — how often guardrails fire & how far spending flexes")
                a1, a2, a3, a4 = st.columns(4)
                a1.metric(
                    "Any Cut",
                    f"{_adj.get('prob_any_cut', 0.0):.0%}",
                    help="Share of trials with ≥1 capital-preservation cut (−10% spending).",
                )
                a2.metric(
                    "Any Raise",
                    f"{_adj.get('prob_any_raise', 0.0):.0%}",
                    help="Share of trials with ≥1 prosperity-rule raise (+10% spending).",
                )
                a3.metric(
                    "Hit Floor",
                    f"{_adj.get('prob_any_floor_hit', 0.0):.0%}",
                    help="Share of trials that ever hit the spending floor (where guardrails could have cut further).",
                )
                a4.metric(
                    "Median Worst Real Spend",
                    f"{_adj.get('min_real_ratio_p50', 1.0):.0%}",
                    help=(
                        "Median across trials of the lowest real-spending year, "
                        "expressed as % of starting real baseline. 80% = a typical trial's "
                        "worst year saw spending drop to 80% of baseline purchasing power."
                    ),
                )
                st.caption(
                    f"Avg cuts per trial: **{_adj.get('avg_cuts_per_trial', 0.0):.1f}** · "
                    f"Avg raises per trial: **{_adj.get('avg_raises_per_trial', 0.0):.1f}** · "
                    f"Avg floor years per trial: **{_adj.get('avg_floor_years_per_trial', 0.0):.1f}** · "
                    f"10th-pctile worst real spend: **{_adj.get('min_real_ratio_p10', 1.0):.0%}** of baseline"
                )

            _mc_failed = mc_result["n_depleted"]
            _mc_total = mc_result["n_runs"]
            _mc_le = profile["life_expectancy"]
            _mc_rate = mc_result["success_rate"]
            _mc_plain = f"In plain terms: {_mc_failed:,} of {_mc_total:,} simulated market sequences run out of money before age {_mc_le}."
            if _mc_failed == 0:
                st.success(f"Your plan survived all {_mc_total:,} simulated market sequences through age {_mc_le}.")
            elif _mc_rate >= 0.90:
                st.success(_mc_plain + " Strong result — solid safety margin.")
            elif _mc_rate >= 0.80:
                st.info(_mc_plain + " Moderate result — consider keeping a spending buffer.")
            elif _mc_rate >= 0.70:
                st.warning(_mc_plain + " Caution — build a contingency plan (part-time work, flexible spending).")
            else:
                st.error(_mc_plain + " Plan needs revision — save more, spend less, or retire later.")

            with st.expander("📖 What makes a good result?", expanded=False):
                st.caption(
                    "Guidance based on financial planning research (Bengen 1994, Pfau, Kitces). "
                    "Success rate = % of simulated market sequences where the portfolio lasted to life expectancy."
                )
                bench_df = pd.DataFrame({
                    "Success Rate": ["≥ 95%", "90 – 95%", "80 – 90%", "70 – 80%", "< 70%"],
                    "Rating":       ["Very Safe", "Strong ✓", "Moderate", "Caution ⚠️", "High Risk ❌"],
                    "Shortfall Odds": ["1 in 20+", "~1 in 10–20", "~1 in 5–10", "~1 in 4–5", "> 1 in 3"],
                    "What to do": [
                        "May be over-funded — consider spending more or retiring earlier",
                        "Standard CFP planning target — solid safety margin",
                        "Acceptable if you can flex spending 10–15% in a bad sequence",
                        "Build a contingency: part-time work, cut discretionary spend",
                        "Plan needs revision — save more, spend less, or retire later",
                    ],
                })
                st.dataframe(bench_df, width='stretch', hide_index=True)
                st.caption(
                    "**10th percentile portfolio at life expectancy**: if this is above $0, your plan "
                    "survives even unlucky market sequences. A 90%+ success rate *and* a positive 10th "
                    "percentile together indicate a robust plan."
                )

            st.plotly_chart(
                _charts.chart_monte_carlo(mc_result, det_portfolio),
                width='stretch',
            )

            mc_sc_name = st.session_state.get("sc_name", "My Scenario")
            if st.button("📌 Add Median to Progress Chart", key="mc_add_to_progress"):
                _mc_tracking = load_tracking(mc_sc_name)
                _mc_tracking["mc_median"] = {
                    "captured_date": date.today().isoformat(),
                    "model": "CMA Log-Normal" if use_v2 else "Standard",
                    "by_age": {
                        str(age): val
                        for age, val in zip(mc_result["ages"], mc_result["percentiles"][50])
                    },
                }
                save_tracking(mc_sc_name, _mc_tracking)
                st.success("MC median saved — visible in the Progress tab.")

            if mc_result["n_depleted"] > 0:
                st.plotly_chart(_charts.chart_mc_depletion(mc_result), width='stretch')
        else:
            st.info("Configure your plan in the sidebar, then click **▶ Run Monte Carlo** to see results.")

        # --- Model comparison (shown when both have been run against the current plan) ---
        mc_v1 = st.session_state.get("mc_result")
        mc_v2 = st.session_state.get("mc_result_v2")
        # Only compare results computed against the current plan inputs; otherwise one model
        # could reflect an older spending/balance set than the other (or the baseline).
        if mc_v1 and mc_v1.get("plan_sig") != _mc_plan_sig:
            mc_v1 = None
        if mc_v2 and mc_v2.get("plan_sig") != _mc_plan_sig:
            mc_v2 = None
        if mc_v1 and mc_v2:
            st.divider()
            st.subheader("Model Comparison")
            st.caption(
                "Both models have been run. Blue = Standard (Normal), Orange = CMA Log-Normal. "
                "Differences reflect log-normal vs normal distributions, correlated factors, and stochastic inflation."
            )
            c1, c2, c3 = st.columns(3)
            c1.metric(
                "Success Rate",
                f"CMA: {mc_v2['success_rate']:.1%}",
                delta=f"{mc_v2['success_rate'] - mc_v1['success_rate']:+.1%} vs Standard",
            )
            c2.metric(
                "Median Portfolio at Life Expectancy",
                f"CMA: ${mc_v2['percentiles'][50][-1]:,.0f}",
                delta=f"${mc_v2['percentiles'][50][-1] - mc_v1['percentiles'][50][-1]:+,.0f} vs Standard",
            )
            c3.metric(
                "10th Percentile at Life Expectancy",
                f"CMA: ${mc_v2['percentiles'][10][-1]:,.0f}",
                delta=f"${mc_v2['percentiles'][10][-1] - mc_v1['percentiles'][10][-1]:+,.0f} vs Standard",
            )
            st.plotly_chart(
                _charts.chart_mc_comparison(mc_v1, mc_v2, det_portfolio),
                width='stretch',
            )

    with tab8:
        _kpi_bar()
        st.subheader("Strategy Optimizer")
        st.caption(
            "The optimizer runs many random combinations of withdrawal strategies and Roth conversion "
            "settings to find the configuration that maximizes your lifetime after-tax income while "
            "minimizing taxes. It reads your current accounts and profile but **never modifies your "
            "scenario**. Use the results as a guide, then apply changes manually in the sidebar."
        )

        # --- Version selector ---
        opt_version = st.radio(
            "Optimizer Version",
            options=["v1 — Roth conversion + withdrawal strategy",
                     "v2 — + SS timing, IRMAA-aware & ACA-aware conversions"],
            index=0,
            horizontal=True,
            key="opt_version",
            help=(
                "**v1** optimizes Roth conversion timing and withdrawal order. "
                "**v2** also optimizes Social Security start age (62–70) and adds "
                "IRMAA-aware and ACA cliff-aware Roth conversion amounts to the search space, "
                "targeting the hard income cliffs that trigger Medicare surcharges or premium subsidy loss."
            ),
        )
        use_v2 = opt_version.startswith("v2")

        # --- Controls ---
        opt_c1, opt_c2, opt_c3 = st.columns([2, 2, 2])
        with opt_c1:
            opt_n = int(st.number_input(
                "Iterations", min_value=100, max_value=5000, value=500, step=100, key="opt_n",
                help="Number of random strategy combinations to evaluate. More = better results but slower.",
            ))
        with opt_c2:
            opt_legacy = st.slider(
                "Legacy Weight (%)", min_value=0, max_value=50, value=20, step=5, key="opt_legacy",
                help="How much to credit remaining portfolio at end of life. 0% = ignore legacy, 50% = weight it heavily.",
            ) / 100.0
        with opt_c3:
            opt_seed = int(st.number_input(
                "Random Seed", min_value=1, max_value=9999, value=42, step=1, key="opt_seed",
                help="Change to explore different random draws with the same iteration count.",
            ))

        if st.button("▶ Run Optimizer", type="primary", key="opt_run"):
            with st.spinner(f"Evaluating {opt_n:,} strategy combinations…"):
                _opt_kwargs = dict(
                    accounts_at_retirement=accounts_at_retirement,
                    profile=profile,
                    assumptions=assumptions,
                    roth_conversion_baseline=roth_conversion,
                    spending_overrides=spending_overrides,
                    n_iterations=opt_n,
                    legacy_weight=opt_legacy,
                    seed=opt_seed,
                )
                if use_v2:
                    _opt_run_result = _opt_v2.run_optimizer_v2(**_opt_kwargs)
                else:
                    _opt_run_result = _opt.run_optimizer(**_opt_kwargs)
                _opt_run_result["_version"] = "v2" if use_v2 else "v1"
            st.session_state["opt_result"] = _opt_run_result

        opt_result = st.session_state.get("opt_result")

        if not opt_result:
            st.info("Configure your plan in the sidebar, then click **▶ Run Optimizer** to see recommendations.")
        else:
            best = opt_result["best_result"]
            base = opt_result["baseline_result"]
            best_df = best["ret_df"]
            base_df = base["ret_df"]
            best_summary = best["summary"]
            base_summary = base["summary"]

            def _lft_spend(df):
                return float(df["actual_after_tax_net"].sum()) if df is not None and not df.empty else 0.0

            def _lft_tax(df):
                return float(df["total_tax"].sum()) if df is not None and not df.empty else 0.0

            def _final_port(df):
                return float(df["total_portfolio"].iloc[-1]) if df is not None and not df.empty else 0.0

            base_spend = _lft_spend(base_df)
            opt_spend = _lft_spend(best_df)
            base_tax = _lft_tax(base_df)
            opt_tax = _lft_tax(best_df)
            base_port = _final_port(base_df)
            opt_port = _final_port(best_df)
            base_depl = base_summary.get("portfolio_depleted_age")
            opt_depl = best_summary.get("portfolio_depleted_age")
            base_roth_total = float(base_df["roth_conversion"].sum()) if base_df is not None and not base_df.empty else 0.0
            opt_roth_total = float(best_df["roth_conversion"].sum()) if best_df is not None and not best_df.empty else 0.0

            # Round all dollar totals to integers so Change = Optimized − Baseline exactly
            # (raw-float arithmetic can produce a ±$1 rounding mismatch vs. individually-rounded cells).
            _b_spend = round(base_spend)
            _o_spend = round(opt_spend)
            _b_tax   = round(base_tax)
            _o_tax   = round(opt_tax)
            _b_port  = round(base_port)
            _o_port  = round(opt_port)
            _b_roth  = round(base_roth_total)
            _o_roth  = round(opt_roth_total)

            # --- Top-line comparison ---
            st.divider()
            st.subheader("Results: Baseline vs. Optimized")
            comparison_data = {
                "Metric": [
                    "Lifetime After-Tax Income",
                    "Lifetime Taxes Paid",
                    "Final Portfolio Value",
                    "Total Roth Conversions",
                    "Portfolio Depleted",
                    "Trials Evaluated",
                ],
                "Baseline": [
                    f"${_b_spend:,}",
                    f"${_b_tax:,}",
                    f"${_b_port:,}",
                    f"${_b_roth:,}",
                    f"Age {base_depl}" if base_depl else "No",
                    "1 (current settings)",
                ],
                "Optimized": [
                    f"${_o_spend:,}",
                    f"${_o_tax:,}",
                    f"${_o_port:,}",
                    f"${_o_roth:,}",
                    f"Age {opt_depl}" if opt_depl else "No",
                    f"{opt_result['n_evaluated']:,} of {opt_n:,}",
                ],
                "Change": [
                    f"${_o_spend - _b_spend:+,} ({(_o_spend - _b_spend) / max(_b_spend, 1):.1%})",
                    f"${_o_tax - _b_tax:+,} ({(_o_tax - _b_tax) / max(_b_tax, 1):.1%})",
                    f"${_o_port - _b_port:+,}",
                    f"${_o_roth - _b_roth:+,}",
                    "—",
                    "—",
                ],
            }
            st.dataframe(pd.DataFrame(comparison_data), width='stretch', hide_index=True)

            # Plain-English explanation of why the optimized strategy wins
            _why_parts = []
            if _o_spend - _b_spend > 1000:
                _why_parts.append(f"**\\${_o_spend - _b_spend:,} more** in lifetime after-tax income")
            if _b_tax - _o_tax > 1000:
                _why_parts.append(f"**\\${_b_tax - _o_tax:,} less** in lifetime taxes")
            if _o_roth - _b_roth > 1000:
                _why_parts.append(f"**\\${_o_roth - _b_roth:,} more** converted to Roth (shrinking future RMDs)")
            if _o_port - _b_port > 5000:
                _why_parts.append(f"**\\${_o_port - _b_port:,} more** left at end of plan")
            if _why_parts:
                st.info("💡 **Why this strategy wins:** The optimized plan delivers " + ", and ".join(_why_parts) + ". Apply the recommended settings below to activate it.")
            elif _b_spend - _o_spend > 1000:
                st.info("💡 The optimizer found no significant improvement over your current settings — your plan is already well-configured.")

            # --- Year-by-year actions ---
            st.divider()
            st.subheader("Recommended Actions by Year")
            st.markdown(
                "🔴 **Red** — action required: sell / withdraw / convert out of this account. &nbsp;"
                "🟢 **Green** — money arriving (Roth conversion receipt). &nbsp;"
                "🟡 **Amber** — expense (taxes, healthcare). &nbsp;"
                "🔵 **Blue** — income columns: SS & Passive Income offsets the portfolio draw; Ordinary Income is total taxable ordinary income driving your bracket. &nbsp;"
                "💚 **Bold green** — **Total Spend**: what you actually have to live on after all costs. "
                "Check: |Portfolio Draw| + SS & Passive Income − |Taxes| − |Healthcare| = Total Spend."
            )
            best_rc = best["roth_conversion"]
            best_ws = best["withdrawal_strategy"]
            actions_df = _opt.build_actions_table(best_df, best_rc, accounts_at_retirement)
            if not actions_df.empty:
                non_dollar = {"Age", "Eff. Tax Rate"}
                act_fmt = {c: "${:,.0f}" for c in actions_df.columns if c not in non_dollar}
                act_fmt["Eff. Tax Rate"] = "{:.1%}"

                _acct_cols    = {a["name"] for a in accounts_at_retirement}
                _expense_cols = {"Taxes", "Healthcare"}
                _income_cols  = {"SS & Passive Income", "Ordinary Income"}
                _draw_cols    = {"Portfolio Draw"}
                _spend_cols   = {"Total Spend"}

                def _actions_style(df: pd.DataFrame) -> pd.DataFrame:
                    out = pd.DataFrame("", index=df.index, columns=df.columns)
                    for col in df.columns:
                        if col in _acct_cols or col in _draw_cols:
                            bold = "; font-weight: 600" if col in _draw_cols else ""
                            out[col] = df[col].apply(lambda v:
                                f"background-color: #ffd6d6; color: #b30000{bold}"
                                if isinstance(v, (int, float)) and v < -0.5
                                else f"background-color: #d6f0d6; color: #1a6b1a{bold}"
                                if isinstance(v, (int, float)) and v > 0.5
                                else ""
                            )
                        elif col in _expense_cols:
                            out[col] = df[col].apply(lambda v:
                                "background-color: #fff0cc; color: #7a5c00"
                                if isinstance(v, (int, float)) and v < -0.5
                                else ""
                            )
                        elif col in _income_cols:
                            out[col] = df[col].apply(lambda v:
                                "background-color: #d6eaf8; color: #1a4f7a"
                                if isinstance(v, (int, float)) and v > 0.5
                                else ""
                            )
                        elif col in _spend_cols:
                            out[col] = df[col].apply(lambda v:
                                "background-color: #b7e4b7; color: #0d5c0d; font-weight: 700"
                                if isinstance(v, (int, float)) and v > 0.5
                                else ""
                            )
                    return out

                st.dataframe(
                    actions_df.style.format(act_fmt, na_rep="—").apply(_actions_style, axis=None),
                    width='stretch',
                    hide_index=True,
                )

            # --- Recommended strategy settings ---
            st.divider()
            st.subheader("Recommended Strategy Settings")
            st.caption("Apply these settings in the sidebar to activate the optimized strategy.")
            _opt_result_version = opt_result.get("_version", "v1")
            if _opt_result_version == "v2":
                desc = _opt_v2.describe_strategy_v2(
                    withdrawal_strategy=best_ws,
                    roth_conversion=best_rc,
                    accounts=accounts_at_retirement,
                    profile_overrides=best.get("profile_overrides", {}),
                    base_profile=profile,
                    cliff_label=best.get("cliff_label"),
                    irmaa_headroom=best.get("irmaa_headroom", 0.0),
                    aca_headroom=best.get("aca_headroom", 0.0),
                    annual_rebalance_gain=best.get("annual_rebalance_gain", 0.0),
                )
            else:
                desc = _opt._describe_strategy(best_ws, best_rc, accounts_at_retirement, best.get("annual_rebalance_gain", 0.0))
            desc_df = pd.DataFrame(
                [{"Setting": k, "Recommended Value": v} for k, v in desc.items()]
            )
            st.dataframe(desc_df, width='stretch', hide_index=True)

            # --- Account balances by year ---
            st.divider()
            st.subheader("Optimized Account Balances by Year")
            bal_df_opt = _opt.build_balances_table(best_df, accounts_at_retirement)
            if not bal_df_opt.empty:
                dollar_bal_cols = [c for c in bal_df_opt.columns if c != "Age"]
                st.dataframe(
                    bal_df_opt.style.format("${:,.0f}", subset=dollar_bal_cols),
                    width='stretch',
                    hide_index=True,
                )

            # --- Full year-by-year detail ---
            st.divider()
            st.subheader("Full Year-by-Year Detail (Optimized)")
            _opt_display = best_df.copy()
            _opt_display["withdrawal_pct"] = (
                _opt_display["spending_target"] / _opt_display["start_portfolio"].clip(lower=1.0)
            )
            opt_detail_cols = [
                "age", "start_portfolio", "spending_target", "net_spending_target", "actual_after_tax_net",
                "withdrawal_pct",
                "ss_income", "rental_income", "investment_income",
                "rmd_amount", "taxable_withdrawal", "traditional_withdrawal", "roth_withdrawal", "bank_withdrawal",
                "roth_conversion", "qual_dividends", "harvest_ltcg", "withdrawal_ltcg",
                "ordinary_income", "ltcg_income", "magi",
                "total_tax", "effective_tax_rate", "federal_irmaa", "healthcare_cost",
                "after_tax_spending", "total_portfolio",
            ]
            opt_detail_cols = [c for c in opt_detail_cols if c in _opt_display.columns]
            if not fixed_net_mode:
                opt_detail_cols = [c for c in opt_detail_cols if c not in ("net_spending_target", "actual_after_tax_net")]
            opt_fmt = {c: "${:,.0f}" for c in opt_detail_cols
                       if c not in ("age", "effective_tax_rate", "withdrawal_pct")}
            opt_fmt["effective_tax_rate"] = "{:.1%}"
            opt_fmt["withdrawal_pct"] = "{:.2%}"
            st.dataframe(
                _opt_display[opt_detail_cols].style.format(opt_fmt, na_rep="—"),
                width='stretch',
            )

            # --- Score distribution ---
            st.divider()
            st.subheader("Score Distribution Across Trials")
            all_scores = opt_result.get("all_scores", [])
            if len(all_scores) > 1:
                score_fig = go.Figure()
                score_fig.add_trace(go.Histogram(
                    x=all_scores, nbinsx=40, marker_color="steelblue", opacity=0.75,
                ))
                score_fig.add_vline(
                    x=base["score"], line_dash="dash", line_color="orange",
                    annotation_text="Baseline", annotation_position="top right",
                )
                score_fig.add_vline(
                    x=best["score"], line_dash="dash", line_color="green",
                    annotation_text="Best Found", annotation_position="top left",
                )
                score_fig.update_layout(
                    title="Optimizer Score Distribution (higher = better)",
                    xaxis_title="Score",
                    yaxis_title="Count",
                    showlegend=False,
                    height=300,
                    margin=dict(t=40, b=30),
                )
                st.plotly_chart(score_fig, width='stretch')
                st.caption(
                    f"Orange dashed = baseline ({base['score']:,.0f}). "
                    f"Green dashed = best found ({best['score']:,.0f}). "
                    f"Score = lifetime after-tax income − 30% × taxes + {opt_legacy:.0%} × final portfolio."
                )


    with tab9:
        st.subheader("Account Overview")
        st.caption(
            "Edit key account parameters directly in the table. "
            "Click **Apply Changes** to update projections, then **Save to Scenario** to persist to disk."
        )
        if "_acct_saved_name" in st.session_state:
            _saved_sc = st.session_state.pop("_acct_saved_name")
            st.success(f"Saved '{_saved_sc}' — projections updated.")

        # Build display dataframe — percentages stored as human-readable values (e.g. 7.0 = 7%)
        _acct_rows = []
        for _a in accounts:
            _acct_rows.append({
                "Name": _a["name"],
                "Type": ACCOUNT_TYPE_LABELS.get(_a["type"], _a["type"]),
                "Current Value ($)": _a["balance"],
                "Current Basis ($)": _a.get("basis", 0.0) if _a["type"] in {"taxable", "reit", "rental_property"} else None,
                "Return Rate (%)": round(_a.get("return_rate", 0.07) * 100, 4),
                "Use Global Rate": bool(_a.get("use_global_return_rate", True)),
                "Qual. Div Yield (%)": round(_a.get("qualified_dividend_yield", 0.0) * 100, 4) if _a["type"] in {"taxable", "reit"} else 0.0,
                "Ord. Income Yield (%)": round(_a.get("ordinary_income_yield", 0.0) * 100, 4) if _a["type"] in {"taxable", "reit"} else 0.0,
                "Total Return (%)": round(
                    (_a.get("return_rate", 0.07)
                     + (_a.get("qualified_dividend_yield", 0.0) if _a["type"] in {"taxable", "reit"} else 0.0)
                     + (_a.get("ordinary_income_yield", 0.0) if _a["type"] in {"taxable", "reit"} else 0.0)) * 100, 4
                ),
            })
        _acct_df = pd.DataFrame(_acct_rows)

        _acct_col_cfg = {
            "Name": st.column_config.TextColumn(disabled=True),
            "Type": st.column_config.TextColumn(disabled=True),
            "Current Value ($)": st.column_config.NumberColumn(min_value=0, format="$%,.0f"),
            "Current Basis ($)": st.column_config.NumberColumn(
                min_value=0, format="$%,.0f",
                help="Cost basis — applies to taxable brokerage, REIT, and rental property accounts only. Blank (N/A) for retirement accounts.",
            ),
            "Return Rate (%)": st.column_config.NumberColumn(
                min_value=0.0, max_value=30.0, format="%.2f%%",
                help=(
                    "Capital appreciation only — does NOT include qualified dividend yield or ordinary income yield. "
                    "Full return = Return Rate + Qual. Div Yield + Ord. Income Yield (see Total Return column)."
                ),
            ),
            "Use Global Rate": st.column_config.CheckboxColumn(
                help="When checked, the global Retirement Return Rate is used during the withdrawal phase instead of this account's rate",
            ),
            "Qual. Div Yield (%)": st.column_config.NumberColumn(
                min_value=0.0, max_value=20.0, format="%.2f%%",
                help="Annual qualified dividend yield (taxable brokerage / REIT accounts)",
            ),
            "Ord. Income Yield (%)": st.column_config.NumberColumn(
                min_value=0.0, max_value=20.0, format="%.2f%%",
                help="Annual ordinary income yield — e.g. bond interest, non-qualified dividends (taxable / REIT accounts)",
            ),
            "Total Return (%)": st.column_config.NumberColumn(
                disabled=True, format="%.2f%%",
                help="Calculated: Return Rate + Qual. Div Yield + Ord. Income Yield. This is the full expected annual return for the account.",
            ),
        }

        _edited_accts = st.data_editor(
            _acct_df,
            column_config=_acct_col_cfg,
            width='stretch',
            hide_index=True,
            num_rows="fixed",
            key="acct_table_editor",
        )

        _btn_col1, _btn_col2, _ = st.columns([2, 2, 8])

        with _btn_col1:
            if st.button("Apply Changes", key="acct_apply", help="Update projections with edited values (does not save to disk)"):
                for _i, _a in enumerate(st.session_state.accounts):
                    _row = _edited_accts.iloc[_i]
                    _a["balance"] = float(_row["Current Value ($)"])
                    if _a["type"] in {"taxable", "reit", "rental_property"}:
                        _a["basis"] = float(_row["Current Basis ($)"])
                    _a["return_rate"] = _dec(float(_row["Return Rate (%)"]))
                    _a["use_global_return_rate"] = bool(_row["Use Global Rate"])
                    if _a["type"] in {"taxable", "reit"}:
                        _a["qualified_dividend_yield"] = _dec(float(_row["Qual. Div Yield (%)"]))
                        _a["ordinary_income_yield"] = _dec(float(_row["Ord. Income Yield (%)"]))
                    else:
                        _a["qualified_dividend_yield"] = 0.0
                        _a["ordinary_income_yield"] = 0.0
                # Clear editor state so the table reinitialises from the updated accounts
                if "acct_table_editor" in st.session_state:
                    del st.session_state["acct_table_editor"]
                st.rerun()

        with _btn_col2:
            if st.button("💾 Save to Scenario", key="acct_save", type="primary"):
                # Apply edits first, then save
                for _i, _a in enumerate(st.session_state.accounts):
                    _row = _edited_accts.iloc[_i]
                    _a["balance"] = float(_row["Current Value ($)"])
                    if _a["type"] in {"taxable", "reit", "rental_property"}:
                        _a["basis"] = float(_row["Current Basis ($)"])
                    _a["return_rate"] = _dec(float(_row["Return Rate (%)"]))
                    _a["use_global_return_rate"] = bool(_row["Use Global Rate"])
                    if _a["type"] in {"taxable", "reit"}:
                        _a["qualified_dividend_yield"] = _dec(float(_row["Qual. Div Yield (%)"]))
                        _a["ordinary_income_yield"] = _dec(float(_row["Ord. Income Yield (%)"]))
                    else:
                        _a["qualified_dividend_yield"] = 0.0
                        _a["ordinary_income_yield"] = 0.0
                _sc_name = st.session_state.get("sc_name", "My Scenario")
                try:
                    save_scenario(
                        _sc_name,
                        st.session_state.profile,
                        st.session_state.assumptions,
                        st.session_state.accounts,
                        st.session_state.roth_conversion,
                    )
                    set_last_used_scenario(_sc_name)
                    if "acct_table_editor" in st.session_state:
                        del st.session_state["acct_table_editor"]
                    st.session_state["_acct_saved_name"] = _sc_name
                    st.rerun()
                except Exception as _e:
                    st.error(str(_e))


if __name__ == "__main__":
    main()
