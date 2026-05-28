# Retirement Planner

A personal retirement planning app built with Python and Streamlit. Model your retirement projections, run Monte Carlo simulations, compare withdrawal strategies, and track your progress over time.

> **Warning:** This app is a work in progress and may contain errors. Use results for informational purposes only and verify any financial figures independently.

---

## Features

- **Retirement Projections** — Year-by-year accumulation and drawdown modeling across multiple account types (401k, Roth IRA, taxable brokerage, real estate, etc.)
- **Tax Calculations** — Federal and California state tax, RMDs, Social Security taxability, IRMAA, LTCG, and NIIT
- **Withdrawal Strategies** — Tax-efficient, Roth-preservation, and traditional-first strategies with binary search solver for net-spending accuracy
- **Monte Carlo Simulation** — Probability of success across up to 10,000 simulated market scenarios; CMA Log-Normal (v2) and standard normal (v1) engines
- **Strategy Optimizer** — Random-search optimizer over withdrawal strategies and Roth conversion parameters to maximize after-tax lifetime wealth
- **Scenario Management** — Save, load, and compare multiple planning scenarios with name validation
- **Account Management** — Track balances, contributions, employer match, and per-account return rates
- **Progress Tracking** — Check-in system to compare actual vs. projected balances over time

---

## Getting Started

**Quick start:**
```
git clone https://github.com/mcleanjx/retirementplanner.git
cd retirementplanner
pip install -r requirements.txt
streamlit run app.py
```

---

## Requirements

| Package | Version |
| ------- | ------- |
| Python | >= 3.10 |
| streamlit | >= 1.45.0 |
| plotly | >= 5.22.0 |
| pandas | >= 2.2.0 |
| numpy | >= 1.26.0 |

---

## Project Structure

| File | Purpose |
| ---- | ------- |
| `app.py` | Main Streamlit UI |
| `projections.py` | Accumulation phase calculations |
| `withdrawals.py` | Retirement drawdown simulation |
| `taxes.py` | Federal and state tax engine |
| `montecarlo.py` / `montecarlo_v2.py` | Monte Carlo simulation (v1 normal, v2 log-normal) |
| `optimizer.py` | Withdrawal strategy optimizer |
| `scenarios.py` | Scenario save/load/delete |
| `charts.py` | Plotly chart helpers |
| `constants.py` | Tax brackets, RMD tables, and other constants |

Scenario data is stored in `scenarios/` and tracking data in `scenarios/tracking/`. Both folders are created automatically on first run.

---

## Releases

### v1.3 — May 2026
- Added comprehensive user guide covering all features, data inputs, and model assumptions
- Fixed Streamlit session-state conflict on scenario name widget
- Corrected stale test expectation (invalid scenario names are rejected, not silently sanitized)
- README and documentation cleanup

### v1.2 — May 2026
- Removed stale CAPE adjustment infrastructure from Monte Carlo v2 (hardcoded value would have silently gone stale)
- Removed simplified wizard mode (`simplified.py`) — superseded by the full UI
- Added `CLAUDE.md` and `CONSIDERATIONS.md` to document open questions and design tradeoffs

### v1.1 — May 2026
- Binary search solver for fixed-net spending accuracy (replaces effective-rate gross-up)
- Per-account return rate override (`use_global_return_rate` flag)
- LTCG harvesting in retirement simulation
- Scenario name validation with clear error messaging
- Comprehensive test suite (300+ tests across all modules)

### v1.0 — Initial release
- Full retirement accumulation and drawdown simulation
- Federal + California state tax engine (RMDs, SS taxability, IRMAA, LTCG, NIIT)
- Monte Carlo v1 (normal returns) and v2 (log-normal, correlated equity/bond, stochastic inflation)
- Strategy optimizer
- Scenario save/load/compare
- Progress tracking with check-in system

---

## License

Personal use only.
