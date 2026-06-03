# Retirement Planner — User Guide

> **This is a local Python app** — it runs entirely on your computer, not in the cloud. Before using it you will need Python, a few packages, and a terminal. See the [Installation Instructions](InstallationInstructions.md) for a step-by-step setup guide.

## Table of Contents

1. [What This App Does](#1-what-this-app-does)
2. [The Sidebar: Setting Up Your Plan](#2-the-sidebar-setting-up-your-plan)
   - [Profile](#profile)
   - [Assumptions](#assumptions)
   - [Accounts](#accounts)
   - [Roth Conversion](#roth-conversion)
   - [Scenarios: Saving and Loading Plans](#scenarios-saving-and-loading-plans)
3. [The Main Tabs](#3-the-main-tabs)
   - [Accumulation](#-accumulation)
   - [Retirement](#-retirement)
   - [Custom Spending](#-custom-spending)
   - [Data Tables](#-data-tables)
   - [Progress](#-progress)
   - [Warnings](#-warnings)
   - [Monte Carlo](#-monte-carlo)
   - [Optimizer](#-optimizer)
   - [Accounts](#-accounts)
4. [Key Concepts Explained Simply](#4-key-concepts-explained-simply)
5. [What This Tool Does Not Cover](#5-what-this-tool-does-not-cover)
6. [Technical Reference: How the Math Works](#6-technical-reference-how-the-math-works)
   - [How Taxes Are Calculated](#how-taxes-are-calculated)
   - [How Withdrawals Are Sequenced](#how-withdrawals-are-sequenced)
   - [How the Monte Carlo Simulation Works](#how-the-monte-carlo-simulation-works)
   - [How the Optimizer Works](#how-the-optimizer-works)

---

## 1. What This App Does

This app answers the most important financial question most people face: **Will I have enough money to last through retirement?**

It does this by:

- **Projecting your savings** from today to retirement, watching how each account grows with contributions and investment returns
- **Simulating retirement withdrawals** year by year, pulling money from your accounts in the most tax-efficient order possible
- **Modeling taxes in detail** — federal brackets, capital gains rates, Social Security taxation, Medicare surcharges, and state taxes — so your projections reflect what you'll actually keep, not just what's in your accounts
- **Stress-testing your plan** with thousands of simulated market sequences to show what happens when returns are bad early in retirement (sequence-of-returns risk)
- **Finding a better strategy** automatically, searching for the combination of Social Security timing, withdrawal order, and Roth conversions that leaves you the most money after taxes

The app is not a substitute for professional financial advice, but it is one of the most realistic retirement projection tools available, modeling the same tax complexity that fee-only financial planners use.

---

## 2. The Sidebar: Setting Up Your Plan

The left sidebar contains all your inputs organized into collapsible sections.

### Profile

Your personal information that shapes the entire projection.

| Input | What It Means |
|-------|---------------|
| **Current Age** | Your age today |
| **Retirement Age** | When you plan to stop working |
| **Life Expectancy** | How long to plan for. Choosing a higher number (e.g., 95) is more conservative |
| **Filing Status** | Single or Married Filing Jointly — affects tax brackets and standard deduction |
| **State** | California and Montana use progressive state tax brackets. All other states use a flat rate you specify |
| **Current Annual Income** | Your pre-tax salary — used to estimate your current tax bracket during the savings phase |
| **Social Security Benefit** | Your estimated annual benefit in *today's* dollars (as shown on ssa.gov) |
| **SS Start Age** | When you'll begin collecting. Ages 62–70 are valid; delaying increases the monthly benefit |

**If you're Married:**

You'll also enter your spouse's age, retirement age, Social Security benefit, and SS start age. There's also a **Survivor Spending Reduction** (default 25%) — when one spouse passes, total spending typically drops because some fixed costs (housing) don't change while income falls.

**Healthcare costs:**

- **Pre-Medicare** (before age 65): the annual cost of health insurance and out-of-pocket expenses when you're not yet on Medicare. Default: $15,000/year.
- **Post-Medicare** (age 65+): Part B premiums, supplemental/Medigap, dental, vision, and out-of-pocket costs. Default: $12,000/year. IRMAA surcharges (income-based Medicare penalties) are calculated separately and added on top.

Both amounts inflate each year with the general inflation rate.

---

### Assumptions

Economic inputs that drive the entire projection.

| Input | What It Means | Default |
|-------|---------------|---------|
| **Inflation Rate** | How fast prices rise each year. Your spending target and healthcare costs grow at this rate | 3% |
| **Tax Bracket Inflation** | How fast IRS brackets and thresholds adjust. Set lower than inflation to model bracket creep | 2.5% |
| **Retirement Return Rate** | Average annual return on your portfolio during retirement. Used for accounts set to "global rate" | 6.5% |
| **Spending Mode** | See below | — |
| **Withdrawal Strategy** | See below | Tax-Efficient |

**Spending Modes:**

- **% of Portfolio (SWR):** Each year you withdraw a fixed percentage of your *starting* retirement portfolio. The classic "4% rule" uses this mode. Your spending amount is locked at a real (inflation-adjusted) level — it doesn't shrink if your portfolio shrinks.
- **Fixed Dollar Amount:** You target a specific after-tax dollar amount each year in today's money (the app inflates it to future dollars automatically). Use this if you have a specific lifestyle cost in mind.

**Withdrawal Strategies:**

- **Tax-Efficient (default):** Each year, the app first withdraws from traditional accounts (401k/IRA) up to the top of the 22% federal tax bracket, then draws Roth funds tax-free for anything remaining. This keeps your tax bill low in the current year.
- **Roth Preservation:** Drains traditional accounts completely before touching Roth. Accepts higher taxes now to let Roth accounts grow tax-free longer and to reduce future Required Minimum Distributions (RMDs). Better if you expect to be in a higher bracket later.

---

### Accounts

You can add as many accounts as you have. Each account has a type that determines how it's taxed.

**Account Types:**

| Type | Tax on Contributions | Tax on Withdrawals |
|------|---------------------|-------------------|
| Traditional 401(k) | Pre-tax (reduces today's income) | Ordinary income tax |
| Roth 401(k) | After-tax (no deduction) | Tax-free |
| Traditional IRA | Pre-tax (if deductible) | Ordinary income tax |
| Roth IRA | After-tax | Tax-free |
| Taxable Brokerage | After-tax | Capital gains tax on profits; dividends taxed annually |
| HSA | Pre-tax | Tax-free for medical |
| Bank / Cash | After-tax | No capital gains; interest may be taxable |
| REIT (Taxable) | After-tax | REIT distributions mostly ordinary income; gains at capital gains rates |
| Rental Property | After-tax (equity tracking) | Gain above basis taxed at capital gains rates |

**Key account settings:**

- **Balance:** Current market value. For Rental Property, enter your equity (property value minus remaining mortgage).
- **Return Rate:** Annual capital appreciation. For brokerage/REIT accounts, this is *price appreciation only* — dividends are entered separately.
- **Use Global Retirement Return Rate:** When checked, this account earns the global Retirement Return Rate during retirement instead of its own rate. Useful for simplicity. Bank and Rental accounts always use their own rate.
- **Annual Contribution:** What you're adding each year. 401(k) and IRA limits are enforced with warnings.
- **Employer Match (401k only):** Enter the match percentage and the annual dollar cap.
- **Cost Basis (Taxable/REIT/Rental):** What you paid for assets you hold. The difference between current balance and basis is your unrealized gain, which will be taxed when sold. If you don't know your basis, the app defaults to 50% of balance and shows a warning.
- **Qualified Dividend Yield:** Dividends that qualify for preferential (lower) capital gains tax rates. Default: 1.5% for brokerage, 0% for REIT.
- **Ordinary Income Yield:** Dividends/distributions taxed at ordinary income rates (non-qualified dividends, interest, REIT distributions). Default: 0.5% for brokerage, 4% for REIT.
- **Withdraw Priority:** For taxable accounts, set to "Last Resort" to hold it until all other accounts are exhausted (useful if you want to preserve a taxable account for heirs or a large purchase).
- **Bank Cash Buffer:** Amount of cash in a bank account that's never touched in the plan — it stays as an emergency reserve.
- **Net Annual Rental Income:** Annual cash from a rental property after all expenses (mortgage, taxes, insurance, maintenance). This is treated as ordinary income each year.

---

### Roth Conversion

Roth conversions move money from a Traditional account (401k or IRA) into a Roth account. You pay income tax on the converted amount now, but then that money grows and is withdrawn tax-free forever. This is most powerful in the gap between retirement and when Social Security and RMDs kick in — when your income is temporarily low.

| Input | What It Means |
|-------|---------------|
| **Enable Conversions** | Toggle on to activate |
| **Strategy** | *Fill to Bracket*: convert enough to use up your target bracket each year. *Fixed Amount*: convert a specific dollar figure every year |
| **Target Bracket** | For Fill to Bracket: top of 10%, 12%, 22%, or 24% marginal bracket |
| **Start Age / End Age** | The window during which conversions happen. Default end is just before RMDs start (age 73) or SS starts, whichever is earlier |
| **Source Accounts** | Which traditional accounts to convert from (drawn proportionally) |
| **Destination** | Which Roth account receives the conversion |

Conversion taxes are paid out of your portfolio (from bank/taxable accounts), so the app correctly accounts for the real cost rather than letting it silently reduce your spending.

---

### Scenarios: Saving and Loading Plans

The Scenarios section lets you save your current plan to a named file and load it back later. This is how you compare alternatives — save a "Base Case" and a "Retire at 60" scenario, then switch between them to compare outcomes.

- **Save:** Type a name and click Save. The entire plan (all accounts, all inputs) is stored as a file.
- **Load:** Select a saved scenario from the dropdown and click Load. The app also auto-loads your most recently used scenario when you open it.
- **Delete:** Removes a saved scenario file.

Scenario files are stored locally on your computer and never leave your machine.

> **Note:** The app ships with several scenarios named `test_*` (e.g., `test_median_couple`, `test_fire_single`). These exist solely to verify the app is working correctly and can be safely deleted from the Load dropdown once you've created your own plan.

---

## 3. The Main Tabs

### 📈 Accumulation

Shows your portfolio growing from today to retirement.

**What you'll see:**
- A stacked area chart showing each account's balance over time, color-coded by tax type (pre-tax, Roth, taxable, real estate, cash)
- A donut chart showing how your retirement nest egg is split by account type on retirement day
- Summary metrics: total portfolio at retirement, and the breakdown between pre-tax, Roth, and taxable money

**What it's telling you:** How much you'll have when you stop working, and in what tax buckets. The bucket mix matters — $1M in a Roth is worth more than $1M in a Traditional IRA, because you'll pay income tax on every dollar you withdraw from the IRA.

If you're already retired (current age ≥ retirement age), the accumulation tab will be empty — skip straight to Retirement.

---

### 💰 Retirement

The heart of the app. Shows your year-by-year financial life from retirement to life expectancy.

**What you'll see:**

1. **Drawdown chart:** Your portfolio balance falling over time, with each account stacked. There's a dashed line showing your total portfolio in *today's purchasing power* (adjusted for inflation) — a flat or slowly declining dashed line means your real wealth is being preserved.

2. **Annual Income chart:** A stacked bar showing all your income sources each year (Social Security, rental income, dividends, 401k/IRA withdrawals, Roth withdrawals). Taxes are shown as a negative bar going down. The solid line is your actual after-tax spending in nominal (future) dollars; the dashed line is that same spending in today's purchasing power — it should stay roughly flat if inflation is being handled correctly.

3. **Tax Burden chart:** How your tax bill breaks down each year — federal ordinary income tax, capital gains tax, NIIT (investment income surtax), IRMAA (Medicare surcharge), and state tax — plus your effective tax rate.

4. **Spending Coverage chart:** Where every dollar of your retirement comes from and goes. Positive bars are income sources; negative bars are taxes and any money reinvested back into the portfolio (a good sign — means you're spending less than you could).

**Summary metrics** show lifetime taxes paid, lifetime healthcare costs, how long the portfolio lasts, and your sustainable monthly withdrawal.

---

### ✏️ Custom Spending

Lets you override your spending target for specific years. Useful for modeling:

- A high-spending early retirement ("go-go years") followed by lower spending later
- A one-time large expense (vacation home, wedding gift to children)
- Gradual spending reduction as you age

Set a year's spending to 0 to revert it back to the default calculated target. You can enter amounts as a fixed after-tax number or as a gross (pre-tax) number.

---

### 📋 Data Tables

Shows the raw numbers behind the charts as downloadable year-by-year tables.

- **Accumulation table:** Balance in each account at every age during the savings phase
- **Account balances:** Year-by-year account balances during retirement
- **Full retirement detail:** Everything — income sources, withdrawals, taxes, healthcare, spending — in one comprehensive table

Useful for detailed review or for copying numbers into a spreadsheet.

---

### 📊 Progress

Tracks how your actual results compare to your plan over time.

**Workflow:**
1. **Capture baseline:** When you first finalize your plan, click "Capture Baseline" to save the projected balances as your reference point.
2. **Annual check-in:** Once a year, enter your actual account balances. The app shows how you're tracking versus the projection.
3. **Update scenario:** Optionally, update your scenario with the actual balances (and your new current age) so future projections start from where you actually are.

The variance charts show you whether you're ahead or behind, and by how much, across your entire account portfolio.

---

### ⚠️ Warnings

A dedicated tab showing anything that needs your attention:

- **Portfolio depletion:** If the plan runs out of money before life expectancy
- **IRMAA thresholds:** If your Medicare surcharges jump to a higher tier (and by how much), or if you're within $10,000 of the next tier
- **RMD excess:** Years when Required Minimum Distributions force you to take out more than your spending target (the excess goes back into your taxable account, but taxes are still owed)
- **Contribution limit violations:** If any of your planned contributions exceed 2026 IRS limits for 401(k), IRA, or HSA accounts

Review this tab first — if anything is flagged here, your plan needs adjustment.

---

### 🎲 Monte Carlo

The most important tab for understanding *risk* (as opposed to the Retirement tab, which shows the *expected* outcome).

**What it does:** Runs your retirement plan 1,000 to 10,000 times, each time with a different sequence of annual market returns drawn randomly. Some runs have bad markets early (the worst case for a retiree — you sell shares at low prices to cover spending). Some have good markets early. The spread shows you the range of plausible outcomes.

**How to read the fan chart:**
- The **dark band** (25th–75th percentile) is where half of all outcomes land — your most likely range
- The **light band** (10th–90th percentile) shows the extremes
- The **solid line** is the median outcome (50th percentile)
- The **dashed line** is your deterministic baseline (the same projection as the Retirement tab)
- If the **10th percentile line stays above $0**, your plan is robust even in bad markets

**Success Rate:** The percentage of trials where your portfolio never hit $0 before your life expectancy. Targets by common planning standards:
- 95%+: Very safe (you may be over-saving)
- 90–95%: Strong (standard CFP target)
- 80–90%: Moderate (consider having a backup plan)
- Below 80%: Needs revision

**Settings to know:**

| Setting | What to Set |
|---------|-------------|
| **Return Model** | Use **CMA Log-Normal** (recommended). More realistic than the Standard model. |
| **Equity Volatility** | How volatile stocks are. Default 16% is calibrated to historical US equities. |
| **Bond Volatility** | How volatile bonds are. Default 6%. |
| **Number of Trials** | 1,000 is fast. 5,000–10,000 gives more stable percentiles. |
| **Withdrawal Rule** | *Constant Real*: you spend the same inflation-adjusted amount every year. *Guyton-Klinger Guardrails*: you cut spending 10% when the market is bad and raise it 10% when things are going well — this improves success rates significantly. |
| **Spending Floor** | Only available with Guyton-Klinger. A minimum annual discretionary spend in today's dollars that guardrail cuts can never breach. Healthcare and taxes are always paid on top. Set to 0 to disable. |

> The app displays a note when current market valuations (CAPE) are historically elevated, suggesting forward returns may be below the long-run average.

---

### 🔍 Optimizer

The Optimizer tries to find a *better* retirement strategy than whatever you've currently configured.

**What it searches:** Hundreds of combinations of (1) Social Security start ages, (2) Tax-Efficient vs. Roth Preservation withdrawal strategy, and (3) whether to do Roth conversions — and if so, at what bracket level and over what years. Conversions are automatically constrained to stay below IRMAA or ACA income cliffs where applicable.

**How to use it:**
1. Leave your current settings as-is (this becomes the "baseline" to beat)
2. Set **Number of Trials** (500 is a good balance of speed and thoroughness)
3. Set **Legacy Weight** — how much you care about leaving money to heirs vs. maximizing your own spending. Higher weight biases the optimizer toward strategies that preserve the portfolio.
4. Click **Run Optimizer**
5. Compare the results table: Baseline vs. Best Found

**What the output shows:**
- **Comparison table:** How much lifetime spending, lifetime taxes, and final portfolio value differ between your current strategy and the optimizer's best find
- **Recommended Strategy:** Plain-language description of what to do differently, including the recommended Social Security start ages and whether to stay below the IRMAA or ACA income cliff
- **Year-by-year actions table:** Color-coded cash flows. Red = money leaving an account (withdrawals). Green = Roth conversion receipts. Amber = taxes/healthcare. Blue = passive income (Social Security, dividends, rental). Bold green = your total after-tax spending
- **Score distribution:** A histogram of all strategies tested, with your baseline and the best result marked. The wider the spread, the more room there is for improvement.

The Optimizer does not automatically apply its recommendations to your scenario — you apply them manually in the sidebar if you agree with the strategy.

---

### 🏦 Accounts

A spreadsheet-style editor for quickly updating account values without expanding the sidebar expanders one by one.

Edit current balance, cost basis, return rate, dividend yields, and the "use global rate" flag for each account. Click **Apply Changes** to update the projections, or **Save to Scenario** to write the changes to disk.

Useful for annual updates when you know your new balances but don't need to change anything else.

---

## 4. Key Concepts Explained Simply

**Required Minimum Distributions (RMDs):** The IRS requires you to start withdrawing from Traditional 401(k) and IRA accounts at age 73, whether you want to or not. The minimum is calculated as your account balance divided by a life-expectancy factor from an IRS table (roughly your remaining life expectancy). RMDs count as ordinary income — they can push you into higher tax brackets and increase your Medicare costs. Roth accounts have no RMDs.

**The 0% Capital Gains Zone:** If your ordinary income is low enough, your investment gains (from selling stocks or receiving qualified dividends) are taxed at *zero percent*. For Married Filing Jointly, ordinary income below roughly $98,900 (in 2026) is in the 0% capital gains bracket. The app automatically takes advantage of this by harvesting gains from your taxable account in years when you have space — locking in those gains tax-free and resetting your cost basis higher.

**IRMAA (Medicare Surcharges):** Medicare Part B and Part D premiums go up in steps based on your income from two years prior. In 2026, a married couple with income under $218,000 pays the standard premium. Above that, surcharges kick in — and they're cliffs, meaning going $1 over a threshold can cost $1,148 more per year per person (combined Part B + Part D surcharge). The Warnings tab flags when you're near a cliff.

**NIIT (Net Investment Income Tax):** A 3.8% surtax on investment income (dividends, gains, rental income) that kicks in when your Modified Adjusted Gross Income exceeds $250,000 (married) or $200,000 (single). It applies to the *lesser* of your investment income or the excess above the threshold.

**Social Security Taxation:** Social Security benefits are not fully tax-free. Depending on your total income, up to 85% of your SS benefit may be subject to federal income tax. The thresholds ($32,000 and $44,000 for married couples) have *not* been adjusted for inflation since 1984, meaning they effectively tax more and more of people's benefits every year as incomes rise.

**Sequence-of-Returns Risk:** If the market crashes in the first few years of your retirement, you're forced to sell investments at low prices to cover living expenses. Those shares are gone and can't recover with the market. A bad early sequence can deplete a portfolio that would otherwise have lasted — even if the *average* return over retirement is exactly what you planned. This is why Monte Carlo simulation matters more than a single projection.

**Bracket Creep:** Tax brackets are adjusted for inflation each year (by the "Tax Bracket Inflation" rate), but some thresholds are not — most importantly, the Social Security taxability thresholds, which have been frozen since 1984. As nominal incomes rise with inflation, more income falls into higher brackets and more SS becomes taxable, even if real purchasing power hasn't changed.

---

## 5. What This Tool Does Not Cover

This app models retirement cash flows and taxes in depth, but it is **not a total wealth calculator**. Understanding what is excluded helps you use it correctly and seek additional guidance where needed.

**Real estate and physical assets**
- Your primary home value is not included. There are no calculations for downsizing, reverse mortgages, or the proceeds from selling a home. If you plan to tap home equity in retirement, you would need to manually model that as an account or income source.
- Personal property (vehicles, collectibles, jewelry) is not tracked or liquidated in any scenario.

**Inheritances and gifts**
- Expected inheritances are not modeled — neither receipt nor bequest. If you anticipate a significant inheritance, add it as a one-time custom spending credit in the year you expect it. Charitable giving, donor-advised funds, and estate planning strategies (trusts, stepped-up basis at death) are outside scope.

**Late-life and long-term care**
- Healthcare costs are modeled as a fixed annual amount that grows with inflation. The app does not simulate nursing home costs ($5,000–$15,000/month), assisted living, memory care, or the Medicaid asset-spend-down rules that govern how LTC costs interact with savings. If long-term care is a concern, model a manual spending override in the Custom Spending tab for those years.

**Portfolio allocation and investment strategy**
- The app takes your expected return rate as a given — it does not recommend or optimize asset allocation (stocks vs. bonds vs. alternatives), rebalancing schedules, or glide paths. It also does not model tax-loss harvesting beyond simple basis tracking, individual security selection, or alternatives like private equity and commodities.

**Insurance and liabilities**
- Life insurance proceeds, disability insurance income, and long-term care insurance benefits are not modeled. Debt (mortgage balance, car loans, student loans) is not tracked; if you have significant outstanding debt, it will affect your actual spending need in ways the app cannot see.

**Pensions and annuities**
- Defined-benefit pensions can be approximated by entering the annual payment as custom income in the Retirement tab, but the app does not model lump-sum vs. annuity trade-offs, survivor annuity options, or inflation-adjusted pension COLAs separately from the general inflation rate. True annuity products (variable, fixed-index) are not modeled.

**Business interests**
- Equity in a private business, partnership, or S-corp is not tracked. Business sale proceeds would need to be added manually as a one-time event.

**Multi-state and international scenarios**
- State taxes are modeled for California and Montana only; all other states use a flat rate. There is no multi-state scenario (e.g., planning a mid-retirement relocation), no state-specific treatment of pension or RMD income, and no foreign tax credits or expatriate scenarios.

---

## 6. Technical Reference: How the Math Works

This section describes the calculations in precise terms for users who want to understand the methodology.

---

### How Taxes Are Calculated

Taxes are computed fresh each year of the retirement simulation, in this order:

#### Step 1: Assemble Ordinary Income

Ordinary income includes:
- **RMDs** from Traditional accounts (age 73+)
- **Discretionary withdrawals** from Traditional accounts (401k/IRA)
- **Rental income** (net cash after expenses)
- **Ordinary dividends and interest** (from taxable brokerage and REIT accounts)
- **Roth conversion amount** (if conversions are enabled)
- **Taxable portion of Social Security** (calculated in Step 2)

#### Step 2: Calculate Social Security Taxability

The IRS uses "provisional income" to determine how much of your SS is taxable:

```
Provisional Income = Ordinary Income (ex-SS) + 50% × Total SS Benefit
```

| Provisional Income (MFJ) | Provisional Income (Single) | SS Taxable % |
|--------------------------|----------------------------|--------------|
| Under $32,000 | Under $25,000 | 0% |
| $32,000–$44,000 | $25,000–$34,000 | Up to 50% of income above lower threshold |
| Over $44,000 | Over $34,000 | 50% of middle band + 85% of excess above upper threshold, capped at 85% of total SS |

These thresholds are *not* indexed to inflation — they've been frozen since 1984.

#### Step 3: Federal Ordinary Income Tax

Applied to (Ordinary Income − Standard Deduction) using 2026 brackets, scaled annually by the Tax Bracket Inflation Rate:

**Married Filing Jointly:**
| Taxable Income | Rate |
|---------------|------|
| $0 – $24,800 | 10% |
| $24,800 – $100,800 | 12% |
| $100,800 – $211,400 | 22% |
| $211,400 – $403,550 | 24% |
| $403,550 – $512,450 | 32% |
| $512,450 – $768,700 | 35% |
| $768,700+ | 37% |
Standard Deduction: $32,200

**Single:**
| Taxable Income | Rate |
|---------------|------|
| $0 – $12,400 | 10% |
| $12,400 – $50,400 | 12% |
| $50,400 – $105,700 | 22% |
| $105,700 – $201,775 | 24% |
| $201,775 – $256,225 | 32% |
| $256,225 – $640,600 | 35% |
| $640,600+ | 37% |
Standard Deduction: $16,100

All bracket thresholds are multiplied by `(1 + bracket_inflation_rate)^years_since_retirement` each year.

#### Step 4: Long-Term Capital Gains Tax

Qualified dividends and capital gains from selling taxable assets are taxed at preferential rates, *stacking on top of* ordinary income:

**MFJ:** 0% up to $98,900 combined income; 15% up to $613,700; 20% above  
**Single:** 0% up to $49,450; 15% up to $545,500; 20% above

When selling from a taxable account, only the gain portion is taxable:
```
Gain Ratio = (Balance − Basis) / Balance
Taxable Portion = Withdrawal × Gain Ratio   ← taxed at LTCG rates
Basis Return = Withdrawal × (1 − Gain Ratio) ← tax-free
```

#### Step 5: Net Investment Income Tax (NIIT)

A 3.8% surtax applies when MAGI (Modified Adjusted Gross Income) exceeds the threshold:

```
NIIT = 3.8% × min(Net Investment Income, MAGI − Threshold)
```

Threshold: $250,000 MFJ / $200,000 Single (scaled by bracket inflation)

Net Investment Income includes: qualified dividends, ordinary dividends, capital gains, rental income. It does *not* include Social Security or Traditional account withdrawals.

#### Step 6: IRMAA Medicare Surcharges (Age 65+)

Income-Related Monthly Adjustment Amounts are added to Medicare premiums based on MAGI:

| MAGI (MFJ, 2026) | Monthly Part B surcharge | Monthly Part D surcharge | Annual Surcharge Per Person |
|------------------|--------------------------|--------------------------|------------------------------|
| ≤ $218,000 | $0 | $0 | $0 |
| $218,001–$274,000 | +$81.20 | +$14.50 | $1,148 |
| $274,001–$342,000 | +$203.70 | +$37.60 | $2,896 |
| $342,001–$410,000 | +$325.20 | +$60.60 | $4,630 |
| $410,001–$750,000 | +$406.90 | +$83.70 | $5,887 |
| > $750,000 | +$487.00 | +$91.00 | $6,936 |

For Married couples where both spouses are on Medicare, the surcharge applies *twice*. After one spouse passes, only one Medicare enrollee is counted. Thresholds scale by bracket inflation each year.

#### Step 7: State Tax

**California:** Progressive brackets from 1% to 13.3%. Social Security is *fully excluded* from California taxable income. Capital gains are taxed as ordinary income (no preferential rate).

**Montana:** Progressive brackets from 1% to 6.75%. Social Security is taxable at the same federal rate (up to 85%). Capital gains are taxed as ordinary income (no preferential rate).

**Other States:** A flat rate applied to ordinary income and capital gains.

#### Total Tax Summary

```
Total Tax = Federal Ordinary Tax
          + Federal LTCG Tax
          + NIIT
          + IRMAA Surcharges
          + State Tax
```

The effective tax rate shown in the charts is Total Tax / Gross Income.

---

### How Withdrawals Are Sequenced

Each retirement year, cash is assembled in this order:

**1. Mandatory and passive income (collected automatically):**
- RMDs from Traditional accounts (if age 73+)
- Social Security (if at or past SS start age) — inflated to nominal dollars with annual COLA
- Net rental income from Rental Property accounts
- Qualified dividends (taxed at LTCG rates)
- Ordinary dividends and interest (taxed as ordinary income)

**2. Roth Conversions (if enabled):**
- Calculated *before* discretionary withdrawals so they consume bracket space first
- Conversion taxes are added to the spending need for that year

**3. Tax-Free Capital Gains Harvesting:**
- If there's room left in the 0% capital gains bracket, the app sells and immediately repurchases assets in taxable accounts to step up the cost basis — locking in gains tax-free now and reducing future taxable gains
- This produces no cash; it's a pure tax optimization step

**4. Discretionary Withdrawals (to cover remaining spending need):**

*Tax-Efficient Strategy:*
1. Bank/Cash accounts (no tax, lowest return — use first)
2. Taxable Brokerage accounts (normal priority)
3. Traditional accounts up to the top of the 22% bracket
4. Roth accounts (tax-free)
5. Additional Traditional if still short
6. Taxable accounts marked "Last Resort"

*Roth Preservation Strategy:*
1. Bank/Cash accounts
2. Taxable Brokerage (normal priority)
3. All Traditional accounts
4. Roth accounts
5. Taxable "Last Resort"

**5. Fixed Net Mode (if spending_mode = "fixed"):**

When you've set a fixed after-tax spending target, the app uses binary search (50 iterations) to find the exact gross withdrawal that — after taxes — leaves you with exactly your target. This is more accurate than estimating taxes using last year's rate.

**Surplus handling:** If passive income exceeds the spending need (e.g., large RMDs in a low-spending year), the excess is reinvested into the taxable or bank account (it's already been taxed as ordinary income, so it goes in at full cost basis).

---

### How the Monte Carlo Simulation Works

The Monte Carlo engine (v2, recommended) runs N independent trials — each one is a complete simulation of your retirement from first year to last, with randomized annual returns.

#### Return Generation (v2 CMA Log-Normal Engine)

Each year, for each trial, the engine generates a correlated pair of equity and bond returns using the log-normal distribution:

```
equity_return = exp(μ_equity + σ_equity × z_equity) − 1
bond_return   = exp(μ_bond  + σ_bond  × z_bond)   − 1
```

where `z_equity` and `z_bond` are correlated standard normal draws, generated via Cholesky decomposition of the correlation matrix. This means equity and bond returns move somewhat together (positive correlation) rather than being completely independent.

The mean parameters (μ) are calibrated so that the portfolio's expected return matches your global Retirement Return Rate, using a 3-percentage-point equity risk premium spread between stocks and bonds.

**Why log-normal?** Real market returns can't go below −100%, but a normal distribution has no such floor. Log-normal returns are naturally bounded at −100% (you can't lose more than you invested) and correctly model the right-skewed nature of long-run equity returns.

**Stochastic inflation:** Inflation is also randomized each year, drawn from a normal distribution centered on your assumed inflation rate with a 1.5% standard deviation. Your spending target inflates by the *drawn* inflation each year, not a fixed rate.

#### Guyton-Klinger Guardrails (Optional)

Instead of spending a constant inflation-adjusted amount each year, you can adopt a rule that adjusts spending based on how the portfolio is performing:

- **Capital Preservation Rule:** If your current withdrawal rate is more than 120% of your initial rate (i.e., your portfolio shrank so much that you're now drawing down faster than planned), cut your spending by 10%
- **Prosperity Rule:** If your withdrawal rate falls below 80% of your initial rate (portfolio grew faster than expected), increase spending by 10%

This flexibility significantly improves success rates because you're not rigidly committed to a spending level when the market has been bad.

**Spending Floor:** You can optionally set a minimum discretionary spending level in today's dollars. Guardrail cuts will never push your spending below this floor — it is inflated forward with the drawn inflation each year, so it preserves its real purchasing power throughout the simulation. Healthcare costs and taxes are always paid in addition to the floor.

#### Interpreting Results

- **Success Rate:** Percentage of trials where the portfolio balance never reached $0 before life expectancy. Target: ≥90%.
- **10th Percentile at Life Expectancy:** The portfolio balance in the worst 10% of outcomes at your planned end-of-life age. If this is above $0, your plan survives even in quite bad markets.
- **Depletion Histogram:** When shown, it displays the distribution of *ages* at which failed trials ran out of money — useful for understanding when in retirement the risk is concentrated.

---

### How the Optimizer Works

The Optimizer is a random search over the space of possible retirement strategies.

#### What It Searches

For each of N trials (you set N, default 500), the optimizer randomly picks:

1. **Social Security start ages:** Both your age and your spouse's (if applicable) are varied independently across the valid range (62–70). Later claiming increases the monthly benefit but delays the income stream; the optimizer searches for the combination that maximizes your score.

2. **Withdrawal strategy:** Tax-Efficient or Roth Preservation

3. **Roth conversion:** Enabled or disabled. If enabled: randomly selects the bracket level (10%, 12%, 22%, or 24%), the conversion amount method (fill-to-bracket, fixed amount, IRMAA-safe, or ACA-safe), the start age, end age, source accounts, and destination Roth account.
   - **IRMAA-safe conversions:** When the conversion window overlaps Medicare ages (65+), the optimizer tries a mode that caps conversions just below the IRMAA Tier-0 income ceiling ($218,000 MFJ / $109,000 single), avoiding $1,148–$6,936/person/year in Medicare surcharges.
   - **ACA-safe conversions:** When retiring before 65, the optimizer tries a mode that caps conversions below the ACA 400%-FPL cliff (~$84,600 MFJ / $62,700 single), preserving marketplace premium subsidies until Medicare begins.

Each combination is evaluated by running the complete retirement simulation with those settings.

#### Score Function

Each strategy is scored:

```
Score = Lifetime After-Tax Spending
      − 0.30 × Lifetime Taxes Paid
      + Legacy Weight × Final Portfolio Value
      − Depletion Penalty (large penalty if portfolio hits $0)
```

The Legacy Weight (default 20%, your choice) controls the trade-off between maximizing your own spending versus leaving money to heirs. A higher legacy weight shifts the optimizer toward preserving portfolio balance at end of life.

The 0.30 × Lifetime Taxes term adds an additional penalty for high taxes beyond just the direct effect on spending — reflecting that high tax bills often signal suboptimal strategy even when spending targets are met.

#### Output

The optimizer reports:
- The *best-found* strategy, compared to your current baseline
- Lifetime improvements in after-tax spending, taxes paid, and final portfolio value
- The specific settings that produced the best result (which you can manually apply in the sidebar)
- A score distribution histogram — if the best-found score is dramatically higher than the median, there's genuine upside to be captured; if scores are tightly clustered, your current strategy is already near-optimal

**Important limitation:** The optimizer evaluates each strategy using the deterministic projection (not Monte Carlo). A strategy that scores highly on expected value might have different risk characteristics. After applying the optimizer's recommendation, run the Monte Carlo tab to verify the success rate remains acceptable.

---

*This guide reflects the app as of June 2026. Tax brackets and Medicare thresholds are for 2026 and are scaled forward in the simulation by the Tax Bracket Inflation Rate.*
