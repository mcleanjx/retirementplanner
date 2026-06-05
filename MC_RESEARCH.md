# Monte Carlo for Retirement — 2026 Research Notes

Synthesis of current best practice for retirement Monte Carlo (Kitces, Pfau, Vanguard / JPM / BlackRock CMAs, Morningstar, Retirement Researcher). Companion to `retirement_monte_carlo.md` (the original v1 spec) and to the engines in `montecarlo.py` / `montecarlo_v2.py`.

The single biggest takeaway: **the most-cited "MC weakness" — fat tails — turns out to be a smaller problem than the silent assumption that annual returns are independent**. Everything below sits downstream of that.

---

## 1. The independence assumption is the dominant modeling error

Independent annual draws are the convenient default (it's what both engines and the original spec do). But Kitces / Tharp's analysis is the clearest counter:

- Annual real-asset returns are reasonably close to normal — they pass Shapiro-Wilk. Daily / monthly returns are fat-tailed; annual returns largely aren't. So fat-tail fixes (Student-t, etc.) operate at the wrong timescale for an annual-step planner.
- Real markets exhibit **negative serial correlation** at multi-year horizons: bad stretches tend to be followed by recoveries, and valuation contracts and expands. Independent draws strip this out.
- The empirical consequence: independent-draw MC strings together long unbroken bear runs that have never happened, **overstating** left-tail failure. Tharp shows a 93.5% MC success rate corresponding to 100% survival across every rolling historical 30-year period at 4% — and 6.5% of MC trials failed *faster than any sequence in US history*.
- Lowering CMA inputs (e.g. to a 2% real return) compounds the error, pushing 50% of trials *worse than the Great Depression*. Using lowered CMAs and "shoot for 95%+" together is a known trap.

Practical implication for this app: the v2 engine already feels "honest" because the tails look severe, but the severity comes partly from a modeling artifact, not realism. Adding mean reversion / block-bootstrap is more valuable than adding Student-t.

## 2. Fat-tail fixes — overrated at annual horizon, still useful as an option

- Student-t (df 5–7) widens both tails by the same amount, so it doesn't preferentially capture downside; it just inflates variance. Not a substitute for mean reversion or serial correlation.
- **Bootstrap from historical annual returns** preserves whatever skew/kurtosis is in the historical record without parametrizing it. Cheap to implement; biases results to the specific sample used.
- **Block bootstrap** (3–10 year blocks) is the cleanest single fix because it captures fat tails, serial correlation, mean reversion, and stock–bond co-movement *simultaneously*. Pralana, Retirement Researcher, and a growing share of academic work use it. Block length is the only knob; longer blocks ≈ historical sequencing, shorter blocks ≈ parametric MC.
- **Regime-switching / Markov models** (high-vol vs. low-vol regimes) capture volatility clustering. Heavier to calibrate; more useful for sub-annual horizons.

## 3. Capital market assumptions are time-varying — current consensus is below the original spec

The numbers in `retirement_monte_carlo.md` (US Large 7.5% / 15.5%, US Bonds 4.5% / 5.5%) match the 2022-era consensus. As of the 2026 CMA round:

| Asset | Vanguard 2026 (10y nominal) | BlackRock late-2025 | Original spec |
|---|---|---|---|
| US equity | 3.5–5.5% | ~5.0% | 7.5% |
| US value | 5.8–7.8% | — | — |
| US growth | 2.3–4.3% | — | — |
| Non-US developed | 4.9–6.9% | 7.1% | 7.5% |
| US agg bonds | — | 4.1% | 4.5% |

JPM 2026 LTCMA follows the same direction (lower equity, higher bonds vs. 2022).

Two implications:
1. A hardcoded 5% global retirement return is now plausibly *too high* for US-large-tilted portfolios — but plausibly *too low* if the user is value-tilted. The CMA-vs-user-assumption decoupling matters more than it used to.
2. Forward CMAs are a calibration choice the user (or app) makes once a year. Burying them at 5% and 5.5/15.5% volatility hides that choice.

## 4. Inflation correlation matters more in the 2020s than it did in the 2010s

Independent inflation and returns understate sequence risk. Stocks tend to deliver worse real returns when inflation surprises upward; nominal bonds get crushed. This was a footnote in 1995-era SWR research; 2022 made it material. v2 already draws stochastic inflation, but the equity/bond Cholesky doesn't include inflation as a third factor, so the comovement isn't modeled.

## 5. Dynamic withdrawal rules dominate engine tweaks

Across every published comparison, switching from constant-real ("4% rule") to guardrails / floor-and-ceiling raises starting safe withdrawal more than any engine refinement. Morningstar's 2024 review: guardrails gave the highest starting SWR (5.2%); Kitces / Guyton showed 5.0–5.5% with comparable success rates. The cost is income variability; the benefit is that the model now reflects actual retiree behavior.

The Kitces critique: when interpreting success rate, "failure" usually means "spending got reduced," not "ran out of cash at 78." Reporting *only* a success number is misleading; advisors increasingly report:
- **Probability of adjustment** — how often spending changes
- **Magnitude of adjustment** — how big the cut
- **Floor probability** — how often the user hits the spending floor

These are richer outputs than a single % survival.

## 6. Reporting: percentile *bands* aren't percentile *paths*

The fan chart most planners draw — including this app's — takes the p10 / p25 / p50 / p75 / p90 of portfolio value *at each age*. That's a legitimate marginal distribution, but the band at age 85 doesn't correspond to a trajectory that ever happened in any single trial. The p10 path is not "the 10th-worst trial"; it's the 10th-percentile balance at each age, often crossing many trials.

Two ways to address:
1. Show the band *and* overlay 5–10 actual worst-case trajectories (terminal-balance-ranked).
2. Report "depletion age" distribution explicitly (already done) — that's a per-trial outcome.

## 7. Sample size and variance reduction

- 1,000 trials gives a standard error of ~1.6 percentage points on a 90% success rate. Fine for headline reporting, noisy for percentile bands.
- 10,000 trials reduces SE to ~0.5pp. Common professional default.
- Sobol / Halton sequences (quasi-MC) hit the same accuracy in ~10× fewer trials by avoiding pseudo-random clumping. Easy to implement: replace `rng.standard_normal` with `scipy.stats.qmc.Sobol(...).random_base2(...)` → normal via inverse-CDF.
- Antithetic variates (pair each draw with its negation) halve variance for free.

For this app, where each trial is expensive (full `simulate_retirement` with binary-search fixed-net), variance reduction is high-leverage.

## 8. Sequence-of-returns stress test as a deterministic supplement

Pure MC under-weights the *specific* failure mode that matters: bad returns in years 1–10 of retirement. A deterministic "early-bear" overlay (e.g. −20%, −10%, then average) communicates this risk in a way the success-rate number doesn't. Several commercial tools run this in parallel with MC.

## 9. CAPE-adjusted near-term returns

A near-consensus refinement (Research Affiliates, GMO, Vanguard): start equity returns lower than the long-run CMA based on current CAPE, then revert over 10 years. The original spec describes this; the app removed it (correctly) when the hardcoded CAPE went stale. The right fix is to expose CAPE as an annually updated user input, not to bake it in.

## 10. Per-account allocation realism

Both engines currently treat *all* investment accounts as having the same stock/bond mix. Real portfolios are often quite different: Roth accounts skewed to equity (longest horizon), bond funds concentrated in traditional / taxable, REIT carving its own factor exposure. With shared equity/bond factors, the *correlation structure* is right, but the per-account *exposure* isn't. This silently underestimates the location-allocation benefit some users plan around.

---

## Sources

- [Kitces — Fat Tails In Monte Carlo Analysis vs Safe Withdrawal Rates](https://www.kitces.com/blog/monte-carlo-analysis-risk-fat-tails-vs-safe-withdrawal-rates-rolling-historical-returns/)
- [Kitces — A 50% Probability Of Success Can Work (success-rate reframing)](https://www.kitces.com/blog/monte-carlo-retirement-projection-probability-success-adjustment-minimum-odds/)
- [Kitces — Reframing Retirement Risk As Over/Under-Spending](https://www.kitces.com/blog/retirement-income-risk-monte-carlo-probability-sucess-over-under-spend/)
- [Kitces — Renaming the Outcomes of an MC Projection](https://www.kitces.com/blog/renaming-the-outcomes-of-a-monte-carlo-retirement-projection/)
- [Kitces — Assessing MC Model Predictiveness (Brier scores)](https://www.kitces.com/blog/monte-carlo-models-simulation-forecast-error-brier-score-retirement-planning/)
- [Kitces — Why Guyton-Klinger Guardrails Are Too Risky (risk-based variant)](https://www.kitces.com/blog/guyton-klinger-guardrails-retirement-income-rules-risk-based/)
- [Pralana wish list — block bootstrap discussion](https://pralanaretirementcalculator.com/community/pralana-wish-list-forum/bootstrap-monte-carlo/)
- [Retirement Researcher — Advantages of MC vs historical](https://retirementresearcher.com/advantages-monte-carlo-simulations/)
- [McLean Asset Management — Monte Carlo vs Historical Simulations](https://www.mcleanam.com/monte-carlo-simulations-vs-historical-simulations/)
- [Vanguard Capital Markets Model forecasts (2026)](https://corporate.vanguard.com/content/corporatesite/us/en/corp/vemo/vemo-return-forecasts.html)
- [BlackRock Capital Market Assumptions](https://www.blackrock.com/institutions/en-global/institutional-insights/thought-leadership/capital-market-assumptions)
- [JPMorgan 2026 Long-Term Capital Market Assumptions](https://am.jpmorgan.com/content/dam/jpm-am-aem/americas/us/en/institutional/insights/portfolio-insights/ltcma-full-report.pdf)
- [Morningstar — Experts Forecast Stock and Bond Returns: 2026 Edition](https://www.morningstar.com/markets/experts-forecast-stock-bond-returns-2026-edition)
- [Quant Decoded — When Monte Carlo Fails](https://quantdecoded.com/en/when-monte-carlo-fails-retirement-planning-pitfalls)
- [Retirement Lab — How It Works (fat-tail / historical stress)](https://retirement-lab.com/how-it-works/)
- [Retirement Lab — Guyton-Klinger Glossary](https://retirement-lab.com/learn/glossary/guyton-klinger-rules/)
- [Income Laboratory — Retirement Income Guardrails](https://incomelaboratory.com/retirement-income-guardrails-complete-guide/)
- [Wealthvieu — Guardrails spending](https://wealthvieu.com/guardrails-spending/)
- [Portfolio Optimizer — Bootstrap Simulation for Financial Planning](https://portfoliooptimizer.io/blog/bootstrap-simulation-with-portfolio-optimizer-usage-for-financial-planning/)
- [Wikipedia — Quasi-Monte Carlo](https://en.wikipedia.org/wiki/Quasi-Monte_Carlo_method)
