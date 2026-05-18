# Retirement Planning Web App - Project Specification

## Overview

Build a single-page Streamlit application for retirement planning that allows users to model multiple investment accounts, project growth through retirement, and visualize tax-optimized withdrawal strategies.

## Tech Stack

- **UI Framework**: Streamlit
- **Charts**: Plotly (plotly.express and plotly.graph_objects)
- **Data**: pandas, numpy
- **State Management**: Streamlit session_state
- **No backend required** - all calculations run locally in Python

## Core Features

### 1. Account Management

Users should be able to add, edit, and remove multiple investment accounts. Each account has:

**Required Fields:**
- Account name (user-defined)
- Account type (dropdown):
  - Traditional 401(k)
  - Roth 401(k)
  - Traditional IRA
  - Roth IRA
  - Taxable Brokerage
  - Bank / Cash (savings/money market; grows at own rate, no tax on appreciation, tax-free withdrawals modeled as ordinary income at 0% — simple cash reserve)
  - HSA
  - REIT (Taxable)
  - Rental Property
- Current balance ($) — for Rental Property, this is current equity (property value minus mortgage)
- Expected rate of return / appreciation (% per year)

**Optional Fields (by account type):**
- Annual contribution ($) — not applicable to Rental Property or REIT (no ongoing contributions)
- Contribution growth rate (% per year) — not applicable to Rental Property or REIT
- Employer match percentage (401k only)
- Employer match limit (401k only)
- Cost basis ($) — Taxable Brokerage and REIT only; defaults to 50% of balance with a warning if not provided
- Qualified dividend yield (% of balance/year) — Taxable Brokerage and REIT; portion taxed at LTCG rates (default: 1.5% for brokerage, 0% for REIT)
- Ordinary income yield (% of balance/year) — Taxable Brokerage and REIT; portion taxed as ordinary income — covers interest, non-qualified dividends, REIT distributions (default: 0.5% for brokerage, 4% for REIT)
- Net annual rental income ($) — Rental Property only; cash income after all expenses (mortgage P&I, taxes, insurance, maintenance); treated as ordinary income each year
- Mortgage remaining balance ($) — Rental Property only; reduces equity; payoff year = current year + (balance / annual principal paydown estimate); for simplicity, user can just enter equity directly and leave this at 0
- **Use global retirement return rate** (checkbox, all non-bank/non-rental accounts) — when checked, the account grows at the global "Retirement Return Rate" during the retirement phase; when unchecked, the account's own return rate is used instead. Bank and Rental Property accounts always use their own rates. This allows modeling, e.g., a conservative bond account growing at 3% while equities grow at 7%, all within the same scenario.

**Tax Treatment (derived from account type):**
- Traditional 401(k)/IRA: Pre-tax contributions, taxed as ordinary income on withdrawal
- Roth 401(k)/IRA: Post-tax contributions, tax-free qualified withdrawals
- Taxable Brokerage: Post-tax contributions; dividends/interest taxable annually; capital gains tax on gains at withdrawal
- Bank / Cash: Post-tax; no capital gains; withdrawals are basis return (no tax); interest taxed as ordinary income via ordinary_income_yield if set
- HSA: Pre-tax contributions, tax-free for medical (model as tax-free for simplicity)
- REIT (Taxable): Like taxable brokerage but distributions are predominantly ordinary income (not qualified dividends); basis tracked for LTCG on sale
- Rental Property: Equity appreciates annually; net rental income is ordinary income each year; on sale, gain above basis is taxed at LTCG rates (depreciation recapture not modeled — show a warning)

### 2. User Profile / Assumptions

**Personal Information:**
- Current age
- Planned retirement age
- Life expectancy (or "plan to age")
- Filing status (Single, Married Filing Jointly)
- State of residence (California uses progressive brackets; other states use a flat rate %)
- Current annual income / salary (pre-tax, optional — used for income replacement calculation and accumulation-phase tax drag estimate)

**Spouse Information (MFJ only):**
- Spouse current age
- Spouse planned retirement age
- Spouse estimated Social Security benefit ($ per year, in today's dollars)
- Spouse Social Security start age (default: 67)
- Survivor scenario: when the older spouse reaches life expectancy, model the following automatically:
  - Filing status switches to Single (higher tax rates)
  - Total SS drops to the higher of the two individual SS benefits (the lower benefit stops)
  - Spending target reduces by a configurable percentage (default: 25% reduction, reflecting shared fixed costs)

**Healthcare Costs:**
- Pre-Medicare annual healthcare cost ($ per year; applies from retirement age until age 65; default: $15,000 — covers premiums + out-of-pocket)
- Post-Medicare annual healthcare cost ($ per year; applies from age 65 onward; default: $12,000 — covers Part B/D premiums ~$2,435/yr/person, supplemental/Medigap, dental/vision, and out-of-pocket; IRMAA surcharges are computed separately and added on top)
- These are added to the annual spending target and are inflation-adjusted each year

**Economic Assumptions:**
- Inflation rate (default: 3%)
- **Tax bracket inflation rate** (default: 2.5%) — annual rate at which all federal (and CA) bracket thresholds, standard deductions, NIIT thresholds, and IRMAA tier thresholds are scaled forward each simulation year. Applied as `bracket_factor = (1 + rate)^(age - current_age)` to all threshold constants. **SS taxability thresholds are intentionally NOT indexed** — they have been frozen by Congress since 1984, so the simulation correctly models increasing SS taxability via bracket creep over time.
- Safe withdrawal rate (default: 4%)
- Expected return during retirement (default: 5%, typically more conservative than accumulation)
- **Withdrawal strategy** (radio button):
  - *Tax-Efficient* (default): each year, fill Traditional withdrawals up to top of 22% bracket, then draw Roth, then overflow back to Traditional if still short. Minimizes current-year taxes.
  - *Roth Preservation*: drain Traditional accounts completely before touching Roth. Accepts higher taxes now; lets Roth grow tax-free longer and reduces future RMDs.

**Social Security (Primary filer):**
- Estimated Social Security benefit ($ per year, **in today's dollars** — as shown on SSA.gov "my Social Security")
- Social Security start age (default: 67)
- **Important:** The simulation inflates SS inputs from today's dollars to retirement-year nominal dollars using `(1 + inflation)^years_to_retirement` before the retirement loop begins. Inside the retirement loop, SS benefits grow by the inflation rate each year (COLA). This correctly models the real-world behavior where SSA shows benefits in today's purchasing power.

### 3. Accumulation Phase Projection

Calculate year-by-year growth of each account from current age to retirement age.

**Row recording convention:** Each year's row records the account balance at the **start** of that year (before growth and contributions are applied). This means the row for `current_age` shows the user's actual starting balances, and the row for `retirement_age` shows the balances that will be handed to the retirement simulation.

```
For each year from current_age to retirement_age (inclusive):
  For each account:
    1. Record start-of-year balance and passive income metrics for this age row
    2. [Only if age < retirement_age] Apply investment return and contributions:
         a. balance *= (1 + return_rate)
         b. Add annual contribution (with employer match if applicable)
         c. Increase contribution by growth rate for next year
         d. Cap contributions at IRS limits (optional advanced feature)
    3. [Taxable / REIT accounts] Generate recurring income (computed on start-of-year balance):
         qualified_div_income = balance * qualified_dividend_yield
         ordinary_income      = balance * ordinary_income_yield
       Add to the year's taxable income tally (see Tax Drag below)
    4. [Rental Property] Add net_annual_rental_income to taxable income tally
       Grow equity: equity *= (1 + appreciation_rate)
```

The `accounts_at_retirement` list returned to the retirement simulator contains start-of-retirement balances (i.e., the balances recorded in the `retirement_age` row, before any further growth).

**Tax Drag on Taxable Accounts During Accumulation:**

Taxable brokerage, REIT, and rental income generate taxable income every year — even before retirement. This reduces the user's effective return and must be reflected in projections.

- If `current_income` is provided in the Profile: estimate the user's federal marginal bracket from salary; apply that rate to ordinary income yields. For California residents, use CA marginal rates (progressive, capital gains taxed as ordinary income) rather than the flat federal LTCG rate.
- If no income is provided: assume 22% federal marginal rate and 15% LTCG rate as defaults.
- Annual tax cost for taxable accounts:
  - `ord_tax = ordinary_income × (fed_rate + state_rate)`
  - `ltcg_tax = calculate_ltcg_tax(qual_div, max(0, current_income - std_ded), filing_status)`
  - Plus CA state tax on qualified dividends (CA taxes LTCGs as ordinary income)
- Show this as an annual cost line in the accumulation projection table (it does not reduce the account balance — the user pays it from other income — but it is a real cash drag to display).

**Output:**
- Ending balance for each account at retirement
- Total portfolio value at retirement
- Breakdown by tax treatment (pre-tax, Roth/tax-free, taxable)
- Annual rental and investment income during accumulation (for tax drag display)

### 4. Retirement Phase Projection (Tax-Optimized Withdrawals)

Simulate withdrawals from retirement age to life expectancy using a tax-optimized strategy:

**Tax Optimization Strategy:**

Each retirement year, execute the following steps in order:

**Step 0 — Survivor scenario check**
- If both spouses' ages are modeled and the older spouse has reached life expectancy this year:
  - Switch filing status to Single
  - Total SS = max(primary_ss_benefit, spouse_ss_benefit)
  - Reduce annual spending target by the survivor spending reduction % (default 25%)
  - After survivor transition, count only one Medicare enrollee (not two) for IRMAA purposes
  - Emit a warning in the output at the year this transition occurs

**Step 1 — Mandatory and passive income (no choice)**
- Take all RMDs from Traditional accounts (age 73+); these are ordinary income
- Collect Social Security (primary + spouse if MFJ) if at or past each SS start age; taxability calculated in Step 2
- Collect net rental income from Rental Property accounts; this is ordinary income
- Collect recurring income from Taxable Brokerage and REIT accounts:
  - `qualified_div_income = balance × qualified_dividend_yield` → goes into LTCG income bucket
  - `ordinary_income = balance × ordinary_income_yield` → goes into ordinary income bucket
- Note: recurring investment income reduces the amount that needs to be withdrawn from accounts in Step 5

**Step 2 — Calculate Social Security taxable amount**
- Combined income = AGI (so far) + 50% of total SS benefit
- SS taxable portion: 0% if combined income < $32,000 MFJ / $25,000 Single; 50% up to $44,000 MFJ / $34,000 Single; 85% above that
- Add taxable SS to ordinary income running total
- **Note:** These SS taxability thresholds are NOT inflation-adjusted (see bracket inflation rate note in Section 2). This is intentional — it accurately models the real-world effect of increasing SS taxability over time.

**Step 3 — Roth conversions (optional; see Section 8 for full specification)**
- If Roth conversion strategy is enabled, calculate the conversion amount for this year per the user's chosen strategy
- Add conversion amount to ordinary income (it is taxable in the year converted)
- Move converted amount from the chosen Traditional account(s) to the chosen Roth account
- Conversions happen before discretionary withdrawals so they consume bracket space first
- Do not convert in years where RMDs already push income above the target bracket ceiling
- **Conversion tax funding:** After computing the conversion amount, estimate the conversion tax (`conversion_amount × target_bracket_rate`) and add it to the year's spending need. This ensures Step 5 withdraws enough cash from taxable/bank accounts to actually pay the conversion taxes — preventing the taxes from silently reducing after-tax spending while leaving the portfolio overstated. The estimate uses the target bracket rate (fill_to_bracket strategy) or the previous year's effective rate (fixed_amount strategy).

**Step 4 — Tax-free capital gains harvesting (taxable accounts)**
- Calculate remaining 0% LTCG headroom: `0% LTCG threshold × bracket_factor - current taxable income`
  - MFJ: 0% up to $98,900 × bracket_factor; 15% up to $613,700 × bracket_factor; 20% above
  - Single: 0% up to $49,450 × bracket_factor; 15% up to $545,500 × bracket_factor; 20% above
- If headroom exists and taxable account has unrealized gains, realize gains up to the headroom limit (sell and immediately rebuy to step up basis)
- This does not generate cash for spending — it purely reduces future embedded gains
- **Important:** harvested gains must still be added to `ltcg_income` (even though taxed at 0%) so that MAGI is correctly computed for IRMAA and NIIT threshold tests in Step 6

**Step 5 — Meet spending needs (withdrawal ordering)**
- Annual spending target = base target (inflation-adjusted) + healthcare costs (inflation-adjusted) + conversion tax estimate (if Roth conversion active this year)
  - Pre-65: add pre-Medicare healthcare cost
  - Age 65+: add post-Medicare healthcare cost (base; IRMAA surcharge added in Step 6 after income is known)
- Subtract passive income already collected in Step 1 to get remaining gap
- Withdraw from accounts in this order:
  1. **Bank / Cash accounts** — drain first (no tax cost, lowest return)
  2. **Taxable brokerage / REIT** — only the gain portion is taxed at LTCG rates; basis returned tax-free
     - `gain_ratio = unrealized_gain / current_balance` — compute **before** reducing balance
     - `taxable_portion = withdrawal × gain_ratio` → taxed at LTCG rate
     - `basis_portion = withdrawal × (1 - gain_ratio)` → tax-free
     - Reduce account basis proportionally on each withdrawal
  3. **Traditional / Roth (order depends on withdrawal strategy)**:

  *Tax-Efficient (default):*
  - Fill Traditional up to top of 22% bracket (ordinary income ceiling including standard deduction × bracket_factor)
  - Then draw Roth for any remaining need
  - Fall back to Traditional if Roth is exhausted

  *Roth Preservation:*
  - Drain Traditional accounts fully before touching Roth
  - Then draw Roth only once Traditional is exhausted

**Step 6 — IRMAA and NIIT**

Before computing taxes, assemble the full **net investment income (NII)** figure that NIIT applies to:
```
nii = ordinary_dividend_income + qualified_dividend_income + ltcg_gains + rental_income
```
This includes ALL of: ordinary dividends from taxable accounts, qualified dividends, realized capital gains (including harvested gains from Step 4), and net rental income. Do **not** include SS or Traditional account withdrawals — those are not NII.

*NIIT:*
- If MAGI exceeds $250,000 MFJ / $200,000 Single (scaled by bracket_factor), apply 3.8% NIIT to the lesser of **net investment income (as defined above)** or the excess MAGI above threshold

*IRMAA (age 65+):*
- IRMAA surcharges are per person; apply to each Medicare-eligible spouse separately
- After survivor transition, count only one Medicare enrollee
- Based on 2026 MAGI thresholds scaled by bracket_factor (use current-year MAGI as a planning proxy rather than the 2-year lookback):

  | MAGI (MFJ) | MAGI (Single) | Part B surcharge/mo | Part D surcharge/mo |
  |---|---|---|---|
  | ≤ $218,000 | ≤ $109,000 | $0 (base $202.90) | $0 |
  | $218,001–$274,000 | $109,001–$137,000 | +$81.20 | +$14.50 |
  | $274,001–$342,000 | $137,001–$171,000 | +$203.70 | +$37.60 |
  | $342,001–$410,000 | $171,001–$205,000 | +$325.20 | +$60.60 |
  | $410,001–$750,000 | $205,001–$500,000 | +$406.90 | +$83.70 |
  | > $750,000 | > $500,000 | +$487.00 | +$91.00 |

  *(All MAGI thresholds multiplied by bracket_factor in the simulation)*

- Annual IRMAA cost per Medicare-eligible person = `(Part B surcharge + Part D surcharge) × 12`
- For MFJ where both spouses are 65+, apply IRMAA twice
- Add IRMAA cost to the year's total tax/cost burden and to the after-tax spending cost
- **IRMAA cliff alerts**: Emit a proactive warning whenever MAGI is within $10,000 of the next IRMAA tier threshold, showing the dollar amount of surcharges that would be avoided by staying below the cliff.
- Emit a warning whenever the user actually crosses an IRMAA tier threshold.

**Step 7 — Apply returns, COLA, and advance year**
- Apply investment returns to remaining balances in each account:
  - Bank accounts and Rental Property always use their own `return_rate`
  - All other accounts: use the account's own `return_rate` if `use_global_return_rate` is `False`; otherwise use the global `retirement_return_rate` from Assumptions
- Grow taxable account basis by zero (returns accrue as unrealized gains until sold)
- Grow rental property equity: `equity *= (1 + appreciation_rate)`
- Inflate spending target by inflation rate (healthcare costs inflate at the same rate)
- Apply SS COLA: multiply both primary and spouse SS benefit by `(1 + inflation)` each year — after the survivor transition spouse_ss is 0 so this is harmless

**Tax Rates (2026 base — scaled annually by bracket_inflation_rate)**

Ordinary income — Married Filing Jointly:
```
Standard Deduction: $32,200 × bracket_factor (no tax on this amount)
10%: $0 – $24,800 × bracket_factor
12%: $24,800 – $100,800 × bracket_factor
22%: $100,800 – $211,400 × bracket_factor
24%: $211,400 – $403,550 × bracket_factor
32%: $403,550 – $512,450 × bracket_factor
35%: $512,450 – $768,700 × bracket_factor
37%: $768,700+ × bracket_factor
```

Ordinary income — Single:
```
Standard Deduction: $16,100 × bracket_factor (no tax on this amount)
10%: $0 – $12,400 × bracket_factor
12%: $12,400 – $50,400 × bracket_factor
22%: $50,400 – $105,700 × bracket_factor
24%: $105,700 – $201,775 × bracket_factor
32%: $201,775 – $256,225 × bracket_factor
35%: $256,225 – $640,600 × bracket_factor
37%: $640,600+ × bracket_factor
```

Long-term capital gains — Married Filing Jointly:
```
0%:  $0 – $98,900 × bracket_factor of taxable income
15%: $98,900 – $613,700 × bracket_factor
20%: $613,700+ × bracket_factor
+3.8% NIIT on investment income when MAGI > $250,000 × bracket_factor
```

Long-term capital gains — Single:
```
0%:  $0 – $49,450 × bracket_factor of taxable income
15%: $49,450 – $545,500 × bracket_factor
20%: $545,500+ × bracket_factor
+3.8% NIIT on investment income when MAGI > $200,000 × bracket_factor
```

Add a configurable state tax rate (simple flat percentage applied to ordinary income and capital gains).

**California special rules (when `state == "california"`):**
- Capital gains are taxed as ordinary income (no preferential LTCG rate)
- Social Security is **fully excluded** from California taxable income — CA does not tax SS at all
- Implementation: `ordinary_income` passed into the tax function already includes only the **federal taxable SS amount** (`ss_taxable`). When computing CA state tax, subtract exactly `ss_taxable` (not the full gross SS benefit) from ordinary income, so CA sees non-SS income only. Subtracting the full SS benefit would over-exclude income that was never included.
- CA standard deduction and CA bracket thresholds are also scaled by bracket_factor (CA also indexes brackets to inflation annually)

**Taxable Account Basis Tracking:**
- Each account carries two values: `balance` (current market value) and `basis` (total cost basis)
- `unrealized_gain = balance - basis`
- At retirement start, if the user doesn't know their basis, default to 50% of balance with a visible warning
- During accumulation, annual contributions add to basis dollar-for-dollar; investment returns accrue as unrealized gains

**Handle RMDs (Required Minimum Distributions):**
- Starting at age 73, Traditional 401(k)/IRA accounts require minimum withdrawals
- RMD = Account Balance / Distribution Period (IRS Uniform Lifetime Table)
- Approximate divisors: age 73 → 26.5, age 75 → 24.6, age 80 → 20.2, age 85 → 16.0, age 90 → 12.2
- If RMD exceeds spending need, withdraw the full RMD anyway; excess goes to taxable account (add to balance and basis equally, since it's already been taxed)

**Output:**
- Year-by-year withdrawal amounts from each account
- Annual passive income (rental + dividends + interest) by source
- Annual ordinary income tax + LTCG tax + NIIT + IRMAA surcharge + state tax
- After-tax spending power (net of taxes and healthcare)
- Remaining balance and remaining basis in each account
- Effective tax rate each year
- Year of survivor transition (if MFJ) with before/after spending and tax comparison
- Year when each account is depleted
- Year when total portfolio is depleted
- Warning flags: portfolio depletion before life expectancy, IRMAA tier crossings, IRMAA approaching warnings, RMD excess, contribution limit violations

### 5. Visualizations (using Plotly)

**Chart 1: Account Growth (Accumulation Phase)**
- Type: Stacked area chart
- X-axis: Age (current to retirement)
- Y-axis: Balance ($)
- Series: One for each account, color-coded by tax treatment (pre-tax, Roth, taxable, real estate, cash)

**Chart 2: Portfolio Composition at Retirement**
- Type: Donut chart
- Segments: Each account's ending balance with percentage breakdown by tax treatment

**Chart 3: Retirement Drawdown**
- Type: Stacked area chart — per-account balances, color-shaded within each tax bucket
- Overlay: Dashed line showing total portfolio in **today's purchasing power** (deflated by `(1+inflation)^(age-current_age)`)

**Chart 4: Annual Retirement Income**
- Type: Stacked bar chart (positive: income sources; negative: taxes)
- Overlay: After-tax spending line (nominal), plus dash-dot line showing spending in **retirement-year real dollars** (flat line = real spending preserved)

**Chart 5: Tax Burden Over Time**
- Type: Line chart with secondary Y-axis for effective tax rate %
- Series: Federal ordinary, federal LTCG, NIIT, IRMAA, state tax

**Chart 6: Retirement Spending Coverage**
- Type: Stacked bar + line overlay (`barmode="relative"`)
- Positive bars: Social Security, Rental Income, Dividends/Interest, RMDs, Portfolio Drawdown
- Negative bars: Taxes and Surplus Reinvested
- Identity: `sum(positive bars) - taxes - surplus = after_tax_spending line`

**Chart 7: Monte Carlo Fan Chart**
- Type: Filled band chart
- Light fill: 10th–90th percentile band
- Medium fill: 25th–75th percentile band
- Solid line: 50th percentile (median)
- Dashed line: Deterministic baseline (expected returns, no randomness)
- Red dotted line at $0

**Chart 8: Monte Carlo Depletion Histogram**
- Type: Histogram (only rendered when at least one trial depleted)
- X-axis: Age at portfolio depletion
- Y-axis: Number of trials
- Shows the distribution of failure timing across depleted trials

### 6. Summary Statistics

Display key metrics prominently:

**At Retirement:**
- Total portfolio value
- Breakdown: Pre-tax / Roth / Taxable amounts

**During Retirement:**
- Sustainable annual withdrawal (in today's dollars)
- Sustainable monthly withdrawal (in today's dollars)
- Portfolio longevity (years until depletion)
- Lifetime taxes paid in retirement (broken down: federal ordinary + LTCG + NIIT + IRMAA + state)
- Lifetime healthcare costs
- Percentage of income replacement vs. pre-retirement income (only shown if `current_income` is provided)
- Total passive income over retirement (rental + dividends + interest)

**Warnings/Alerts:**
- Portfolio depletes before life expectancy
- RMDs force higher withdrawals than desired spending target
- IRMAA tier crossed (flag the year and the annual cost increase)
- IRMAA approaching: MAGI within $10,000 of next tier (shows dollar savings from staying below)
- Survivor transition year (SS reduction + tax rate change summary)
- Contribution limits exceeded vs. 2026 IRS limits (401k: $23,500 + catch-up; IRA: $7,000 + $1,000; HSA: $8,550 MFJ / $4,300 single)
- Rental property depreciation recapture not modeled (always shown if user has a Rental Property account)

## UI/UX Requirements

### Layout

Use a clean, professional design with:

1. **Header**: App title, brief description
2. **Left Sidebar**: Input forms
   - Collapsible sections for: Profile, Assumptions, Accounts, Roth Conversion, Scenarios
   - "Add Account" button
3. **Main Content**: Tabs for different views
   - Tab 1: Accumulation charts
   - Tab 2: Retirement charts
   - Tab 3: Custom Spending overrides
   - Tab 4: Data Tables (year-by-year)
   - Tab 5: Progress Tracking (baseline + check-ins)
   - Tab 6: Warnings & Notes
   - Tab 7: Monte Carlo Simulation

### Interaction

- Real-time updates: Charts and calculations update as inputs change
- Monte Carlo: on-demand via button click; results cached in session_state to avoid re-running on every widget interaction
- Input validation: Reasonable ranges, required fields
- Tooltips: Explain less obvious inputs
- Sensible defaults: Pre-populate with reasonable assumptions

### Hot-Reload Safety

Streamlit's hot-reload mechanism updates module objects in `sys.modules` when files change, but `from module import name` binds a stale reference at first import. Always use module-level imports in `app.py` to avoid stale function references:

```python
import charts as _charts      # correct — always does fresh attribute lookup
import montecarlo as _mc      # correct
# NOT: from charts import chart_drawdown  ← stale after hot-reload
```

## Sample Default Values

When the app loads, pre-populate with a sample scenario so users see something meaningful:

```
Profile:
- Current age: 35
- Retirement age: 65
- Life expectancy: 90
- Filing status: Married Filing Jointly
- State: California

Assumptions:
- Inflation: 3%
- Tax bracket inflation: 2.5%
- Safe withdrawal rate: 4%
- Retirement return: 5%
- Withdrawal strategy: Tax-Efficient

Accounts:
1. "401(k)" - Traditional 401k
   - Balance: $150,000
   - Annual contribution: $15,000
   - Employer match: 50% up to $3,000/yr
   - Contribution growth: 3%
   - Return: 7%

2. "Roth IRA" - Roth IRA
   - Balance: $40,000
   - Annual contribution: $7,000
   - Contribution growth: 0% (already maxed)
   - Return: 7%
```

## Code Organization

```
retirement_planner/
├── app.py                  # Main Streamlit app, layout, sidebar inputs, tab rendering
├── projections.py          # Accumulation phase calculations (all account types)
├── withdrawals.py          # Retirement phase calculations, withdrawal ordering, survivor logic
├── montecarlo.py           # Monte Carlo simulation engine (per-year/per-account randomized returns)
├── taxes.py                # Federal/state tax, LTCG, NIIT, IRMAA, SS taxability calculations
├── constants.py            # Tax brackets, LTCG thresholds, IRMAA tiers, RMD table, IRS limits
├── charts.py               # Plotly chart builders (accumulation, retirement, MC fan chart)
├── scenarios.py            # Save / load / delete / list scenario JSON files
├── scenarios/              # User scenario files (gitignored)
└── requirements.txt        # streamlit, plotly, pandas, numpy
```

## Implementation Notes

### Calculation Precision
- Use floats for all calculations
- Round display values to whole dollars
- Handle edge cases: zero balances, zero contributions, negative scenarios

### Performance
- 30-60 years of projections should calculate instantly in Python
- Monte Carlo with 1,000 trials runs in 2–5 seconds in pure Python; 5,000 is slower but feasible
- Use pandas DataFrames for year-by-year projection tables (easy to feed into Plotly)
- Streamlit re-runs the full script on each input change — keep calculations in pure functions so they're fast and side-effect free

### Session state and scenario auto-load

On startup, `_init_state()` automatically loads the **most recently modified** scenario file (via `latest_scenario()` which sorts by `st_mtime`). This ensures that after a browser refresh the user sees the scenario they were last working on, not an arbitrary alphabetically-sorted one.

Widget key naming convention for account checkboxes: use `chk_global_{account_id}` (not `a_*`) so the keys survive the `_apply_pending_load()` deletion sweep of `a_*` and `p_*` keys. Streamlit's widget binding survives `del st.session_state[key]`, so the prefix must stay outside the deletion range.

### State Structure

Use Python dataclasses or dicts stored in `st.session_state`:

```python
# Account (one per investment account)
{
  "id": str,
  "name": str,
  "type": str,  # 'traditional_401k' | 'roth_401k' | 'traditional_ira' | 'roth_ira'
                # | 'taxable' | 'bank' | 'hsa' | 'reit' | 'rental_property'
  "balance": float,          # for rental_property: current equity (value - mortgage)
  "basis": float,            # taxable / reit / rental_property only; defaults to 50% of balance
  "annual_contribution": float,        # not used for rental_property or reit
  "contribution_growth_rate": float,   # not used for rental_property or reit
  "return_rate": float,                # appreciation rate for rental_property; accumulation rate for others
  "use_global_return_rate": bool,      # retirement phase only; True = use global retirement_return_rate;
                                       # False = use this account's own return_rate; always False for bank/rental
  "employer_match_percent": float,     # 401k only, optional
  "employer_match_limit": float,       # 401k only, optional
  "qualified_dividend_yield": float,   # taxable / reit only; decimal (e.g. 0.015)
  "ordinary_income_yield": float,      # taxable / reit only; decimal (e.g. 0.005)
  "net_annual_rental_income": float,   # rental_property only; after all expenses
}

# Profile
{
  "current_age": int,
  "retirement_age": int,
  "life_expectancy": int,
  "filing_status": str,               # 'single' | 'married_filing_jointly'
  "state": str,                       # 'california' | 'other'
  "state_tax_rate": float,            # decimal; used when state == 'other'
  "current_income": float,            # optional; pre-tax annual salary
  "social_security_benefit": float,   # today's dollars (SSA.gov estimate)
  "social_security_start_age": int,
  # MFJ only:
  "spouse_age": int,
  "spouse_ss_benefit": float,         # today's dollars
  "spouse_ss_start_age": int,
  "survivor_spending_reduction": float,  # decimal; default 0.25
  # Healthcare:
  "pre_medicare_healthcare": float,   # annual cost before age 65
  "post_medicare_healthcare": float,  # annual cost from age 65 (excl. IRMAA surcharge)
}

# Assumptions
{
  "inflation_rate": float,            # general inflation (applied to spending target and healthcare)
  "bracket_inflation_rate": float,    # annual bracket/threshold scaling; default 0.025
  "safe_withdrawal_rate": float,
  "retirement_return_rate": float,    # global fallback; applied to accounts where use_global_return_rate=True
  "spending_mode": str,               # 'swr' | 'fixed'
  "annual_spending_target": float,    # used when spending_mode == 'fixed'; today's dollars after-tax ex-healthcare
  "withdrawal_strategy": str,         # 'tax_efficient' | 'roth_preservation'
}

# Roth Conversion Strategy
{
  "enabled": bool,
  "strategy": str,                    # 'fill_to_bracket' | 'fixed_amount'
  "target_bracket": float,            # decimal top of bracket, e.g. 0.12; fill_to_bracket only
  "fixed_amount": float,              # annual conversion amount; fixed_amount only
  "start_age": int,
  "end_age": int,
  "source_account_ids": list[str],    # list of Traditional account IDs to convert from (drawn proportionally)
  "destination_account_id": str,      # Roth account to convert into
  "allow_during_accumulation": bool,
}
```

### Testing Scenarios

Verify calculations against these scenarios:

1. **Simple case**: One 401k account, no employer match
2. **Roth-heavy**: Mostly Roth savings, verify tax-free withdrawals
3. **Early retirement**: Retire at 50, verify early withdrawal considerations (note: for simplicity, you can ignore early withdrawal penalties, or add a warning)
4. **Long retirement**: Live to 100, verify portfolio longevity
5. **High earner**: Large balances, verify higher tax brackets apply correctly

### 7. Scenario Save / Load

Persist the full app state (accounts, profile, assumptions, roth_conversion) to a named JSON file on disk so users can return to their work across sessions.

**Behavior:**
- A **scenario name** input (text field) lets users label their scenario (e.g. "Base Case", "Early Retirement")
- **Save** button: serializes `st.session_state` (accounts list, profile dict, assumptions dict, roth_conversion dict) to `scenarios/<name>.json`. Before saving, the handler explicitly reads all account widget keys from `st.session_state` (e.g. `a_bal_{id}`, `a_contrib_{id}`, `chk_global_{id}`) to capture values from collapsed expanders that may not have written back to the accounts list.
- **Load** dropdown: lists all `.json` files in the `scenarios/` folder; selecting one and clicking **Load** restores the full state
- **Delete** button: removes the selected scenario file
- **Auto-load on startup**: the app loads the most recently modified scenario automatically so the user resumes where they left off

**File format** (`scenarios/base_case.json`):
```json
{
  "scenario_name": "Base Case",
  "profile": { ... },
  "assumptions": { ... },
  "accounts": [ { ... }, { ... } ],
  "roth_conversion": { ... }
}
```

**Implementation notes:**
- Create the `scenarios/` directory on first save if it doesn't exist
- Validate the JSON structure on load and show a clear error if the file is malformed or from an incompatible version
- Add `scenarios/` to `.gitignore` so personal data isn't accidentally committed
- `scenarios.py` provides: `list_scenarios()`, `latest_scenario()` (most recently modified by mtime), `save_scenario()`, `load_scenario()`, `delete_scenario()`

### 8. Roth Conversion Modeling

Allow users to plan and simulate Roth conversions — moving money from Traditional 401(k)/IRA accounts to Roth accounts in low-income years to reduce future RMDs, lower lifetime taxes, and shrink SS taxation.

**User Inputs:**

- **Enable conversions**: toggle on/off
- **Conversion strategy** (radio button):
  - *Fill to bracket*: each eligible year, convert enough to bring ordinary income up to the top of a user-selected bracket (10%, 12%, 22%, or 24%). This is the most common planning approach.
  - *Fixed amount*: convert a specific dollar amount per year regardless of bracket position
- **Target bracket ceiling** (only for Fill to bracket): default 12%
- **Fixed conversion amount** (only for Fixed amount): $/year
- **Conversion window**:
  - Start age (default: retirement age)
  - End age (default: the earlier of SS start age − 1 or RMD start age − 1, i.e. age 72)
  - Allow the user to override both ends manually
- **Source accounts**: one or more Traditional accounts to convert from (draws proportionally from all selected sources based on their current balances)
- **Destination account**: which Roth account to convert into (dropdown of Roth accounts)

**Tax Treatment:**
- Converted amount is ordinary income in the year of conversion — it is added to the ordinary income bucket before tax is calculated
- The source Traditional account balance(s) decrease by the converted amount (proportional across sources); the destination Roth balance increases by the same amount
- State tax applies to conversion income at the configured state rate
- **Conversion taxes are funded by actual portfolio withdrawals** — after computing the conversion amount, the simulation adds an estimated conversion tax (`amount × target_bracket_rate`) to the year's spending need. Step 5 then withdraws this additional cash from taxable/bank accounts. This ensures the portfolio correctly reflects the real cost of conversions rather than having the tax silently reduce after-tax spending.

**Economic impact of conversions:**
- **Early years (conversion window):** portfolio is slightly smaller because conversion taxes are paid from taxable accounts now
- **Later years (RMD age+):** traditional accounts are smaller → smaller RMDs → lower taxable income → lower taxes → smaller required withdrawals → portfolio preserved longer
- **Net effect:** conversions are primarily a tax efficiency and longevity hedge, not a portfolio growth lever.

**5-Year Rule (early retirees):**
- Converted amounts must season 5 years before the converted principal can be withdrawn penalty-free if the account holder is under age 59½
- Track each conversion vintage (year → amount) so the app can flag which converted amounts are accessible penalty-free in any given year

### 9. Monte Carlo Simulation

Runs N independent trials (default 1,000) with randomized annual returns to model sequence-of-returns risk and show the probability that the portfolio survives to life expectancy.

**Core design:**
- Each trial independently draws per-year, per-account returns from a normal distribution
- Spending, Social Security (with COLA), healthcare, and survivor transition all follow the same logic as the deterministic simulation
- Results are cached in `st.session_state["mc_result"]` and only recomputed when the user clicks "Run Monte Carlo" — so adjusting other inputs does not re-trigger the expensive computation
- A staleness hint is shown if any MC parameter changes after the last run

**User Inputs (Monte Carlo tab):**
- **Equity Volatility** (slider, 1–30%, default 12%): standard deviation of annual equity returns. US equities: ~15–17%; balanced 60/40: ~10–12%; conservative: ~6–8%.
- **Stock Allocation** (slider, 0–100%, default 60%): fraction of each investment account (401k, IRA, Roth, taxable) modeled as equities. The remainder is bonds.
- **Bond Annual Return** (number input, default 3.5%): expected return on the bond portion. A live caption shows the resulting blended expected return.
- **Trials** (number input, 100–5,000, default 1,000)
- **Include market crash events** (checkbox, default off): schedules random −20% equity shocks every 10–20 years in each trial.

**Return model per account per year:**

For investment accounts (all except bank and rental property):
```
stock_r ~ N(stock_mean, equity_vol)          # equity draw
bond_r  ~ N(bond_return_rate, equity_vol × 0.30)  # bonds: ~30% as volatile
blended_r = stock_pct × stock_r + (1 − stock_pct) × bond_r
balance *= (1 + max(−0.60, blended_r))       # floor at −60%
```
Where `stock_mean` = the account's global retirement return rate (or its own rate if `use_global_return_rate=False`).

For bank accounts: `N(own_rate, equity_vol × 0.10)` — near-deterministic.
For rental property: `N(own_rate, equity_vol × 0.40)` — lower vol than equities, not split by stock/bond.

**Market crash model:**
- Each trial pre-schedules crash years at random 10–20 year intervals starting from retirement age
- In a crash year, equity accounts receive an additional shock AFTER the normal return:
  ```
  balance *= (1 − stock_pct × crash_magnitude)
  ```
  A 60/40 portfolio absorbs 60% of the −20% crash (net −12%); a 20/80 portfolio absorbs only 20% (net −4%). Bank and rental property accounts are not affected by crashes.

**Outputs:**
- **Success rate**: % of trials where the portfolio never hit $0 before life expectancy
- **Percentile fan chart**: 10th/25th/50th/75th/90th percentile portfolio bands by age, plus the deterministic baseline as a dashed overlay
- **Depletion histogram**: distribution of ages at which failed trials depleted (hidden when all trials succeed)
- **Summary metrics**: success rate, median and 10th-percentile portfolio at life expectancy, depleted trial count

**Withdrawal model in MC trials:**

The MC uses a simplified withdrawal order (bank → taxable → traditional → Roth) without the full tax optimization of the main simulation. This keeps trial time manageable while still capturing sequence-of-returns risk, which is the primary purpose of the MC analysis.

## Stretch Goals (Optional Enhancements)

If time permits, consider adding:

1. ~~**Roth Conversion Ladder**: Model converting Traditional to Roth in low-income years~~ *(promoted to core feature — see Section 8)*
2. ~~**Sequence of Returns Risk**: Monte Carlo simulation instead of fixed returns~~ *(promoted to core feature — see Section 9)*
3. ~~**Contribution Limits**: Enforce IRS limits with warnings~~ *(implemented in Warnings tab)*
4. ~~**Export/Import**: Save scenarios to JSON, load later~~ *(promoted to core feature — see Section 7)*
5. **Comparison Mode**: Show two scenarios side-by-side
6. **Print/PDF Report**: Generate a summary report
7. **Monte Carlo with inflation uncertainty**: Add a second volatility parameter for inflation draws
8. **QCDs**: Qualified Charitable Distributions from Traditional accounts (reduces RMD, not taxable)
9. **Part-time income**: Model phased retirement with declining earned income
10. **State tax diversity**: Support additional states beyond California + flat-rate

## Getting Started

1. Create a virtual environment: `python -m venv .venv && .venv\Scripts\activate`
2. Install dependencies: `pip install streamlit plotly pandas numpy`
3. Freeze deps: `pip freeze > requirements.txt`
4. Run the app: `streamlit run app.py`
5. Build out modules incrementally:
   - Start with data structures and `constants.py`
   - Build and unit-test calculation functions in `projections.py`, `taxes.py`, `withdrawals.py`
   - Wire up `app.py` sidebar inputs + `st.session_state` for accounts
   - Add charts via `charts.py` once calculations are verified
   - Add `montecarlo.py` and wire the Monte Carlo tab last
   - Polish layout and labels last

Focus on correctness of calculations first, then visualization, then polish.
