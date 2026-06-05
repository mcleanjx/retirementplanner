# Open Considerations

Living document. Update when decisions are made or new questions arise.

---

## Open Questions
*Unresolved — should inform next iterations*

**CAPE adjustment removed (v1.1)** — Shiller earnings-yield model was implemented but disabled and held a hardcoded CAPE of 39.6 that would silently go stale. Removed rather than ship misleading dead code. To re-add properly: expose a "Current CAPE" user input in the UI, wire it to `_equity_bond_means()` output with linear reversion over 10 years, and add a note that the user is responsible for keeping it current.

**Spousal Roth conversion bracket coordination** — Per-account ownership flags exist but conversion headroom (`withdrawals.py:425`) applies a single MFJ bracket ceiling without distinguishing whose account is being converted. Could cause bracket collision in edge cases where both spouses convert in the same year.

**Optimizer v2 IRMAA/ACA headroom display uses profile-default SS ages** — The reported IRMAA and ACA headroom shown in the Recommended Strategy Settings table is estimated once using the profile's current SS start ages, not the optimized trial's SS start ages. The optimization itself is correct (headroom is recomputed per trial during the search); only the displayed figure is approximate. Fix: pass the best trial's `ss_start` into `_irmaa_headroom` / `_aca_headroom` before calling `describe_strategy_v2`.

---

## Active Tradeoffs
*Conscious choices — revisit if scope or user base changes*

**Normal (v1) vs. log-normal (v2) Monte Carlo** — Both engines now run the *same* full plan per trial (they delegate to `simulate_retirement`); they differ only in the return distribution: v1 draws normal, independent-per-account returns with deterministic inflation, while v2 draws log-normal, correlated equity/bond returns with stochastic inflation. v2 is more realistic (bounded left tail, correlated factors, fatter tails) and is the default for serious planning; v1 is the simpler, more optimistic "Standard" comparison. Both incur per-trial tax/strategy cost (fixed-net mode is ~5× SWR mode due to the per-year binary search).

**Fixed-net binary search vs. SWR** — Fixed-net mode converges to $1 precision via 50-iteration binary search but is computationally expensive. SWR is faster but doesn't account for actual tax-bracket interactions. For optimizer runs (500 trials × N years), this matters.

**Annual simulation granularity** — Year-by-year simulation means no intra-year rebalancing, sequence-of-returns within a year, or monthly budget tracking. Acceptable for long-horizon planning; would mislead if used for near-term cash flow.

**Survivor spending reduction hardcoded at 25%** — Default is configurable per profile but there's no guidance to users. Health & Retirement Study data suggests the right number varies widely by income level and housing situation.

---

## Known Limitations
*Intentional simplifications — document so they aren't treated as features*

**No depreciation recapture on rental property** — Rental sales modeled as simple capital gains. Depreciation recapture (taxed at 25%) is ignored. Material if user has held rental property for many years.

**Healthcare inflation equals general inflation** — Medical cost inflation has historically run 1–2% above CPI. Using the same inflation rate understates retiree healthcare burden, especially in high-longevity scenarios.

**No lot-level basis tracking** — Taxable accounts use a single blended cost basis (pro-rata). Tax-loss harvesting, specific lot identification, and wash-sale rules are not modeled.

**Roth 5-year rule not enforced** — Conversion vintage tracking exists (`withdrawals.py:301`) but non-qualified withdrawal ordering is never checked. Low impact for typical retirees; material for FIRE scenarios with early conversions.

**No long-term care / catastrophic healthcare** — Healthcare costs are a fixed annual amount per person (pre/post-Medicare switch at 65). Nursing home costs ($5–15k/month), LTC insurance, or Medicaid asset limits are not modeled.

**Pro-rata rule not modeled for Roth conversions** — Conversions assume 100% of the converted amount is ordinary income. If the IRA contains after-tax basis, the actual taxable portion is lower. Users with nondeductible IRA contributions will see overstated conversion tax costs.

**State tax: CA, MT, or flat-rate only** — No multi-state scenarios, no relocation modeling, no state-specific treatment of RMDs. Some states exempt SS or pension income; only CA's SS exclusion is currently modeled. MT taxes SS at the federal rate.

**No one-time income events** — There is no way to model a discrete future event (business sale, inheritance, lawsuit settlement, property sale) as a taxed income event in a specific year. Workaround: estimate after-tax proceeds externally and add them as a Taxable Brokerage account balance. To implement properly: a one-time event would need a trigger year/age, gross amount, tax treatment (LTCG, ordinary income, or user-specified after-tax), and a destination account; the amount would flow into `simulate_retirement` as extra income in the matching year and be passed through `calculate_year_taxes`.

**Survivor transition only models the spouse dying, and only when the spouse is older** — The retirement loop runs on the primary person's age and triggers the survivor transition only when `spouse_age >= life_expectancy` (`withdrawals.py` Step 0). There is a single shared `life_expectancy` (no separate spouse life-expectancy input), so: (a) when the spouse is *younger* than the primary, the loop ends before `spouse_age` reaches `life_expectancy`, so no survivor period is ever modeled (no 25% spending reduction, no switch to single-filer brackets — which *understates* late-life taxes); (b) the primary dying first while the spouse survives is never modeled. The model effectively assumes the older partner dies first at the shared life expectancy. To implement properly: add a `spouse_life_expectancy` input and trigger survivor status on the first death, switching the survivor's filing status, SS (larger benefit continues), and spending.

---

## Resolved
*Decisions made / bugs fixed — kept for institutional memory*

**Accumulation now honors `use_global_return_rate`** — Previously the accumulation phase always grew each account at its own `return_rate` (default 7%), ignoring the per-account "use global rate" flag and the global Retirement Return Rate, while the retirement phase honored both. `projections.py` now uses the global rate during accumulation when the flag is set (bank/rental always use their own rate), matching `withdrawals.py`.

**Already-retired Monte Carlo horizon** — `simulate_retirement` was fixed in v1.4 to start at `max(retirement_age, current_age)`, but the MC engines still looped from `retirement_age`, re-simulating already-elapsed years and misaligning the age axis (which silently dropped the deterministic baseline from the fan chart). Both `montecarlo.py` and `montecarlo_v2.py` (and their callers' `ages`/`n_years`) now start at `max(retirement_age, current_age)`; the fixed-net spending target is also guarded against a negative accumulation gap.

**SWR tax treatment aligned between deterministic and Monte Carlo** — In SWR mode the withdrawal rate is gross of tax (the classic 4%-rule convention) in `simulate_retirement`, but `montecarlo_v2` was withdrawing the spending amount *and* the tax bill separately, over-draining the portfolio and biasing the success rate below the deterministic baseline. (Subsumed by the parity rewrite below, which makes simulate_retirement the single source of truth for withdrawal/tax behavior.)

**Monte Carlo now runs the full deterministic plan (strategy parity)** — Both MC engines previously re-implemented a simplified, tax-light withdrawal loop that ignored Roth conversions, 0%-bracket gain harvesting, planned rebalancing, and the tax-efficient fill-to-bracket withdrawal order — so MC stress-tested a *different* plan than the Retirement tab and Optimizer. They now generate only the stochastic per-year, per-account returns (and, for v2, the inflation path) and delegate the entire plan to `simulate_retirement` via its `market_returns` / `inflation_sequence` hooks. Guyton-Klinger guardrails and the spending floor were ported into `simulate_retirement` (gated behind `withdrawal_mode`). A regression suite (`TestMonteCarloStrategyParity`) verifies the injection reproduces the deterministic run exactly and that conversions flow through MC. To keep the per-year binary search affordable at MC scale, the fixed-net dry-run now uses a shallow per-account copy instead of `deepcopy` (~2× faster, also speeds up the optimizer). `run_monte_carlo`/`run_monte_carlo_v2` gained `roth_conversion` and `spending_overrides` parameters, now passed through from the app.
