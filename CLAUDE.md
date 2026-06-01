# Retirement Planning — Project Guide

Python/Streamlit app that models retirement accumulation, drawdown, taxes, and Monte Carlo simulations across multiple account types.

## Running the app
```
streamlit run app.py
```

## Key files
- `app.py` — Advanced UI (2,350 lines); main entry point
- `withdrawals.py` — 7-step annual retirement simulation
- `montecarlo.py` / `montecarlo_v2.py` — v1 (normal returns) and v2 (log-normal, stochastic inflation)
- `optimizer.py` — Strategy optimizer v1 (withdrawal order + Roth conversions)
- `optimizer_v2.py` — Strategy optimizer v2 (+ SS timing, IRMAA/ACA cliff-aware conversions)
- `projections.py` — Accumulation phase
- `taxes.py` — Federal/state tax calculations
- `constants.py` — 2026 tax brackets, RMD tables, IRMAA tiers

## Open considerations
@CONSIDERATIONS.md
