import pandas as pd
import plotly.graph_objects as go

TAX_BUCKET_COLORS = {
    "pre_tax":     "#4C72B0",
    "roth":        "#55A868",
    "taxable":     "#DD8452",
    "real_estate": "#8172B2",
    "cash":        "#A0A0A0",
}

# Per-account shade sequences for drawdown chart — darker → lighter within each bucket
TAX_BUCKET_SHADES = {
    "pre_tax":     ["#1a3a6b", "#2d5a9e", "#4C72B0", "#6e96cc", "#9dc2e0", "#c5dff0"],
    "roth":        ["#1a5c2a", "#2d8040", "#55A868", "#7dc290", "#a8d8b8", "#ccecda"],
    "taxable":     ["#7a2800", "#b04010", "#DD8452", "#e8a07a", "#f0c4a0", "#f8e2cc"],
    "real_estate": ["#3a2060", "#5a3890", "#8172B2", "#a096cc", "#c4b8e0", "#e0d8f0"],
    "cash":        ["#404040", "#686868", "#A0A0A0", "#c0c0c0", "#d8d8d8"],
}

INCOME_COLORS = {
    "ss_income":          "#2ca02c",
    "rental_income":      "#8172B2",
    "investment_income":  "#DD8452",
    "rmd_amount":         "#4C72B0",
    "taxable_withdrawal":    "#e07b39",
    "traditional_withdrawal":"#6a9fd8",
    "roth_withdrawal":       "#55A868",
    "bank_withdrawal":       "#A0A0A0",
    "roth_conversion":    "#bcbd22",
    "harvest_ltcg":       "#17becf",
    "taxes":              "#d62728",
}


def _fmt(val: float) -> str:
    return f"${val:,.0f}"


def chart_accumulation(acc_df: pd.DataFrame) -> go.Figure:
    """Stacked area chart of account balances during accumulation."""
    fig = go.Figure()
    # Group by tax bucket for stacking
    bucket_order = ["pre_tax", "roth", "taxable", "real_estate", "cash"]
    for bucket in bucket_order:
        bdf = acc_df[acc_df["tax_bucket"] == bucket].groupby("age")["balance"].sum().reset_index()
        if bdf.empty:
            continue
        label = {"pre_tax": "Pre-Tax", "roth": "Roth / Tax-Free",
                 "taxable": "Taxable", "real_estate": "Real Estate",
                 "cash": "Cash / Bank"}[bucket]
        fig.add_trace(go.Scatter(
            x=bdf["age"], y=bdf["balance"],
            name=label,
            mode="lines",
            stackgroup="one",
            fillcolor=TAX_BUCKET_COLORS[bucket],
            line=dict(color=TAX_BUCKET_COLORS[bucket], width=1),
            hovertemplate=f"<b>{label}</b><br>Age: %{{x}}<br>Balance: %{{y:$,.0f}}<extra></extra>",
        ))
    fig.update_layout(
        title="Portfolio Growth During Accumulation",
        xaxis_title="Age",
        yaxis_title="Balance",
        yaxis_tickformat="$,.0f",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    return fig


def chart_composition_at_retirement(accounts_at_retirement: list[dict]) -> go.Figure:
    """Donut chart of portfolio composition at retirement."""
    labels, values, colors = [], [], []
    bucket_color = TAX_BUCKET_COLORS
    type_to_bucket = {
        "traditional_401k": "pre_tax", "traditional_ira": "pre_tax",
        "roth_401k": "roth", "roth_ira": "roth", "hsa": "roth",
        "taxable": "taxable", "reit": "taxable",
        "rental_property": "real_estate", "bank": "cash",
    }
    for a in accounts_at_retirement:
        if a["balance"] > 0:
            labels.append(a["name"])
            values.append(a["balance"])
            bucket = type_to_bucket.get(a["type"], "taxable")
            colors.append(bucket_color[bucket])

    fig = go.Figure(go.Pie(
        labels=labels, values=values,
        marker=dict(colors=colors),
        hole=0.45,
        hovertemplate="<b>%{label}</b><br>%{value:$,.0f} (%{percent})<extra></extra>",
    ))
    fig.update_layout(title="Portfolio Composition at Retirement")
    return fig


def chart_drawdown(
    ret_df: pd.DataFrame,
    accounts_at_retirement: list[dict],
    inflation: float = 0.0,
    current_age: int = 0,
) -> go.Figure:
    """Stacked area chart of remaining balances during retirement.

    When inflation and current_age are provided, overlays a dashed line showing
    the total portfolio in today's (current-year) purchasing power.
    """
    fig = go.Figure()
    type_to_bucket = {
        "traditional_401k": "pre_tax", "traditional_ira": "pre_tax",
        "roth_401k": "roth", "roth_ira": "roth", "hsa": "roth",
        "taxable": "taxable", "reit": "taxable",
        "rental_property": "real_estate", "bank": "cash",
    }
    bucket_usage: dict[str, int] = {}
    for a in accounts_at_retirement:
        col = f"bal_{a['name'].replace(' ', '_')}"
        if col not in ret_df.columns:
            continue
        bucket = type_to_bucket.get(a["type"], "taxable")
        shade_idx = bucket_usage.get(bucket, 0)
        shades = TAX_BUCKET_SHADES[bucket]
        color = shades[shade_idx % len(shades)]
        bucket_usage[bucket] = shade_idx + 1
        fig.add_trace(go.Scatter(
            x=ret_df["age"], y=ret_df[col],
            name=a["name"],
            mode="lines",
            stackgroup="one",
            fillcolor=color,
            line=dict(color=color, width=1),
            hovertemplate=f"<b>{a['name']}</b><br>Age: %{{x}}<br>Balance: %{{y:$,.0f}}<extra></extra>",
        ))
    # Real-dollar overlay: deflate nominal portfolio back to today's purchasing power
    if inflation > 0 and current_age > 0 and "total_portfolio" in ret_df.columns:
        real_port = ret_df["total_portfolio"] / (1 + inflation) ** (ret_df["age"] - current_age)
        fig.add_trace(go.Scatter(
            x=ret_df["age"], y=real_port,
            name="Portfolio (today's $)",
            mode="lines",
            line=dict(color="black", width=2, dash="dash"),
            hovertemplate="<b>Portfolio (today's $)</b><br>Age: %{x}<br>%{y:$,.0f}<extra></extra>",
        ))
    fig.update_layout(
        title="Portfolio Drawdown During Retirement",
        xaxis_title="Age",
        yaxis_title="Remaining Balance",
        yaxis_tickformat="$,.0f",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    return fig


def chart_annual_income(
    ret_df: pd.DataFrame,
    inflation: float = 0.0,
    retirement_age: int = 0,
) -> go.Figure:
    """Stacked bar chart of annual income sources in retirement.

    When inflation and retirement_age are provided, overlays a dashed line showing
    after-tax spending in retirement-year purchasing power (flat = real value preserved).
    """
    fig = go.Figure()

    income_sources = [
        ("ss_income",          "Social Security"),
        ("rental_income",      "Rental Income"),
        ("investment_income",  "Dividends / Interest"),
        ("rmd_amount",         "RMDs (Traditional)"),
        ("taxable_withdrawal",    "Taxable Account Sale"),
        ("traditional_withdrawal","Traditional (Discretionary)"),
        ("roth_withdrawal",       "Roth Withdrawal"),
        ("bank_withdrawal",       "Bank / Cash"),
        ("roth_conversion",    "Roth Conversion"),
        ("harvest_ltcg",       "Tax-Gain Harvest (0% LTCG, no cash)"),
    ]

    for col, label in income_sources:
        if col in ret_df.columns and ret_df[col].sum() > 0:
            fig.add_trace(go.Bar(
                x=ret_df["age"], y=ret_df[col],
                name=label,
                marker_color=INCOME_COLORS.get(col, "#aaa"),
                hovertemplate=f"<b>{label}</b><br>Age: %{{x}}<br>Amount: %{{y:$,.0f}}<extra></extra>",
            ))

    # Taxes as negative bars
    fig.add_trace(go.Bar(
        x=ret_df["age"], y=-ret_df["total_tax"],
        name="Taxes",
        marker_color=INCOME_COLORS["taxes"],
        hovertemplate="<b>Taxes</b><br>Age: %{x}<br>Amount: %{y:$,.0f}<extra></extra>",
    ))

    # After-tax spending as line overlay
    fig.add_trace(go.Scatter(
        x=ret_df["age"], y=ret_df["after_tax_spending"],
        name="After-Tax Spending",
        mode="lines+markers",
        line=dict(color="black", width=2, dash="dot"),
        hovertemplate="<b>After-Tax Spending</b><br>Age: %{x}<br>%{y:$,.0f}<extra></extra>",
    ))

    # Real-dollar overlay: deflate nominal spending back to retirement-year purchasing power.
    # A flat line means real spending is preserved; a falling line means erosion.
    if inflation > 0 and retirement_age > 0 and "after_tax_spending" in ret_df.columns:
        real_spend = ret_df["after_tax_spending"] / (1 + inflation) ** (ret_df["age"] - retirement_age)
        fig.add_trace(go.Scatter(
            x=ret_df["age"], y=real_spend,
            name="After-Tax Spending (retirement-yr $)",
            mode="lines",
            line=dict(color="gray", width=2, dash="dashdot"),
            hovertemplate="<b>Spending (retirement-yr $)</b><br>Age: %{x}<br>%{y:$,.0f}<extra></extra>",
        ))

    fig.update_layout(
        title="Annual Retirement Income & Taxes",
        xaxis_title="Age",
        yaxis_title="Amount ($)",
        yaxis_tickformat="$,.0f",
        barmode="relative",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    return fig


def chart_spending_coverage(ret_df: pd.DataFrame) -> go.Figure:
    """
    Stacked bar chart showing how spending is funded.
    Organic income (SS, rental, dividends) and traditional distributions (RMDs)
    are shown individually. All asset liquidations (taxable sales, Roth draws,
    bank draws) are grouped as a single 'Portfolio Drawdown' bar so it is clear
    how much of spending requires selling assets vs. living on income.
    """
    fig = go.Figure()

    # Organic income — arrives without touching portfolio balances
    passive_sources = [
        ("ss_income",         "Social Security",        "#2ca02c"),
        ("rental_income",     "Rental Income",           "#8172B2"),
        ("investment_income", "Dividends / Interest",    "#DD8452"),
        ("rmd_amount",        "RMDs (Traditional)",      "#4C72B0"),
    ]
    for col, label, color in passive_sources:
        if col in ret_df.columns and ret_df[col].sum() > 0:
            fig.add_trace(go.Bar(
                x=ret_df["age"], y=ret_df[col],
                name=label,
                marker_color=color,
                hovertemplate=f"<b>{label}</b><br>Age: %{{x}}<br>%{{y:$,.0f}}<extra></extra>",
            ))

    # Portfolio drawdown — all discretionary account draws grouped together
    drawdown_cols = ["taxable_withdrawal", "traditional_withdrawal", "roth_withdrawal", "bank_withdrawal"]
    available = [c for c in drawdown_cols if c in ret_df.columns]
    if available:
        drawdown = ret_df[available].sum(axis=1)
        if drawdown.sum() > 0:
            fig.add_trace(go.Bar(
                x=ret_df["age"], y=drawdown,
                name="Portfolio Drawdown",
                marker_color="#c44e52",
                hovertemplate="<b>Portfolio Drawdown</b><br>Age: %{x}<br>%{y:$,.0f}<extra></extra>",
            ))

    # Taxes — negative bar so gross income - taxes = after-tax line
    if "total_tax" in ret_df.columns and ret_df["total_tax"].sum() > 0:
        fig.add_trace(go.Bar(
            x=ret_df["age"], y=-ret_df["total_tax"],
            name="Taxes",
            marker_color="#d62728",
            hovertemplate="<b>Taxes</b><br>Age: %{x}<br>-%{customdata:$,.0f}<extra></extra>",
            customdata=ret_df["total_tax"],
        ))

    # Surplus reinvested — only occurs when passive income alone exceeds spending;
    # mutually exclusive with asset sales (we only sell exactly what's needed).
    if "surplus_reinvested" in ret_df.columns and ret_df["surplus_reinvested"].sum() > 0:
        fig.add_trace(go.Bar(
            x=ret_df["age"], y=-ret_df["surplus_reinvested"],
            name="Surplus Reinvested",
            marker_color="#7f7f7f",
            hovertemplate="<b>Surplus Reinvested</b><br>Age: %{x}<br>-%{customdata:$,.0f}<extra></extra>",
            customdata=ret_df["surplus_reinvested"],
        ))

    # After-tax spending line — should align with: gross_bars - taxes - surplus
    fig.add_trace(go.Scatter(
        x=ret_df["age"], y=ret_df["after_tax_spending"],
        name="After-Tax Spending",
        mode="lines+markers",
        line=dict(color="black", width=2, dash="dot"),
        hovertemplate="<b>After-Tax Spending</b><br>Age: %{x}<br>%{y:$,.0f}<extra></extra>",
    ))

    fig.update_layout(
        title="Retirement Spending: Gross Income, Taxes & Net Spending",
        xaxis_title="Age",
        yaxis_title="Amount ($)",
        yaxis_tickformat="$,.0f",
        barmode="relative",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    return fig


def chart_progress_tracking(projections_by_age: dict, checkins: list) -> go.Figure:
    """Dashed baseline projection line with colored scatter dots for actual check-ins."""
    ages = sorted(int(a) for a in projections_by_age)
    totals = [projections_by_age[str(a)]["total"] for a in ages]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=ages, y=totals,
        name="Baseline Projection",
        mode="lines",
        line=dict(color="#4C72B0", width=2, dash="dash"),
        hovertemplate="Age %{x}: %{y:$,.0f}<extra>Projected</extra>",
    ))

    for c in sorted(checkins, key=lambda x: x["age"]):
        proj_entry = projections_by_age.get(str(c["age"]))
        proj_total = proj_entry["total"] if proj_entry else None
        delta = (c["total"] - proj_total) if proj_total is not None else 0
        pct = (delta / proj_total * 100) if proj_total else 0
        color = "#55A868" if delta >= 0 else "#d62728"
        hover = (
            f"<b>Age {c['age']} — {c.get('date', '')}</b><br>"
            f"Actual: ${c['total']:,.0f}<br>"
            f"Projected: ${proj_total:,.0f}<br>"
            f"Delta: ${delta:+,.0f} ({pct:+.1f}%)<br>"
            f"{'Ahead of plan' if delta >= 0 else 'Behind plan'}"
        )
        if c.get("note"):
            hover += f"<br>Note: {c['note']}"
        fig.add_trace(go.Scatter(
            x=[c["age"]], y=[c["total"]],
            name=f"Age {c['age']}",
            mode="markers",
            marker=dict(size=14, color=color, line=dict(width=2, color="white")),
            hovertext=hover,
            hoverinfo="text",
        ))

    fig.update_layout(
        title="Portfolio Progress vs Plan",
        xaxis_title="Age",
        yaxis_title="Total Portfolio",
        yaxis_tickformat="$,.0f",
        hovermode="closest",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


def chart_monte_carlo(mc_result: dict, det_portfolio: list[float]) -> go.Figure:
    """
    Fan chart of Monte Carlo percentile bands with deterministic baseline overlay.
    Bands: 10–90th %ile (light), 25–75th %ile (medium), 50th %ile (solid line).
    """
    ages = mc_result["ages"]
    pct = mc_result["percentiles"]
    fig = go.Figure()

    # 10th–90th band (outermost, lightest fill)
    fig.add_trace(go.Scatter(
        x=ages + ages[::-1],
        y=pct[90] + pct[10][::-1],
        fill="toself",
        fillcolor="rgba(76, 114, 176, 0.12)",
        line=dict(color="rgba(0,0,0,0)"),
        name="10th–90th %ile",
        hoverinfo="skip",
    ))

    # 25th–75th band (inner, medium fill)
    fig.add_trace(go.Scatter(
        x=ages + ages[::-1],
        y=pct[75] + pct[25][::-1],
        fill="toself",
        fillcolor="rgba(76, 114, 176, 0.28)",
        line=dict(color="rgba(0,0,0,0)"),
        name="25th–75th %ile",
        hoverinfo="skip",
    ))

    # Median
    fig.add_trace(go.Scatter(
        x=ages, y=pct[50],
        name="Median (50th %ile)",
        mode="lines",
        line=dict(color="#4C72B0", width=2.5),
        hovertemplate="<b>Median</b><br>Age: %{x}<br>%{y:$,.0f}<extra></extra>",
    ))

    # Deterministic baseline
    if det_portfolio and len(det_portfolio) == len(ages):
        fig.add_trace(go.Scatter(
            x=ages, y=det_portfolio,
            name="Deterministic (expected returns)",
            mode="lines",
            line=dict(color="black", width=2, dash="dash"),
            hovertemplate="<b>Deterministic</b><br>Age: %{x}<br>%{y:$,.0f}<extra></extra>",
        ))

    fig.add_hline(y=0, line=dict(color="red", width=1, dash="dot"))

    vol_pct = mc_result["volatility"] * 100
    success_pct = mc_result["success_rate"] * 100
    fig.update_layout(
        title=(
            f"Monte Carlo — {mc_result['n_runs']:,} Trials  |  "
            f"Volatility: {vol_pct:.0f}%  |  "
            f"Success Rate: {success_pct:.1f}%"
        ),
        xaxis_title="Age",
        yaxis_title="Portfolio Balance",
        yaxis_tickformat="$,.0f",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    return fig


def chart_mc_comparison(mc_v1: dict, mc_v2: dict, det_portfolio: list[float]) -> go.Figure:
    """
    Overlay fan chart comparing Standard (v1, blue) and CMA Log-Normal (v2, orange) results.
    Both percentile bands are shown together with a shared deterministic baseline.
    """
    ages = mc_v1["ages"]
    p1 = mc_v1["percentiles"]
    p2 = mc_v2["percentiles"]
    fig = go.Figure()

    # v1 bands (blue)
    fig.add_trace(go.Scatter(
        x=ages + ages[::-1], y=p1[90] + p1[10][::-1],
        fill="toself", fillcolor="rgba(76, 114, 176, 0.10)",
        line=dict(color="rgba(0,0,0,0)"), name="Standard 10–90%", hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=ages + ages[::-1], y=p1[75] + p1[25][::-1],
        fill="toself", fillcolor="rgba(76, 114, 176, 0.22)",
        line=dict(color="rgba(0,0,0,0)"), name="Standard 25–75%", hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=ages, y=p1[50], name="Standard median",
        mode="lines", line=dict(color="#4C72B0", width=2.5),
        hovertemplate="<b>Standard median</b><br>Age: %{x}<br>%{y:$,.0f}<extra></extra>",
    ))

    # v2 bands (orange)
    fig.add_trace(go.Scatter(
        x=ages + ages[::-1], y=p2[90] + p2[10][::-1],
        fill="toself", fillcolor="rgba(214, 95, 50, 0.10)",
        line=dict(color="rgba(0,0,0,0)"), name="CMA 10–90%", hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=ages + ages[::-1], y=p2[75] + p2[25][::-1],
        fill="toself", fillcolor="rgba(214, 95, 50, 0.22)",
        line=dict(color="rgba(0,0,0,0)"), name="CMA 25–75%", hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=ages, y=p2[50], name="CMA median",
        mode="lines", line=dict(color="#D65F32", width=2.5),
        hovertemplate="<b>CMA median</b><br>Age: %{x}<br>%{y:$,.0f}<extra></extra>",
    ))

    if det_portfolio and len(det_portfolio) == len(ages):
        fig.add_trace(go.Scatter(
            x=ages, y=det_portfolio, name="Deterministic",
            mode="lines", line=dict(color="black", width=2, dash="dash"),
            hovertemplate="<b>Deterministic</b><br>Age: %{x}<br>%{y:$,.0f}<extra></extra>",
        ))

    fig.add_hline(y=0, line=dict(color="red", width=1, dash="dot"))
    fig.update_layout(
        title=(
            f"Model Comparison — Standard success: {mc_v1['success_rate']:.1%}  |  "
            f"CMA success: {mc_v2['success_rate']:.1%}"
        ),
        xaxis_title="Age",
        yaxis_title="Portfolio Balance",
        yaxis_tickformat="$,.0f",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    return fig


def chart_mc_depletion(mc_result: dict) -> go.Figure:
    """Histogram of ages at which the portfolio depleted (failed runs only)."""
    ages = mc_result["depletion_ages"]
    if not ages:
        return go.Figure()
    n_depleted = len(ages)
    n_runs = mc_result["n_runs"]
    fig = go.Figure(go.Histogram(
        x=ages,
        nbinsx=min(len(set(ages)), 30),
        marker_color="#d62728",
        hovertemplate="Age %{x}: %{y} trials depleted<extra></extra>",
    ))
    fig.update_layout(
        title=f"Depletion Age Distribution — {n_depleted:,} of {n_runs:,} trials depleted",
        xaxis_title="Age at Portfolio Depletion",
        yaxis_title="Number of Trials",
        bargap=0.1,
    )
    return fig


def chart_tax_burden(ret_df: pd.DataFrame) -> go.Figure:
    """Line chart of annual tax components during retirement."""
    fig = go.Figure()

    tax_components = [
        ("federal_ordinary_tax", "Federal Ordinary",  "#4C72B0"),
        ("federal_ltcg_tax",     "Federal LTCG",      "#DD8452"),
        ("federal_niit",         "NIIT",               "#d62728"),
        ("federal_irmaa",        "IRMAA",              "#8172B2"),
        ("state_tax",            "State Tax",          "#55A868"),
    ]

    for col, label, color in tax_components:
        if col in ret_df.columns and ret_df[col].sum() > 0:
            fig.add_trace(go.Scatter(
                x=ret_df["age"], y=ret_df[col],
                name=label,
                mode="lines",
                line=dict(color=color, width=2),
                hovertemplate=f"<b>{label}</b><br>Age: %{{x}}<br>%{{y:$,.0f}}<extra></extra>",
            ))

    # Effective rate on secondary axis
    fig.add_trace(go.Scatter(
        x=ret_df["age"], y=ret_df["effective_tax_rate"] * 100,
        name="Effective Rate (%)",
        mode="lines",
        line=dict(color="black", width=2, dash="dash"),
        yaxis="y2",
        hovertemplate="<b>Effective Rate</b><br>Age: %{x}<br>%{y:.1f}%<extra></extra>",
    ))

    fig.update_layout(
        title="Annual Tax Burden During Retirement",
        xaxis_title="Age",
        yaxis=dict(title="Annual Tax ($)", tickformat="$,.0f"),
        yaxis2=dict(title="Effective Rate (%)", overlaying="y", side="right",
                    tickformat=".1f", range=[0, 50]),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    return fig
