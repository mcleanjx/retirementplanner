"""Simplified mode: 5-step wizard + 4-panel results."""
import uuid
import copy

import streamlit as st
import plotly.graph_objects as go
import pandas as pd

from projections import project_accumulation
from withdrawals import simulate_retirement
from constants import RMD_START_AGE

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
# Wizard state init
# ---------------------------------------------------------------------------

def _init_wizard():
    if "wizard" not in st.session_state:
        p = st.session_state.get("profile", {})
        accts = st.session_state.get("accounts", [])
        total_savings = sum(a.get("balance", 0) for a in accts)
        total_contrib = sum(a.get("annual_contribution", 0) for a in accts)
        st.session_state.wizard = {
            # Step 1
            "current_age": int(p.get("current_age", 40)),
            "retirement_age": int(p.get("retirement_age", 65)),
            "life_expectancy": int(p.get("life_expectancy", 90)),
            "married": p.get("filing_status") == "married_filing_jointly",
            "spouse_age": int(p.get("spouse_age", 40)),
            # Step 2
            "total_savings": float(total_savings or 200000),
            "split_savings": False,
            "trad_savings": float(total_savings or 200000),
            "roth_savings": 0.0,
            "other_savings": 0.0,
            "annual_savings": float(total_contrib or 15000),
            # Step 3
            "has_ss": True,
            "ss_benefit": float(p.get("social_security_benefit", 24000)),
            "ss_start_age": int(p.get("social_security_start_age", 67)),
            "spouse_ss_benefit": float(p.get("spouse_ss_benefit", 0)),
            "spouse_ss_start_age": int(p.get("spouse_ss_start_age", 67)),
            "has_pension": False,
            "pension": 0.0,
            "has_rental": False,
            "rental_income": 0.0,
            # Step 4
            "spending_mode": "pct",
            "spending_pct": 80,
            "spending_dollar": int(p.get("current_income", 100000) * 0.80) or 70000,
            "current_income": float(p.get("current_income", 100000)),
            "investment_style": "Moderate",
        }
    if "wizard_step" not in st.session_state:
        st.session_state.wizard_step = 1
    if "wizard_complete" not in st.session_state:
        st.session_state.wizard_complete = False


# ---------------------------------------------------------------------------
# Build plan from wizard data
# ---------------------------------------------------------------------------

def _build_simple_plan(w: dict, extra_savings: float = 0.0,
                       retirement_age_delta: int = 0,
                       spending_delta: float = 0.0) -> tuple:
    """Convert wizard answers → (profile, assumptions, accounts, roth_conversion)."""
    ret_age = max(w["current_age"] + 1, w["retirement_age"] + retirement_age_delta)
    ret_age = min(ret_age, 80)

    spending_target = (
        w["current_income"] * w["spending_pct"] / 100
        if w["spending_mode"] == "pct"
        else float(w["spending_dollar"])
    )
    spending_target = max(0.0, spending_target + spending_delta)

    return_rate = _RETURN_BY_STYLE[w["investment_style"]]

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
        "state": "other",
        "state_tax_rate": _SIMPLE_DEFAULTS["state_tax_rate"],
        "current_income": w["current_income"],
        "social_security_benefit": w["ss_benefit"] if w["has_ss"] else 0.0,
        "social_security_start_age": w["ss_start_age"],
        "pre_medicare_healthcare": _SIMPLE_DEFAULTS["pre_medicare_healthcare"],
        "post_medicare_healthcare": _SIMPLE_DEFAULTS["post_medicare_healthcare"],
    }
    if w["married"]:
        profile.update({
            "spouse_age": w["spouse_age"],
            "spouse_retirement_age": ret_age,
            "spouse_ss_benefit": w["spouse_ss_benefit"],
            "spouse_ss_start_age": w["spouse_ss_start_age"],
            "survivor_spending_reduction": 0.25,
        })

    assumptions = {
        "inflation_rate": _SIMPLE_DEFAULTS["inflation_rate"],
        "bracket_inflation_rate": _SIMPLE_DEFAULTS["bracket_inflation_rate"],
        "retirement_return_rate": return_rate,
        "spending_mode": "fixed",
        "annual_spending_target": spending_target,
        "safe_withdrawal_rate": 0.04,
        "withdrawal_strategy": _SIMPLE_DEFAULTS["withdrawal_strategy"],
    }

    accounts = []
    if w["split_savings"]:
        if w["trad_savings"] > 0:
            accounts.append(_make_acct("Tax-Deferred (401k/IRA)", "traditional_401k",
                                       w["trad_savings"], w["annual_savings"], return_rate))
        if w["roth_savings"] > 0:
            accounts.append(_make_acct("Roth Savings", "roth_ira",
                                       w["roth_savings"], 0.0, return_rate, basis=w["roth_savings"]))
        if w["other_savings"] > 0:
            accounts.append(_make_acct("Other Investments", "taxable",
                                       w["other_savings"], 0.0, return_rate,
                                       basis=w["other_savings"] * 0.7))
        if not accounts:
            accounts.append(_make_acct("Retirement Savings", "traditional_401k",
                                       w["total_savings"], w["annual_savings"] + extra_savings, return_rate))
        else:
            accounts[0]["annual_contribution"] += extra_savings
    else:
        accounts.append(_make_acct("Retirement Savings", "traditional_401k",
                                   w["total_savings"], w["annual_savings"] + extra_savings, return_rate))

    if w.get("has_rental") and w.get("rental_income", 0) > 0:
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


def _make_acct(name, acct_type, balance, contribution, return_rate, basis=0.0):
    return {
        "id": f"simple_{acct_type}",
        "name": name,
        "type": acct_type,
        "balance": float(balance),
        "basis": float(basis),
        "annual_contribution": float(contribution),
        "contribution_growth_rate": 0.0,
        "return_rate": float(return_rate),
        "employer_match_percent": 0.0,
        "employer_match_limit": 0.0,
        "qualified_dividend_yield": 0.0 if acct_type != "taxable" else 0.015,
        "ordinary_income_yield": 0.0,
        "net_annual_rental_income": 0.0,
        "use_global_return_rate": False,
    }


def _run_projection(profile, assumptions, accounts, rc):
    try:
        acc_df, accts_at_ret = project_accumulation(accounts, profile, assumptions)
        for a in accts_at_ret:
            a["use_global_return_rate"] = False
        ret_df, summary = simulate_retirement(accts_at_ret, profile, assumptions, rc, {})
        return acc_df, ret_df, summary
    except Exception as e:
        return pd.DataFrame(), pd.DataFrame(), {"error": str(e)}


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
    labels = ["About You", "Your Savings", "Retirement Income", "Your Goal", "Review"]
    cols = st.columns(len(labels))
    for i, (col, label) in enumerate(zip(cols, labels), 1):
        active = i == step
        done = i < step
        color = "#2b6cb0" if active else ("#48bb78" if done else "#cbd5e0")
        weight = "700" if active else "400"
        col.markdown(
            f"<div style='text-align:center;font-size:0.78rem;color:{color};"
            f"font-weight:{weight};border-bottom:2.5px solid {color};padding-bottom:4px;'>"
            f"{'✓ ' if done else ''}{label}</div>",
            unsafe_allow_html=True,
        )
    st.write("")


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


def _step2():
    w = st.session_state.wizard
    st.subheader("Step 2 — Your Savings")

    st.caption("Add up all your retirement accounts: 401(k), IRA, Roth IRA, and investment accounts.")
    w["total_savings"] = float(st.number_input(
        "Total retirement savings today ($)", 0, 10_000_000,
        int(w["total_savings"]), 10000, key="wiz_total_sav"
    ))

    w["split_savings"] = st.toggle(
        "Split by account type (optional — helps accuracy)",
        value=w["split_savings"], key="wiz_split"
    )
    if w["split_savings"]:
        st.caption("Enter your balance in each bucket. They should add up to your total above.")
        cs1, cs2, cs3 = st.columns(3)
        w["trad_savings"] = float(cs1.number_input(
            "Tax-deferred (401k/IRA) ($)", 0, 10_000_000, int(w["trad_savings"]), 10000, key="wiz_trad"
        ))
        w["roth_savings"] = float(cs2.number_input(
            "Roth / tax-free ($)", 0, 10_000_000, int(w["roth_savings"]), 10000, key="wiz_roth"
        ))
        w["other_savings"] = float(cs3.number_input(
            "Taxable brokerage / other ($)", 0, 10_000_000, int(w["other_savings"]), 10000, key="wiz_other"
        ))
        entered_total = w["trad_savings"] + w["roth_savings"] + w["other_savings"]
        if abs(entered_total - w["total_savings"]) > 1000:
            st.warning(f"Split total (${entered_total:,.0f}) differs from total savings (${w['total_savings']:,.0f}).")

    w["annual_savings"] = float(st.number_input(
        "How much are you saving for retirement each year? ($)",
        0, 200000, int(w["annual_savings"]), 500,
        help="Include your contributions plus any employer match.",
        key="wiz_ann_sav"
    ))

    if _nav_buttons(2, next_label="Next →"):
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
    st.caption(
        f"We'll use a **{rate*100:.0f}% annual return** assumption. "
        "Conservative = bonds-heavy; Aggressive = stocks-heavy."
    )

    if _nav_buttons(4, next_label="See My Results →"):
        st.session_state.wizard_step = 5
        st.session_state.wizard_complete = True
        st.rerun()


def _step5_review():
    """Confirm screen before showing results."""
    w = st.session_state.wizard
    st.subheader("Step 5 — Review")

    spending_target = (
        w["current_income"] * w["spending_pct"] / 100
        if w["spending_mode"] == "pct"
        else float(w["spending_dollar"])
    )

    st.markdown(f"""
**Based on what you told us:**
- You'll retire at **{w['retirement_age']}** with a plan running to age **{w['life_expectancy']}**
- Current savings: **${w['total_savings']:,.0f}**, saving **${w['annual_savings']:,.0f}/year**
- Social Security: **${w['ss_benefit']:,.0f}/year** starting at **{w['ss_start_age']}**
{f"- Spouse SS: **${w['spouse_ss_benefit']:,.0f}/year**" if w['married'] and w['has_ss'] else ""}
{f"- Pension: **${w['pension']:,.0f}/year**" if w.get('has_pension') and w.get('pension',0) > 0 else ""}
{f"- Rental income: **${w['rental_income']:,.0f}/year**" if w.get('has_rental') and w.get('rental_income',0) > 0 else ""}
- Retirement spending goal: **${spending_target:,.0f}/year** (today's dollars)
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
            st.rerun()


def _show_wizard():
    step = st.session_state.wizard_step
    _progress_bar(step)
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


def _render_score_card(score: int, surplus: float, profile: dict, depletion_age):
    bg, fg, label = _score_color(score)
    le = profile["life_expectancy"]
    ret = profile["retirement_age"]

    if depletion_age:
        detail = (
            f"Your portfolio runs out at age **{depletion_age}** — "
            f"{le - depletion_age} years short of your plan."
        )
    elif surplus > 0:
        detail = f"You have a projected **${surplus:,.0f} surplus** remaining at age {le}."
    else:
        detail = f"Your portfolio lasts through age {le}."

    display_score = min(score, 100)

    st.markdown(
        f"""
        <div style="background:{bg};border-radius:16px;padding:1.5rem 2rem;
                    text-align:center;margin-bottom:1rem;">
            <div style="font-size:0.9rem;color:{fg};font-weight:600;
                        letter-spacing:0.05em;text-transform:uppercase;">
                Your Retirement Score
            </div>
            <div style="font-size:4rem;font-weight:800;color:{fg};line-height:1.1;">
                {display_score}%
            </div>
            <div style="font-size:1.3rem;font-weight:700;color:{fg};">
                {label}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(detail)


def _render_portfolio_curve(acc_df, ret_df, profile):
    st.subheader("Will My Money Last?")
    ages, balances = [], []

    if not acc_df.empty:
        for age_val, grp in acc_df.groupby("age"):
            ages.append(int(age_val))
            balances.append(float(grp["balance"].sum()))

    if not ret_df.empty:
        for _, row in ret_df.iterrows():
            ages.append(int(row["age"]))
            balances.append(float(row["total_portfolio"]))

    if not ages:
        st.info("No projection data available.")
        return

    fig = go.Figure()
    colors = [
        "#2b6cb0" if b > 0 else "#e53e3e"
        for b in balances
    ]
    fig.add_trace(go.Scatter(
        x=ages, y=balances,
        mode="lines",
        fill="tozeroy",
        fillcolor="rgba(43,108,176,0.15)",
        line=dict(color="#2b6cb0", width=2.5),
        name="Portfolio Balance",
        hovertemplate="Age %{x}: $%{y:,.0f}<extra></extra>",
    ))
    fig.add_hline(y=0, line_dash="dash", line_color="#e53e3e", line_width=1.5,
                  annotation_text="$0", annotation_position="right")

    ret_age = profile["retirement_age"]
    fig.add_vline(x=ret_age, line_dash="dot", line_color="#718096",
                  annotation_text=f"Retire ({ret_age})", annotation_position="top right")

    fig.update_layout(
        height=320,
        margin=dict(l=0, r=0, t=10, b=0),
        yaxis=dict(tickprefix="$", tickformat=",.0f", title=None),
        xaxis=dict(title="Age"),
        showlegend=False,
        plot_bgcolor="white",
        paper_bgcolor="white",
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_income_sources(ret_df, profile):
    if ret_df.empty:
        return
    st.subheader("Where Will My Income Come From?")

    ret_age = profile["retirement_age"]
    le = profile["life_expectancy"]

    decades = []
    for start in range(ret_age, le, 10):
        end = min(start + 10, le + 1)
        label = f"Age {start}s" if end - start > 5 else f"Age {start}–{end-1}"
        mask = (ret_df["age"] >= start) & (ret_df["age"] < end)
        chunk = ret_df[mask]
        if chunk.empty:
            continue
        ss = chunk["ss_income"].mean()
        rental = chunk["rental_income"].mean()
        portfolio = chunk["after_tax_spending"].mean() - ss - rental
        portfolio = max(0.0, portfolio)
        decades.append({"label": label, "ss": ss, "rental": rental, "portfolio": portfolio})

    if not decades:
        return

    labels = [d["label"] for d in decades]
    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="Portfolio", x=labels, y=[d["portfolio"] for d in decades],
        marker_color="#2b6cb0",
        hovertemplate="%{y:$,.0f}<extra>Portfolio</extra>",
    ))
    fig.add_trace(go.Bar(
        name="Social Security", x=labels, y=[d["ss"] for d in decades],
        marker_color="#48bb78",
        hovertemplate="%{y:$,.0f}<extra>Social Security</extra>",
    ))
    fig.add_trace(go.Bar(
        name="Other Income", x=labels, y=[d["rental"] for d in decades],
        marker_color="#ed8936",
        hovertemplate="%{y:$,.0f}<extra>Other Income</extra>",
    ))
    fig.update_layout(
        barmode="stack",
        height=280,
        margin=dict(l=0, r=0, t=10, b=0),
        yaxis=dict(tickprefix="$", tickformat=",.0f", title=None),
        xaxis=dict(title=None),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        plot_bgcolor="white",
        paper_bgcolor="white",
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_levers(base_score: int, base_surplus: float, base_depletion, profile, w):
    st.subheader("Move the Needle")
    st.caption("Adjust these sliders to see how small changes affect your score.")

    c1, c2, c3 = st.columns(3)
    extra_savings = c1.slider(
        "Save more per year ($)", 0, 10000, 0, 500, key="lever_savings",
        help="Additional annual retirement contribution"
    )
    ret_delta = c2.slider(
        "Retire later (years)", 0, 5, 0, 1, key="lever_retire",
        help="Delay retirement by this many years"
    )
    spend_delta = c3.slider(
        "Spend less per year ($)", 0, 20000, 0, 1000, key="lever_spend",
        help="Reduce annual retirement spending by this amount"
    )

    if extra_savings > 0 or ret_delta > 0 or spend_delta > 0:
        profile_adj, assumptions_adj, accounts_adj, rc_adj = _build_simple_plan(
            w,
            extra_savings=float(extra_savings),
            retirement_age_delta=ret_delta,
            spending_delta=-float(spend_delta),
        )
        _, ret_df_adj, summary_adj = _run_projection(profile_adj, assumptions_adj, accounts_adj, rc_adj)
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


def _render_assumptions_note(w):
    with st.expander("What assumptions did we use?"):
        rate = _RETURN_BY_STYLE[w["investment_style"]]
        st.markdown(f"""
| Assumption | Value |
|---|---|
| Inflation rate | 2.5% |
| Investment return ({w['investment_style']}) | {rate*100:.0f}% nominal |
| Pre-Medicare healthcare | $15,000/yr |
| Post-Medicare healthcare | $12,000/yr |
| State tax rate | 4.5% (national average) |
| Withdrawal strategy | Tax-efficient |
| Social Security COLA | 2.5% annually |

These are reasonable defaults. Switch to **Advanced Mode** to customize any of these.
        """)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_simplified_mode():
    _init_wizard()

    if not st.session_state.wizard_complete:
        _show_wizard()
        return

    w = st.session_state.wizard
    profile, assumptions, accounts, rc = _build_simple_plan(w)
    acc_df, ret_df, summary = _run_projection(profile, assumptions, accounts, rc)

    if "error" in summary:
        st.error(f"Projection error: {summary['error']}")
        if st.button("← Back to Wizard"):
            st.session_state.wizard_complete = False
            st.session_state.wizard_step = 1
            st.rerun()
        return

    score, surplus = _compute_score(ret_df, summary, profile)
    depletion = summary.get("portfolio_depleted_age")

    # ── Panel 1: Score card ────────────────────────────────────────────────
    _render_score_card(score, surplus, profile, depletion)

    st.divider()

    # ── Panels 2 & 3 side-by-side ─────────────────────────────────────────
    col_left, col_right = st.columns([3, 2])
    with col_left:
        _render_portfolio_curve(acc_df, ret_df, profile)
    with col_right:
        _render_income_sources(ret_df, profile)

    st.divider()

    # ── Panel 4: Levers ───────────────────────────────────────────────────
    _render_levers(score, surplus, depletion, profile, w)

    st.divider()

    # ── Edit / assumptions / bridge ────────────────────────────────────────
    c_edit, c_adv = st.columns(2)
    with c_edit:
        if st.button("← Edit My Answers", use_container_width=True):
            st.session_state.wizard_complete = False
            st.session_state.wizard_step = 1
            st.rerun()
    with c_adv:
        if st.button("Switch to Advanced Mode →", use_container_width=True, type="primary"):
            _sync_to_advanced(profile, assumptions, accounts, rc)
            st.session_state.ui_mode = "advanced"
            st.rerun()

    _render_assumptions_note(w)


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
    for a in accounts:
        aid = a["id"]
        st.session_state[f"chk_global_{aid}"] = False
