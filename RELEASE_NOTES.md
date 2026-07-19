# Release Notes — v2.0.0 (July 18, 2026)

This is a **major release**. The unifying theme is *comparing strategies honestly*:
every engine now values your portfolio net of the taxes you'll owe on it, the
optimizer reasons about tax arbitrage and robustness instead of a single lucky
return path, and two long-standing "free lunch" gaps (the ACA subsidy cliff and
Social Security claiming age) are now priced correctly.

## Highlights

### Tax-adjusted portfolio valuation
Pre-tax balances (Traditional 401k/IRA) are now discounted for the income tax
you'll eventually pay on them, everywhere a portfolio value is shown — the
deterministic Retirement tab, both Monte Carlo engines, the Optimizer, and the
summary metrics. A $1M Roth and a $1M Traditional account are no longer treated
as equal, so legacy figures and strategy comparisons are apples-to-apples.

### ACA premium subsidy is now a real cost (opt-in)
If you buy pre-65 marketplace coverage, you can now check **Model ACA premium
subsidy** under Healthcare. The app treats your pre-Medicare healthcare input as
the full unsubsidized premium and subtracts each year's Premium Tax Credit,
which shrinks as your income rises and vanishes above the 400%-FPL cliff
(~$84,600 MFJ / $62,700 single in 2026). Previously, blowing past that cliff cost
nothing in the model even though it costs thousands in reality — now the
fixed-net solver and both optimizers feel it. New per-year subsidy/cliff columns
and a lifetime-subsidy total accompany the change.

### Social Security is actuarially re-priced by the optimizer
When the optimizer moves your claiming age (62–70), it now rescales the benefit
by the correct early-claim reduction (down to ~70% at 62) or delayed-retirement
credit (up to ~124% at 70, relative to Full Retirement Age 67). Before, every
claiming age paid the same dollar benefit, which made claiming early look free
and biased recommendations. Your entered benefit at your entered age is left
untouched — only the optimizer's *what-if* ages are re-priced.

### A smarter, steadier Roth-conversion optimizer
- **Robust mode** scores each conversion candidate across a band of Roth-return
  assumptions and blends mean with worst-case (λ slider), so the recommendation
  no longer flips when you nudge the return rate by a fraction of a point.
- **Tax-smoothing objective** (opt-in) decides the conversion amount on tax-rate
  grounds only — Kitces' marginal-rate equivalency — and reports how much of a
  "great conversion" is genuine tax arbitrage versus an asset-location return bet.
- **Suggested fill-to-rate curve** sweeps the bracket ceiling and scores each on
  the full after-tax simulation, flagging all-or-nothing corner solutions.

### Other additions
- **Montana** long-term capital gains taxed at the preferential HB337 (2026)
  rates (3.0% / 4.1%) instead of as ordinary income.
- **Separate healthcare inflation rate** — grow healthcare costs faster than
  general CPI if you want (preserved through Monte Carlo variation).
- **First-year market-crash stress test** — a deterministic −20% equity shock in
  the first retirement year to probe sequence-of-returns risk.

## Fixes
- **`bracket_ceiling_for_rate`** returned 0 for any marginal rate outside
  10/12/22/24%, so a "fill to the 32%/35% bracket" conversion filled only to the
  standard deduction and converted almost nothing — corrupting the suggested
  fill-to-rate curve. It now reads the authoritative bracket table.
- 401(k) contribution-limit handling and mega-backdoor-Roth validation.
- Already-retired Monte Carlo horizon alignment.
- SWR tax treatment aligned between the deterministic and Monte Carlo engines.
- Scenario name preserved when adding/removing accounts.

## Under the hood
- Monte Carlo now runs the *exact same plan* as the Retirement tab and Optimizer
  (strategy parity) — it only randomizes the market/inflation paths.
- A pre-retirement cash-reserve optimizer lever was trialed and **reverted**
  before release because it conjured cash with no offsetting sale or capital-
  gains tax; a regression test now guards against it.
- An experimental MC-aware receding-horizon optimizer (`optimizer_v3`) is built
  and tested but **not yet wired into the UI**.
- 400 tests passing; ruff clean.

## Upgrading
No data migration is required — existing saved scenarios load unchanged. The two
new opt-in toggles (ACA subsidy, separate healthcare inflation) default to off,
so behavior is unchanged until you enable them.

## Known limitations
See [CONSIDERATIONS.md](CONSIDERATIONS.md) for the full living list. Notable
items unchanged in this release: no long-term-care/catastrophic healthcare
modeling, no QCDs/QLACs, no depreciation recapture on rental sales, single
blended cost basis (no lot-level tracking), and survivor transitions only model
the older partner dying first.
