# Open Considerations

Living document. Update when decisions are made or new questions arise.

---

## Open Questions
*Unresolved — should inform next iterations*

**CAPE adjustment removed (v1.1)** — Shiller earnings-yield model was implemented but disabled and held a hardcoded CAPE of 39.6 that would silently go stale. Removed rather than ship misleading dead code. To re-add properly: expose a "Current CAPE" user input in the UI, wire it to `_equity_bond_means()` output with linear reversion over 10 years, and add a note that the user is responsible for keeping it current.

**Guyton-Klinger guardrails not exposed in UI** — Implemented in `montecarlo_v2.py` lines 214–230 but `simplified.py` hardcodes `withdrawal_mode="constant_real"`. Worth surfacing as a toggle — it meaningfully extends portfolio survival in bad sequences.

**Accumulation vs. retirement return rate inconsistency** — Accumulation phase (`projections.py:98`) defaults to 7% regardless of the user's global setting; retirement phase uses user-set rate (default 6.5%). Subtle but could mislead users who tune the retirement rate thinking it applies everywhere.

**Spousal Roth conversion bracket coordination** — Per-account ownership flags exist but conversion headroom (`withdrawals.py:425`) applies a single MFJ bracket ceiling without distinguishing whose account is being converted. Could cause bracket collision in edge cases where both spouses convert in the same year.

---

## Active Tradeoffs
*Conscious choices — revisit if scope or user base changes*

**Normal (v1) vs. log-normal (v2) Monte Carlo** — v2 is more realistic (bounded left tail, correlated equity/bond, stochastic inflation) but slower due to per-trial tax calculations. Both engines coexist. v2 should be the default for any serious planning; v1 retained for speed comparison.

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

**State tax: CA or flat-rate only** — No multi-state scenarios, no relocation modeling, no state-specific treatment of RMDs or Social Security (some states exempt SS; some exempt pension income entirely).
