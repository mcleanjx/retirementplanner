import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

TAX_BUCKET_COLORS = {
    "pre_tax":     "#4C72B0",
    "roth":        "#55A868",
    "taxable":     "#DD8452",
    "real_estate": "#8172B2",
    "cash":        "#A0A0A0",
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


def chart_drawdown(ret_df: pd.DataFrame, accounts_at_retirement: list[dict]) -> go.Figure:
    """Stacked area chart of remaining balances during retirement."""
    fig = go.Figure()
    type_to_bucket = {
        "traditional_401k": "pre_tax", "traditional_ira": "pre_tax",
        "roth_401k": "roth", "roth_ira": "roth", "hsa": "roth",
        "taxable": "taxable", "reit": "taxable",
        "rental_property": "real_estate", "bank": "cash",
    }
    for a in accounts_at_retirement:
        col = f"bal_{a['name'].replace(' ', '_')}"
        if col not in ret_df.columns:
            continue
        bucket = type_to_bucket.get(a["type"], "taxable")
        fig.add_trace(go.Scatter(
            x=ret_df["age"], y=ret_df[col],
            name=a["name"],
            mode="lines",
            stackgroup="one",
            fillcolor=TAX_BUCKET_COLORS[bucket],
            line=dict(color=TAX_BUCKET_COLORS[bucket], width=1),
            hovertemplate=f"<b>{a['name']}</b><br>Age: %{{x}}<br>Balance: %{{y:$,.0f}}<extra></extra>",
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


def chart_annual_income(ret_df: pd.DataFrame) -> go.Figure:
    """Stacked bar chart of annual income sources in retirement."""
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
