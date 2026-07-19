# Retirement Planning — Project Guide

Python/Streamlit app that models retirement accumulation, drawdown, taxes, and Monte Carlo simulations across multiple account types.

## Running the app
```
streamlit run app.py
```

## Key files
- `app.py` — Advanced UI; main entry point
- `withdrawals.py` — 7-step annual retirement simulation
- `montecarlo.py` / `montecarlo_v2.py` — v1 (normal returns) and v2 (log-normal, stochastic inflation)
- `optimizer.py` — Strategy optimizer v1 (withdrawal order + Roth conversions)
- `optimizer_v2.py` — Strategy optimizer v2 (+ SS timing, IRMAA/ACA cliff-aware conversions)
- `optimizer_v3.py` — MC-aware receding-horizon optimizer (experimental; **not wired into the app UI**)
- `projections.py` — Accumulation phase
- `taxes.py` — Federal/state tax calculations
- `constants.py` — 2026 tax brackets, RMD tables, IRMAA tiers
- `docs/research/` — internal research/scratch notes (not user-facing)

## Testing & linting
```
python -m pytest test_retirement.py -q   # full suite
ruff check .                             # lint gate (config in ruff.toml)
```

## Release checklist
1. Working tree clean; all changes committed.
2. `python -m pytest test_retirement.py -q` passes.
3. `ruff check .` is clean.
4. Bump `__version__` in `app.py` and add a `CHANGELOG.md` entry.
5. Tag the release.

## Open considerations
@CONSIDERATIONS.md
