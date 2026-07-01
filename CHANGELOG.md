# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/), and this project uses semantic
versioning.

## [2.0.0] — 2026-06-30

Major release. The headline change is **tax-adjusted portfolio valuation**
threaded through every engine, plus a substantially smarter Roth-conversion
optimizer that reasons about tax arbitrage and robustness rather than a single
mean-return path.

### Added
- **Tax-adjusted portfolio valuation** across the deterministic simulation,
  both Monte Carlo engines, the optimizer, and the UI — pre-tax balances are
  discounted for embedded tax liability so legacy/comparison figures are
  apples-to-apples.
- **Robust optimizer mode** — scores each Roth-conversion candidate across a
  band of Roth-return assumptions and ranks on a blend of mean and worst-case
  (λ slider), so the recommendation no longer flips on a 0.1pp return nudge.
  Surfaced with a "Robustness to the Return Guess" table.
- **Tax-smoothing conversion objective** — an opt-in alternative to the
  wealth-maximizing objective that decides the conversion amount on tax-rate
  grounds only (Kitces marginal-rate equivalency), reporting a decomposition of
  genuine tax arbitrage vs. asset-location return premium.
- **Suggested conversion fill-to-rate curve** — sweeps the fill-to marginal-rate
  ceiling and scores each on the full after-tax simulation, flagging all-or-
  nothing corners.
- **Pre-retirement cash-reserve dimension** — the optimizer can trial holding
  extra cash at retirement to fund conversion taxes instead of realizing
  appreciated taxable lots.
- **Separate healthcare inflation rate** — optional override decoupling
  healthcare cost growth from general CPI (preserved through MC variation).
- **First-year market-crash stress test** — a deterministic −20% equity shock in
  the first retirement year, targeting sequence-of-returns risk.
- Version marker surfaced in the page title and sidebar.

### Changed
- Optimizer converts earlier and drains pre-tax accounts more reliably.
- Montana capital gains now taxed at preferential HB337 (2026) LTCG rates rather
  than lumped into ordinary income.
- Accumulation phase now honors the per-account `use_global_return_rate` flag.
- Research/scratch documentation moved under `docs/research/`.

### Fixed
- 401(k) contribution-limit handling and mega-backdoor-Roth validation.
- Already-retired Monte Carlo horizon alignment.
- SWR tax treatment aligned between the deterministic and Monte Carlo engines.
- Scenario name preserved when adding/removing accounts.

### Internal
- Monte Carlo engines now delegate the full plan to `simulate_retirement`
  (strategy parity between the Retirement tab, Optimizer, and MC).
- New MC-aware receding-horizon optimizer (`optimizer_v3`) — engine and tests
  complete; **not yet wired into the app UI** (experimental).
- Full lint pass (ruff clean); test suite at 387 passing.

## [1.4.0]
- Optimizer v2 (SS timing, IRMAA/ACA-aware conversions), Guyton-Klinger spending
  floor, Montana state tax, optimizer rebalancing, already-retired simulation
  fix, five committed test scenarios, MC research notes and CMA presets.

## [1.3.0]
- Release-notes and README refresh.

## [1.1.0]
- Removed stale CAPE adjustment infrastructure; removed unused wizard module.
