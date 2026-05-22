# Simplified Mode Spec

## Overview

The retirement planner is powerful but complex — it requires users to understand concepts like effective tax rates, withdrawal sequencing, Roth conversion strategy, and IRMAA thresholds. The simplified mode targets someone who has never used a retirement calculator before, or who just wants a quick "am I on track?" answer without becoming a tax expert.

**Design principle:** The simplified mode is a *complete, trustworthy experience* — not a watered-down teaser. It uses expert defaults to fill in everything the user doesn't need to know, and produces a real answer in under 5 minutes. Power mode remains the full tool for users who want control.

---

## Goals

1. A first-time user can get a meaningful result in under 5 minutes
2. No financial jargon — every input should be answerable by someone who has never opened a brokerage statement
3. A single headline metric (the "score") the user can remember and share
4. Immediately actionable: after the score, show the 2–3 specific changes that would move the needle most
5. Data is never lost when toggling between modes — simplified inputs map cleanly to power-mode fields

---

## Entry Point / Mode Toggle

- A **"Simple / Advanced" toggle** appears in the top-right of the app header (or top of the sidebar)
- Default for new users: **Simple mode**
- Default for existing users with saved data: **Advanced mode** (they've already invested in the full setup)
- Toggling is instant; data is preserved in both directions
- When switching from Simple → Advanced for the first time, show a brief "Here's what we filled in for you" summary so the user understands what to refine

---

## Wizard: Input Steps

The wizard replaces the sidebar entirely. It's a linear, step-by-step flow with a progress bar. Users can go back to any step.

### Step 1 — About You

| Field | Input type | Notes |
|---|---|---|
| Your current age | Number (slider 25–75) | |
| Your target retirement age | Number (slider, min = current age + 1) | Label: "When do you want to stop working?" |
| Are you married or in a partnership? | Yes / No toggle | If yes, show spouse fields |
| Spouse's current age | Number (slider) | Only if married |
| How long do you expect to live? | Slider (75–100, default 90) | Label: "This is just a planning number — better to plan long than run short" |

**What's hidden:** Filing status (auto-set from married/single), state tax (defaulted to national average ~4.5%, adjustable in Advanced), healthcare (age-based defaults applied silently).

---

### Step 2 — Your Savings

| Field | Input type | Notes |
|---|---|---|
| Total retirement savings today | Dollar input | Label: "Add up all your 401k, IRA, and investment accounts" |
| Split into account types? | Optional expandable | "Optional: helps us be more accurate" — see below |
| How much are you saving per year? | Dollar input | Label: "Total amount going into retirement accounts annually, including employer match" |

**Optional split (collapsed by default):**
If the user expands, they can split total savings into:
- Tax-deferred (Traditional 401k / IRA)
- Roth (Roth 401k / Roth IRA)
- Taxable brokerage / other investments

This maps to separate accounts in power mode. Most users won't expand this.

**What's hidden:** Return rate (set by Step 4 investment style selection), contribution growth (defaulted to 0% real / matches inflation), employer match details, cost basis, dividend yields.

---

### Step 3 — Retirement Income

| Field | Input type | Notes |
|---|---|---|
| Will you receive Social Security? | Yes / No | Default: Yes |
| Estimated SS benefit | Dollar input (annual) | Label: "Find this at ssa.gov/myaccount — enter in today's dollars"; help link to SSA |
| When will you claim SS? | Slider (62–70, default 67) | Shows approximate adjustment vs. full retirement age |
| Spouse SS benefit | Dollar input | If married |
| Spouse SS start age | Slider (62–70) | If married |
| Any other income in retirement? | Optional expandable | Pension (annual $), rental income (annual $) |

**What's hidden:** SS COLA (applied at 2.5% inflation silently), spousal benefit calculations, IRMAA surcharges, taxation of SS benefits (handled by the engine behind the scenes).

---

### Step 4 — Your Goal

| Field | Input type | Notes |
|---|---|---|
| How much do you want to spend per year in retirement? | Dollar input OR % slider | Default option: "% of current income" slider (default 80%); can switch to "dollar amount" |
| What's your annual income today? | Dollar input | Only shown if using % mode; used to compute the spending target |
| How would you describe your investment style? | 3-option radio | Conservative (bonds-heavy, ~5% return) / Moderate (balanced, ~7%) / Aggressive (stocks-heavy, ~9%) |

**What's hidden:** The actual return rate (derived from style), inflation rate (2.5%), spending mode (auto-set to fixed-dollar), withdrawal sequencing, Roth conversion (off by default in simplified mode).

---

### Step 5 — Review & Results (auto-advance after Step 4)

No inputs — just a confirmation of key numbers before showing results:

> "Based on what you told us:
> - You'll retire at **65** and need savings to last **25 years**
> - You're currently saving **$18,000/year** toward a **$750,000** portfolio
> - You want **$70,000/year** in retirement; Social Security covers **$28,000** of that
> - We've used a **moderate** investment return assumption"

A single **"See My Results"** button advances to the output view.

---

## Expert Defaults (Hidden from User)

These values are set silently. They're disclosed in a collapsible "What assumptions did we use?" section on the results page.

| Parameter | Simplified default | Power-mode equivalent |
|---|---|---|
| Inflation rate | 2.5% | `inflation_rate` |
| Tax bracket inflation | 2.5% | `bracket_inflation_rate` |
| Return rate (Conservative) | 5.0% nominal | `retirement_return_rate` |
| Return rate (Moderate) | 7.0% nominal | `retirement_return_rate` |
| Return rate (Aggressive) | 9.0% nominal | `retirement_return_rate` |
| Pre-Medicare healthcare | $15,000/yr | `pre_medicare_healthcare` |
| Post-Medicare healthcare | $12,000/yr | `post_medicare_healthcare` |
| Withdrawal strategy | Tax-efficient | `withdrawal_strategy` |
| Roth conversion | Off | `roth_conversion.enabled = False` |
| State tax | 4.5% (national avg) | `state_tax_rate` |
| Spending mode | Fixed dollar | `spending_mode = "fixed"` |
| Life expectancy (if not entered) | 90 | `life_expectancy` |

---

## Simplified Output View

Replace the 9-tab layout with a single scrolling page containing four panels.

---

### Panel 1 — Your Retirement Score (Headline)

A large, color-coded score card:

```
┌────────────────────────────────────┐
│  YOUR RETIREMENT SCORE             │
│                                    │
│         ●  82%                     │
│                                    │
│   ON TRACK                         │
│   Your plan covers 82% of your     │
│   retirement income goal.          │
│                                    │
│   You have a projected surplus of  │
│   $340,000 by age 90.              │
└────────────────────────────────────┘
```

Score bands:
- **95%+** → "You're in great shape" (dark green)
- **80–94%** → "On track" (green)
- **65–79%** → "Close, but some adjustments needed" (yellow)
- **50–64%** → "Needs attention" (orange)
- **<50%** → "At risk — significant changes needed" (red)

The score is: `min(projected_lifetime_spending / target_lifetime_spending, 1.0) * 100`

---

### Panel 2 — Will My Money Last?

A single clean chart:
- X-axis: age (current → life expectancy)
- Y-axis: portfolio value
- Line: projected portfolio balance (current engine output)
- Shaded band: "safe zone" (balance > 0)
- Annotation: age at which portfolio depletes (if it does), or "Surplus at 90: $340k"
- A dashed "target" line at $0 (you want to stay above it)

No tabs, no scenario comparison, no Monte Carlo distribution — just the median projection.

---

### Panel 3 — Where Will My Income Come From?

A stacked bar chart by decade (60s, 70s, 80s):
- Portfolio withdrawals
- Social Security
- Other income (pension, rental)

Labels in plain English: "In your 70s, Social Security covers about 40% of your spending."

---

### Panel 4 — Move the Needle

Three interactive "what if" sliders, each showing how the score changes in real time:

1. **Save more** — "What if I saved $X more per year?" (slider: +$0 to +$10,000/yr)
2. **Retire later** — "What if I retired at age X?" (slider: current retirement age ± 5 years)
3. **Spend less** — "What if I spent $X less per year in retirement?" (slider: 0 to −$20,000)

Each slider instantly re-runs the projection and updates the score in Panel 1. No page reload — these drive the same engine synchronously.

Below the sliders: a short plain-English summary of the most impactful lever:

> "Saving an extra $300/month would move your score from 82% to 95% — putting you firmly on track."

---

### Panel 5 — Want More Detail?

A callout at the bottom:

> **"You've covered the basics. Want to go deeper?"**
>
> The Advanced mode lets you model taxes, Roth conversions, state taxes, different account types, and Monte Carlo scenarios. All your data carries over automatically.
>
> [Switch to Advanced Mode →]

Also: a collapsible **"What assumptions did we use?"** section disclosing all expert defaults.

---

## Data Mapping: Simple → Power Mode

When a user builds a simplified plan and then switches to Advanced, their inputs map as follows:

| Simplified input | Power mode mapping |
|---|---|
| Total savings (undivided) | Single "Traditional 401k" account |
| Savings split (3 buckets) | Three accounts: Traditional 401k, Roth IRA, Taxable |
| Annual savings | `annual_contribution` on the main account |
| SS benefit + age | `profile.social_security_benefit`, `profile.social_security_start_age` |
| Spouse SS | `profile.spouse_ss_benefit`, `profile.spouse_ss_start_age` |
| Pension | Additional income event (one-time income stream) |
| Rental income | Rental property account with `net_annual_rental_income` |
| Investment style | Sets `retirement_return_rate` |
| Married | `filing_status = "married_filing_jointly"` |
| Life expectancy | `profile.life_expectancy` |
| Retirement age | `profile.retirement_age` |
| Spending goal | `annual_spending_target` |

When switching Advanced → Simple, only the fields with simplified equivalents are surfaced; the rest are preserved in the background.

---

## Mode Persistence & Data Integrity

- Mode toggle is stored in `st.session_state.ui_mode` (`"simple"` or `"advanced"`)
- All power-mode fields are always saved, even when the user is in simple mode — switching is non-destructive
- Wizard state is stored in `st.session_state.wizard_step` (1–5)
- If a user has already completed the wizard, going back to simple mode shows their completed answers (not the blank wizard)
- If power-mode data exists for a field that simplified mode would overwrite (e.g., multiple accounts → single balance), simplified mode reads the aggregate and writes back the aggregate — it does not silently overwrite the individual account breakdown unless the user explicitly edits the balance field

---

## Edge Cases

| Scenario | Handling |
|---|---|
| User is already retired | Step 1 detects retirement age ≤ current age; wizard skips Step 2 (no accumulation) and goes straight to "How long does your portfolio need to last?" |
| User has no Social Security | SS section in Step 3 is skipped when user answers No; SS = $0 in the engine |
| Married, spouse already retired | Spouse retirement age field clamped to current spouse age or higher |
| Score > 100% | Show "You have a significant surplus — your plan is very comfortable" with the actual surplus dollar amount |
| Simplified result very different from Advanced result | If the user has Advanced data, show a soft warning: "Your advanced settings may change this estimate. Switch to Advanced mode for your most accurate projection." |
| No data entered | Wizard blocks "See My Results" until Steps 1–4 are complete; partial completion shows a progress bar |

---

## Implementation Notes

### Toggle placement
Top of sidebar with a segmented control (`st.radio` styled as a toggle, or a custom button pair). Keep it visible at all times so the user always knows they can switch.

### Wizard layout
Use `st.progress()` for the step bar. Each step is a single `st.container()` with a Next/Back button. Store answers in `st.session_state.wizard`.

### Engine reuse
The simplified mode uses the **same projection engine** as power mode — no separate calculation logic. It just calls `run_projection(profile, accounts, assumptions)` with the mapped inputs and expert defaults. This keeps the two modes in sync automatically.

### Performance
The "Move the Needle" sliders in Panel 4 must update the score in real time. Use `st.session_state` caching keyed on the three slider values; only re-run the engine when a slider changes. The engine should run in well under 1 second for a single-path projection.

### Progressive enhancement path
After shipping the basic simplified mode, consider adding:
- **Completion percentage** ("Your plan is 60% complete — adding your Social Security estimate would significantly improve accuracy")
- **Coach suggestions** ranked by impact ("The #1 thing that would improve your score is...")
- **One-time event support** in the wizard ("Are there any big expenses coming up? Home purchase, college tuition, etc.")
