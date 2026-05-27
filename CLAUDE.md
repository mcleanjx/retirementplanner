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
- `optimizer.py` — Random-search strategy optimizer
- `projections.py` — Accumulation phase
- `taxes.py` — Federal/state tax calculations
- `constants.py` — 2026 tax brackets, RMD tables, IRMAA tiers

## Open considerations
@CONSIDERATIONS.md
