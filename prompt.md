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
- HSA: Pre-tax contributions, tax-free for medical (model as tax-free for simplicity)
- REIT (Taxable): Like taxable brokerage but distributions are predominantly ordinary income (not qualified dividends); basis tracked for LTCG on sale
- Rental Property: Equity appreciates annually; net rental income is ordinary income each year; on sale, gain above basis is taxed at LTCG rates (depreciation recapture not modeled in v1 — show a warning)

### 2. User Profile / Assumptions

**Personal Information:**
- Current age
- Planned retirement age
- Life expectancy (or "plan to age")
- Filing status (Single, Married Filing Jointly)
- State of residence (for state tax estimation, can simplify to a single state tax rate %)
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
- Pre-Medicare annual healthcare cost ($ per year; applies from retirement age until age 65; default: $15,000 for MFJ, $8,000 for Single — covers premiums + out-of-pocket)
- Post-Medicare annual healthcare cost ($ per year; applies from age 65 onward; default: $5,000 MFJ, $3,000 Single — covers Part B/D premiums + supplemental + out-of-pocket before IRMAA)
- These are added to the annual spending target and are inflation-adjusted each year

**Economic Assumptions:**
- Inflation rate (default: 3%)
- Safe withdrawal rate (default: 4%)
- Expected return during retirement (default: 5%, typically more conservative than accumulation)

**Social Security (Primary filer):**
- Estimated Social Security benefit ($ per year, in today's dollars)
- Social Security start age (default: 67)

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

- If `current_income` is provided in the Profile: estimate the user's federal marginal bracket from salary + investment income; apply that rate to ordinary income yields and the LTCG rate to qualified dividends.
- If no income is provided: assume 22% federal marginal rate and 15% LTCG rate as defaults, with a visible note to the user.
- Annual tax cost = `(ordinary_income × marginal_rate) + (qualified_div_income × ltcg_rate)`
- Show this as an annual cost line in the accumulation projection table (it does not reduce the account balance — the user pays it from other income — but it is a real cash drag to display).
- Add the accumulated annual tax drag to the summary stats as "Estimated taxes paid during accumulation."

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

**Step 3 — Roth conversions (optional; see Section 8 for full specification)**
- If Roth conversion strategy is enabled, calculate the conversion amount for this year per the user's chosen strategy
- Add conversion amount to ordinary income (it is taxable in the year converted)
- Move converted amount from the chosen Traditional account to the chosen Roth account
- Conversions happen before discretionary withdrawals so they consume bracket space first
- Do not convert in years where RMDs already push income above the target bracket ceiling

**Step 4 — Tax-free capital gains harvesting (taxable accounts)**
- Calculate remaining 0% LTCG headroom: `0% LTCG threshold - current taxable income`
  - MFJ: 0% up to $98,900 of taxable income; 15% up to $613,700; 20% above
  - Single: 0% up to $49,450; 15% up to $545,500; 20% above
- If headroom exists and taxable account has unrealized gains, realize gains up to the headroom limit (sell and immediately rebuy to step up basis)
- This does not generate cash for spending — it purely reduces future embedded gains
- **Important:** harvested gains must still be added to `ltcg_income` (even though taxed at 0%) so that MAGI is correctly computed for IRMAA and NIIT threshold tests in Step 6

**Step 5 — Meet spending needs (withdrawal ordering)**
- Annual spending target = base target (inflation-adjusted) + healthcare costs (inflation-adjusted)
  - Pre-65: add pre-Medicare healthcare cost
  - Age 65+: add post-Medicare healthcare cost (base; IRMAA surcharge added in Step 6 after income is known)
- Subtract passive income already collected in Step 1 to get remaining gap
- Withdraw remaining gap from accounts in this order:
  1. **Taxable brokerage / REIT** — only the gain portion is taxed at LTCG rates; basis returned tax-free
     - `gain_ratio = unrealized_gain / current_balance` — compute **before** reducing balance
     - `taxable_portion = withdrawal × gain_ratio` → taxed at LTCG rate
     - `basis_portion = withdrawal × (1 - gain_ratio)` → tax-free
     - Reduce account basis proportionally on each withdrawal
  2. **Traditional 401(k)/IRA** — fill remaining low ordinary income brackets (up to top of 22% if needed) before tapping Roth
  3. **Roth 401(k)/IRA** — use for any remaining spending need; always tax-free

**Step 6 — IRMAA and NIIT**

Before computing taxes, assemble the full **net investment income (NII)** figure that NIIT applies to:
```
nii = ordinary_dividend_income + qualified_dividend_income + ltcg_gains + rental_income
```
This includes ALL of: ordinary dividends from taxable accounts, qualified dividends, realized capital gains (including harvested gains from Step 4), and net rental income. Do **not** include SS or Traditional account withdrawals — those are not NII.

*NIIT:*
- If MAGI exceeds $250,000 MFJ / $200,000 Single, apply 3.8% NIIT to the lesser of **net investment income (as defined above)** or the excess MAGI above threshold
- NIIT thresholds are fixed (not inflation-adjusted)

*IRMAA (age 65+):*
- IRMAA surcharges are per person; apply to each Medicare-eligible spouse separately
- Based on 2026 MAGI thresholds (use current-year MAGI as a planning proxy rather than the 2-year lookback):

  | MAGI (MFJ) | MAGI (Single) | Part B surcharge/mo | Part D surcharge/mo |
  |---|---|---|---|
  | ≤ $218,000 | ≤ $109,000 | $0 (base $202.90) | $0 |
  | $218,001–$274,000 | $109,001–$137,000 | +$81.20 | +$14.50 |
  | $274,001–$342,000 | $137,001–$171,000 | +$203.70 | +$37.60 |
  | $342,001–$410,000 | $171,001–$205,000 | +$325.20 | +$60.60 |
  | $410,001–$750,000 | $205,001–$500,000 | +$406.90 | +$83.70 |
  | > $750,000 | > $500,000 | +$487.00 | +$91.00 |

- Annual IRMAA cost per Medicare-eligible person = `(Part B surcharge + Part D surcharge) × 12`
- For MFJ where both spouses are 65+, apply IRMAA twice
- Add IRMAA cost to the year's total tax/cost burden and to the after-tax spending cost
- Emit a warning whenever the user crosses an IRMAA tier threshold — these are income "cliffs" worth planning around

**Step 7 — Apply returns and advance year**
- Apply investment returns to remaining balances in each account:
  - Bank accounts and Rental Property always use their own `return_rate`
  - All other accounts: use the account's own `return_rate` if `use_global_return_rate` is `False`; otherwise use the global `retirement_return_rate` from Assumptions
- Grow taxable account basis by zero (returns accrue as unrealized gains until sold)
- Grow rental property equity: `equity *= (1 + appreciation_rate)`
- Inflate spending target by inflation rate (healthcare costs inflate at the same rate for simplicity)

**Tax Rates (2026)**

Ordinary income — Married Filing Jointly:
```
Standard Deduction: $32,200 (no tax on this amount)
10%: $0 – $24,800
12%: $24,800 – $100,800
22%: $100,800 – $211,400
24%: $211,400 – $403,550
32%: $403,550 – $512,450
35%: $512,450 – $768,700
37%: $768,700+
```

Ordinary income — Single:
```
Standard Deduction: $16,100 (no tax on this amount)
10%: $0 – $12,400
12%: $12,400 – $50,400
22%: $50,400 – $105,700
24%: $105,700 – $201,775
32%: $201,775 – $256,225
35%: $256,225 – $640,600
37%: $640,600+
```

Long-term capital gains — Married Filing Jointly:
```
0%:  $0 – $98,900 of taxable income
15%: $98,900 – $613,700
20%: $613,700+
+3.8% NIIT on investment income when MAGI > $250,000
```

Long-term capital gains — Single:
```
0%:  $0 – $49,450 of taxable income
15%: $49,450 – $545,500
20%: $545,500+
+3.8% NIIT on investment income when MAGI > $200,000
```

Add a configurable state tax rate (simple flat percentage applied to ordinary income and capital gains).

**California special rules (when `state == "california"`):**
- Capital gains are taxed as ordinary income (no preferential LTCG rate)
- Social Security is **fully excluded** from California taxable income — CA does not tax SS at all
- Implementation: `ordinary_income` passed into the tax function already includes only the **federal taxable SS amount** (`ss_taxable`). When computing CA state tax, subtract exactly `ss_taxable` (not the full gross SS benefit) from ordinary income, so CA sees non-SS income only. Subtracting the full SS benefit would over-exclude income that was never included.

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
- Warning flags: portfolio depletion before life expectancy, IRMAA tier crossings, RMD excess

### 5. Visualizations (using Plotly)

**Chart 1: Account Growth (Accumulation Phase)**
- Type: Stacked area chart
- X-axis: Age (current to retirement)
- Y-axis: Balance ($)
- Series: One for each account, stacked to show total
- Color-code by tax treatment (e.g., blue for pre-tax, green for Roth, orange for taxable)

**Chart 2: Portfolio Composition at Retirement**
- Type: Pie or donut chart
- Segments: Each account's ending balance
- Show percentage breakdown by tax treatment

**Chart 3: Retirement Drawdown**
- Type: Stacked area chart
- X-axis: Age (retirement to life expectancy)
- Y-axis: Remaining balance ($)
- Series: One for each account
- Show how each account depletes over time

**Chart 4: Annual Retirement Income**
- Type: Stacked bar chart
- X-axis: Age (retirement to life expectancy)
- Y-axis: Annual income ($)
- Series: 
  - Gross withdrawals (by account type)
  - Taxes paid (negative or separate color)
  - Social Security (if provided)
- Show after-tax spending line overlay

**Chart 5: Tax Burden Over Time**
- Type: Line chart
- X-axis: Age during retirement
- Y-axis: Annual taxes paid ($)
- Optional: Show effective tax rate as secondary y-axis

**Chart 6: Retirement Spending Coverage**
- Type: Stacked bar + line overlay (`barmode="relative"`)
- X-axis: Age during retirement
- Positive bars (stacked): Social Security, Rental Income, Dividends/Interest, RMDs, Portfolio Drawdown (all discretionary account draws grouped)
- Negative bars: Taxes (shown below zero) and Surplus Reinvested (passive income exceeding spending, also below zero)
- Line overlay: After-Tax Spending
- Identity that must hold: `sum(positive bars) - taxes - surplus = after_tax_spending line`
- The gap between the gross income bars and the spending line is entirely explained by the negative tax bar — no unexplained visual gap should exist

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
- Survivor transition year (SS reduction + tax rate change summary)
- Contribution limits exceeded (if implementing limits)
- Rental property depreciation recapture not modeled (always shown if user has a Rental Property account)

## UI/UX Requirements

### Layout

Use a clean, professional design with:

1. **Header**: App title, brief description
2. **Left Panel or Top Section**: Input forms
   - Collapsible sections for: Accounts, Profile, Assumptions
   - "Add Account" button
   - Clear visual hierarchy
3. **Main Content**: Charts and results
   - Tab navigation between different views (Accumulation, Retirement, Summary)
   - Charts should be responsive
4. **Summary Cards**: Key statistics always visible

### Interaction

- Real-time updates: Charts and calculations update as inputs change
- Input validation: Reasonable ranges, required fields
- Tooltips: Explain less obvious inputs (e.g., "Safe withdrawal rate")
- Sensible defaults: Pre-populate with reasonable assumptions
- Presets: Consider "Quick Start" templates (e.g., "Aggressive Saver", "Conservative")

### Responsive Design

- Works on desktop and tablet
- Mobile: Stack panels vertically, charts remain usable

## Sample Default Values

When the app loads, pre-populate with a sample scenario so users see something meaningful:

```
Profile:
- Current age: 35
- Retirement age: 65
- Life expectancy: 90
- Filing status: Married Filing Jointly
- State tax rate: 5%

Assumptions:
- Inflation: 3%
- Safe withdrawal rate: 4%
- Retirement return: 5%

Accounts:
1. "401(k)" - Traditional 401k
   - Balance: $150,000
   - Annual contribution: $15,000
   - Employer match: 50% up to 6% of salary (assume $100k salary = $3,000 match)
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
├── app.py                  # Main Streamlit app, layout, and sidebar inputs
├── projections.py          # Accumulation phase calculations (all account types)
├── withdrawals.py          # Retirement phase calculations, withdrawal ordering, survivor logic
├── taxes.py                # Federal/state tax, LTCG, NIIT, IRMAA, SS taxability calculations
├── constants.py            # Tax brackets, LTCG thresholds, IRMAA tiers, RMD table, IRS limits
├── charts.py               # Plotly chart builders
├── scenarios.py            # Save / load / delete scenario JSON files
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
- Use pandas DataFrames for year-by-year projection tables (easy to feed into Plotly)
- Streamlit re-runs the full script on each input change — keep calculations in pure functions so they're fast and side-effect free

### State Structure

Use Python dataclasses or dicts stored in `st.session_state`:

```python
# Account (one per investment account)
{
  "id": str,
  "name": str,
  "type": str,  # 'traditional_401k' | 'roth_401k' | 'traditional_ira' | 'roth_ira'
                # | 'taxable' | 'hsa' | 'reit' | 'rental_property'
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
  "state_tax_rate": float,            # decimal
  "current_income": float,            # optional; pre-tax annual salary
  "social_security_benefit": float,   # optional; primary filer
  "social_security_start_age": int,   # optional; primary filer
  # MFJ only:
  "spouse_age": int,                  # optional
  "spouse_retirement_age": int,       # optional
  "spouse_ss_benefit": float,         # optional
  "spouse_ss_start_age": int,         # optional
  "survivor_spending_reduction": float,  # decimal; default 0.25
  # Healthcare:
  "pre_medicare_healthcare": float,   # annual cost before age 65
  "post_medicare_healthcare": float,  # annual cost from age 65 (excl. IRMAA surcharge)
}

# Assumptions
{
  "inflation_rate": float,
  "safe_withdrawal_rate": float,
  "retirement_return_rate": float,  # global fallback; applied to accounts where use_global_return_rate=True
}

# Roth Conversion Strategy
{
  "enabled": bool,
  "strategy": str,                  # 'fill_to_bracket' | 'fixed_amount'
  "target_bracket": float,          # decimal top of bracket, e.g. 0.12; fill_to_bracket only
  "fixed_amount": float,            # annual conversion amount; fixed_amount only
  "start_age": int,
  "end_age": int,
  "source_account_id": str,         # Traditional account to convert from
  "destination_account_id": str,    # Roth account to convert into
  "allow_during_accumulation": bool,
  # Runtime state (not user input — computed each year):
  "conversion_vintages": dict,      # {year: amount} for 5-year rule tracking
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

Persist the full app state (accounts, profile, assumptions) to a named JSON file on disk so users can return to their work across sessions.

**Behavior:**
- A **scenario name** input (text field) lets users label their scenario (e.g. "Base Case", "Early Retirement")
- **Save** button: serializes `st.session_state` (accounts list, profile dict, assumptions dict) to `scenarios/<name>.json`
- **Load** dropdown: lists all `.json` files in the `scenarios/` folder; selecting one and clicking **Load** restores the full state
- **Delete** button: removes the selected scenario file

**File format** (`scenarios/base_case.json`):
```json
{
  "scenario_name": "Base Case",
  "profile": { ... },
  "assumptions": { ... },
  "accounts": [ { ... }, { ... } ]
}
```

**Implementation notes:**
- Create the `scenarios/` directory on first save if it doesn't exist
- Validate the JSON structure on load and show a clear error if the file is malformed or from an incompatible version
- Add `scenarios/` to `.gitignore` so personal data isn't accidentally committed

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
- **Source account**: which Traditional account to convert from (dropdown of Traditional accounts; default: largest Traditional balance)
- **Destination account**: which Roth account to convert into (dropdown of Roth accounts; default: largest Roth balance)
- **Allow conversions during accumulation**: toggle (off by default); enables conversions in working years when income may be temporarily low

**Tax Treatment:**
- Converted amount is ordinary income in the year of conversion — it is added to the ordinary income bucket before tax is calculated
- Conversion does not count as a withdrawal for spending purposes; it is a pre-payment of future taxes
- The source Traditional account balance decreases by the converted amount; the destination Roth balance increases by the same amount
- State tax applies to conversion income at the configured state rate

**5-Year Rule (early retirees):**
- Converted amounts must season 5 years before the converted principal can be withdrawn penalty-free if the account holder is under age 59½
- Track each conversion vintage (year → amount) so the app can flag which converted amounts are accessible penalty-free in any given year
- If a user is already 59½ or older at conversion, the 5-year rule on the converted principal does not apply (though the 5-year rule on Roth account earnings still applies if the account is less than 5 years old)
- Display a warning if a withdrawal plan would access a conversion vintage before it has seasoned and the user is under 59½

**Impact Display:**
- Show a side-by-side comparison (or toggle) of key metrics with and without the conversion strategy:
  - Projected RMD amounts by age (lower with conversions)
  - Lifetime taxes paid (typically lower with conversions)
  - Portfolio longevity (often longer with conversions)
  - SS taxability (lower with conversions, since RMDs raise combined income)
- Show annual conversion amounts as a separate series in Chart 4 (Annual Retirement Income)
- Add a "Conversion Summary" row to the year-by-year retirement table: conversion amount, tax cost of conversion, net Roth balance after conversion

**Integration with retirement phase calculation:**
- Conversions execute in Step 3 of each retirement year loop
- After conversion, the updated bracket position determines how much room remains for discretionary Traditional withdrawals in Step 5
- If RMDs in a given year already exceed the target bracket ceiling, skip the conversion for that year (no point converting if already above target)

## Stretch Goals (Optional Enhancements)

If time permits, consider adding:

1. ~~**Roth Conversion Ladder**: Model converting Traditional to Roth in low-income years~~ *(promoted to core feature — see Section 8)*
2. **Sequence of Returns Risk**: Monte Carlo simulation instead of fixed returns
3. **Contribution Limits**: Enforce IRS limits with warnings
4. ~~**Export/Import**: Save scenarios to JSON, load later~~ *(promoted to core feature — see Section 7)*
5. **Comparison Mode**: Show two scenarios side-by-side
6. **Print/PDF Report**: Generate a summary report

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
   - Polish layout and labels last

Focus on correctness of calculations first, then visualization, then polish.