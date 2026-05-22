# Research & Calibration Notes

This document records empirical research and data sources used to validate and calibrate the retirement planner's assumptions. It is a living document — add findings here before they are acted on in code.

---

## 1. Shiller Historical Data (completed May 2026)

**Source:** Robert Shiller, Yale University — `shillerdata.com` (ie_data.xls)  
**Coverage:** Monthly data, January 1871 – May 2026  
**Contents:** S&P 500 nominal price, dividends, earnings, CPI, 10-yr Treasury yield, CAPE

### Equity Total Returns (nominal and real)

| Period | Nominal CAGR | Real CAGR | Annual Vol |
|---|---|---|---|
| Full history (1871–2026) | 9.38% | 7.09% | 14.0% |
| Modern era (1926–2026) | 10.47% | 7.30% | 15.3% |
| Post-WWII (1946–2026) | 11.27% | 7.32% | 12.1% |
| Recent 30 years (1993–2026) | 10.82% | 8.03% | 12.4% |

**Key takeaway:** Real equity total return is remarkably stable at ~7.1–7.3% across periods. The recent 30yr is slightly higher (8%) due to the 1990s bull market and 2010s tech expansion.

### Inflation (CPI)

| Period | CAGR | Ann. Vol |
|---|---|---|
| Full history (1871–2026) | 2.14% | 3.54% |
| Modern era (1926–2026) | 2.95% | 1.81% |
| Post-WWII (1946–2026) | 3.68% | 1.53% |
| Recent 30 years (1993–2026) | 2.58% | 1.19% |

The app default of 2.5% inflation is well-calibrated to the recent 30-year experience. The post-WWII average (3.7%) is a useful stress-test value.

### 10-Year Treasury Yield (level, not total return)

| Period | Mean | Median |
|---|---|---|
| Full history (1871–2026) | 4.48% | 3.83% |
| Modern era (1926–2026) | 4.77% | 3.92% |
| Post-WWII (1946–2026) | 5.25% | 4.45% |
| Recent 30 years (1993–2026) | 3.93% | 4.05% |

Current 10-yr yield (~4.4%) is right at the historical median — no unusual bond headwind or tailwind implied by starting conditions.

### CAPE (Shiller P/E)

| Metric | Value |
|---|---|
| Historical median | 16.6× |
| Historical mean | 17.7× |
| Current (May 2026) | 39.6× |

The current CAPE of ~39× is the second-highest on record (after the ~44× peak in early 2000). Historically elevated CAPE has predicted below-average 10-year forward returns. GMO and Research Affiliates estimate ~2–3% real US equity returns over the next decade based on current valuations.

---

## 2. Capital Market Assumptions in the Code

### montecarlo_v2.py defaults (CMA Log-Normal engine)

| Parameter | Code value | Shiller historical | Notes |
|---|---|---|---|
| `DEFAULT_EQUITY_VOL` | 15.5% | 12.1–15.3% | Top of range; appropriate conservatism |
| `DEFAULT_BOND_VOL` | 5.5% | n/a | Aligned with JPM/Vanguard/BlackRock CMA |
| `DEFAULT_EQUITY_BOND_CORR` | 0.10 | — | Long-run CMA consensus |
| Inflation vol | 1.5% (hardcoded) | 1.2–1.8% modern era | Well-calibrated |

The equity vol at 15.5% is at the top of the historical range — this is intentional conservatism. It reflects the full modern era (1926–now) rather than the lower vol of the post-WWII period.

### app.py DEFAULT_ASSUMPTIONS

| Parameter | Old default | New default (May 2026) | Basis |
|---|---|---|---|
| `retirement_return_rate` | 5.0% | **6.5%** | Shiller 7.1–7.3% real; minus ~0.5% for blended portfolio; CAPE caveat noted in UI |
| `inflation_rate` | 3.0% | 3.0% | Post-WWII average; slightly above recent 30yr (2.6%) — appropriate conservatism |

**Why 6.5% and not 7%+:**  
- Real history says ~7.1–7.3% real for 100% equities.
- The app default models a blended portfolio (equities + bonds), not pure equities.
- Current CAPE (~39×) argues for below-average forward returns.
- 6.5% nominal ≈ 4.0% real at 2.5% inflation — slightly below the long-run equity real return, which is appropriate for a balanced portfolio in a high-valuation environment.

**Dividend adjustment note (shown in UI help text):**  
The `retirement_return_rate` is capital appreciation only. Users with dividend-paying accounts set to "use global rate" should reduce this by their portfolio's dividend yield (e.g., 5.0% if total return is 6.5% and dividend yield is 1.5%), because dividends are separately modeled as income.

---

## 3. CAPE-Based Forward Return Context

The retirement_monte_carlo.md spec (Section 6.2) describes a CAPE-based equity return adjustment as a potential refinement: reduce near-term equity returns based on current valuations, reverting to long-run averages over 10 years. This has not been implemented.

At current CAPE (~39×), Research Affiliates and GMO models suggest:
- 10-year US equity real return: ~1–3% (vs. historical ~7%)
- Implication: the 6.5% nominal default may still be optimistic for near-term cohorts
- A CAPE adjustment mode would allow users to stress-test against a low-return decade before reverting to historical averages

**Status:** Not implemented. Flagged as a future refinement.

---

## 4. Data Sources — Pending Exploration

### Vanguard "How America Saves" (next priority)
Annual report on 401(k) participant behavior. Useful for:
- Validating test scenario balances against real-world 401k balances by age
- Checking default contribution rate assumptions
- Benchmarking asset allocation defaults

Search: "Vanguard How America Saves 2024" (annual publication, free PDF from vanguard.com).

### Health and Retirement Study (HRS)
University of Michigan longitudinal study of Americans 50+. Most detailed publicly available dataset on retiree spending, assets, and health costs. Free with registration at hrs.isr.umich.edu.  
Use for: validating spending trajectory assumptions, healthcare cost defaults, and spending reduction at survivor transition.

### BLS Consumer Expenditure Survey (CEX)
Spending by age bracket including 65+. Microdata at bls.gov/cex.  
Use for: spot-checking the default `annual_spending_target` and the 25% survivor spending reduction.

### ICI Retirement Research
IRA and 401(k) balance distributions by age and income. Available at ici.org.  
Use for: validating test scenario balances and contribution assumptions.

### Fed Survey of Consumer Finances (SCF)
Comprehensive household wealth and retirement data, released every 3 years. Downloadable microdata at federalreserve.gov.  
Use for: broad-based validation of starting balance assumptions across income levels.

### FRED (Federal Reserve Economic Data)
Machine-readable API for inflation, treasury yields, bond returns, GDP. Available at fred.stlouisfed.org.  
Use for: programmatic data pulls for ongoing calibration; bond return series to validate bond vol assumptions.

### Kenneth French Data Library
Equity factor returns and portfolio returns by style/size. Useful for validating equity vol assumptions across asset classes.

### SSA Period Life Table
Actuarial standard for life expectancy by age and sex. Used by most commercial planners. Available at ssa.gov/oact/STATS/table4c6.html.  
Use for: validating the default `life_expectancy` of 90 and understanding mortality risk tails.

---

## 5. MC v2 Architecture Reference

The CMA Log-Normal engine (`montecarlo_v2.py`) implements the following design (from `retirement_monte_carlo.md` Section 15):

- **Log-normal returns**: corrects arithmetic/geometric mean confusion; bounds left tail at −100%
- **Correlated equity/bond factors**: Cholesky decomposition of 2×2 correlation matrix; all equity-heavy accounts driven by shared equity factor, bond-heavy by shared bond factor
- **Stochastic inflation**: `N(inflation_rate, 1.5%)` per year; spending inflates by drawn inflation each year
- **Guyton-Klinger guardrails** (optional): cut spending 10% if withdrawal rate > 120% of baseline; raise 10% if < 80%
- **Tax computation** (added May 2026): per-year ordinary income (RMDs + traditional draws + rental), LTCG from taxable withdrawals, SS taxability, bracket-adjusted federal and state tax

The CMA Log-Normal model is now the **default** in the UI (Standard/Normal is still available for comparison).
