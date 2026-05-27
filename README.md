# Retirement Planner

A personal retirement planning app built with Python and Streamlit. Model your retirement projections, run Monte Carlo simulations, compare withdrawal strategies, and track your progress over time.

> **Warning:** This app is a work in progress and may contain errors. Use results for informational purposes only and verify any financial figures independently.

---

## Features

- **Retirement Projections** — Year-by-year accumulation and drawdown modeling across multiple account types (401k, Roth IRA, taxable brokerage, real estate, etc.)
- **Tax Calculations** — Federal and California state tax, RMDs, Social Security taxability, IRMAA, LTCG, and NIIT
- **Withdrawal Strategies** — Tax-efficient, Roth-first, traditional-first, and pro-rata strategies with binary search solver for accuracy
- **Monte Carlo Simulation** — Probability of success across up to 10,000 simulated market scenarios; supports CMA Log-Normal and CAPE-adjusted return models
- **Scenario Management** — Save, load, and compare multiple planning scenarios with name validation
- **Account Management** — Track balances, contributions, employer match, and return rates per account
- **Progress Tracking** — Check-in system to compare actual vs. projected balances over time
- **Simplified Mode** — Guided step-by-step wizard for quick planning without advanced configuration

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
| `app.py` | Main Streamlit UI (advanced mode) |
| `simplified.py` | Guided wizard UI (simplified mode) |
| `projections.py` | Accumulation phase calculations |
| `withdrawals.py` | Retirement drawdown simulation |
| `taxes.py` | Federal and state tax engine |
| `montecarlo.py` / `montecarlo_v2.py` | Monte Carlo simulation |
| `optimizer.py` | Withdrawal strategy optimizer |
| `scenarios.py` | Scenario save/load/delete |
| `charts.py` | Plotly chart helpers |
| `constants.py` | Tax brackets, RMD tables, and other constants |

Scenario data is stored in `scenarios/` and tracking data in `scenarios/tracking/`. Both folders are created automatically on first run.

---

## Releases

| Release | Status |
| ------- | ------ |
| v1.0 | Latest stable |
| v0.1 | Stable |

---

## License

Personal use only.
