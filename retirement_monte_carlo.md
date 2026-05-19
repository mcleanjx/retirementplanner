# Retirement Portfolio Monte Carlo Simulation

A specification for building a multi-asset Monte Carlo retirement simulator using assumptions consistent with mainstream financial-planning practice (capital market assumptions from JPMorgan, Vanguard, BlackRock, Horizon Actuarial, etc.).

---

## 1. Core Concept

Replace single-point return assumptions with thousands of randomly generated return paths, then look at the **distribution of outcomes** — especially the probability the portfolio survives the full retirement horizon.

### The basic loop

For each of N trials (typically 1,000–10,000):

1. Start with the initial balance
2. For each year in the horizon:
   - Draw a random return (correlated across assets)
   - Apply it to the balance
   - Subtract that year's withdrawal (grown by inflation)
3. Record whether the portfolio reached zero and what the ending balance was

Aggregate across trials to get success rate, percentile bands for ending wealth, and worst-case paths.

---

## 2. Key Modeling Choices

**Return generation.** Standard approach: draw annual log-returns from a multivariate normal parameterized by expected return, volatility, and correlation. Alternatives: bootstrap from historical annual returns (preserves fat tails/skew), or block-bootstrap (preserves short-run serial correlation).

**Inflation.** Constant (2.5%) or stochastic. Stochastic matters because real returns and inflation are correlated — stocks tend to do worse in high-inflation regimes.

**Withdrawal rule.** Constant real ("4% rule"), constant percentage of balance, or dynamic rules like Guyton-Klinger guardrails. Constant-real creates the sharpest sequence-of-returns risk.

**Asset allocation and rebalancing.** Typically rebalance annually back to target weights. If modeling a glide path, allocations shift over time.

---

## 3. Capital Market Assumptions (Planner Defaults)

Nominal long-term assumptions roughly aligned with current 10–15 year CMA consensus:

| Asset            | Expected Return | Volatility |
| ---------------- | --------------- | ---------- |
| US Large Cap     | 7.5%            | 15.5%      |
| US Small Cap     | 8.5%            | 20.0%      |
| Intl Developed   | 7.5%            | 17.5%      |
| Emerging Markets | 8.5%            | 23.0%      |
| US Agg Bonds     | 4.5%            | 5.5%       |
| TIPS             | 3.5%            | 5.0%       |
| Cash             | 3.0%            | 1.0%       |

**Inflation:** 2.5% mean, 1.5% volatility

**Correlations (long-run averages):**
- Equities to equities: 0.70–0.85
- Equities to bonds: 0.00–0.15
- Bonds to TIPS: ~0.70

---

## 4. Reference Implementation

```python
import numpy as np

# ---- Capital Market Assumptions ----
assets = ['US_Large', 'US_Small', 'Intl_Dev', 'EM', 'US_Bonds', 'TIPS', 'Cash']
means = np.array([0.075, 0.085, 0.075, 0.085, 0.045, 0.035, 0.030])
vols  = np.array([0.155, 0.200, 0.175, 0.230, 0.055, 0.050, 0.010])

# Long-run correlation matrix
corr = np.array([
    [1.00, 0.85, 0.80, 0.70, 0.10, 0.00, 0.00],
    [0.85, 1.00, 0.75, 0.70, 0.05,-0.05, 0.00],
    [0.80, 0.75, 1.00, 0.75, 0.10, 0.00, 0.00],
    [0.70, 0.70, 0.75, 1.00, 0.05, 0.00, 0.00],
    [0.10, 0.05, 0.10, 0.05, 1.00, 0.70, 0.20],
    [0.00,-0.05, 0.00, 0.00, 0.70, 1.00, 0.15],
    [0.00, 0.00, 0.00, 0.00, 0.20, 0.15, 1.00],
])

# Moderate 60/40 allocation
weights = np.array([0.30, 0.10, 0.12, 0.08, 0.30, 0.05, 0.05])

INFL_MEAN, INFL_VOL = 0.025, 0.015


def simulate(
    initial=1_500_000,
    withdrawal=60_000,        # year-1 withdrawal in today's dollars (4%)
    years=30,
    weights=weights,
    n_trials=10_000,
    seed=42,
):
    rng = np.random.default_rng(seed)
    n = len(means)

    # Convert arithmetic moments to log-space for log-normal sampling
    log_mu = np.log(1 + means) - 0.5 * vols**2
    cov    = corr * np.outer(vols, vols)
    log_cov = np.log(1 + cov / np.outer(1 + means, 1 + means))
    L = np.linalg.cholesky(log_cov + 1e-12 * np.eye(n))

    # Correlated annual log-returns, then exponentiate
    z = rng.standard_normal((n_trials, years, n))
    log_r = log_mu + z @ L.T
    asset_growth = np.exp(log_r)                    # (trials, years, assets)

    # Annual rebalance to target weights — portfolio return per year
    port_growth = asset_growth @ weights            # (trials, years)

    # Stochastic inflation path
    infl = rng.normal(INFL_MEAN, INFL_VOL, size=(n_trials, years))
    cum_infl = np.cumprod(1 + infl, axis=1)

    # Run the year-by-year loop
    balances = np.full(n_trials, float(initial))
    history  = np.zeros((n_trials, years + 1))
    history[:, 0] = initial
    survived = np.ones(n_trials, dtype=bool)

    for t in range(years):
        balances = balances * port_growth[:, t]     # grow
        balances -= withdrawal * cum_infl[:, t]     # withdraw (inflation-adjusted)
        survived &= balances > 0
        balances = np.maximum(balances, 0)
        history[:, t+1] = balances

    return {
        'success_rate': survived.mean(),
        'percentiles': {p: np.percentile(balances, p) for p in [5, 10, 25, 50, 75, 90]},
        'history': history,
        'survived': survived,
    }


if __name__ == '__main__':
    r = simulate()
    print(f"Success rate: {r['success_rate']:.1%}")
    for p, v in r['percentiles'].items():
        print(f"  p{p:>2}: ${v:>14,.0f}")
```

---

## 5. Reporting Outputs (What Planners Use)

The headline metric is **success rate** — the fraction of trials where the portfolio survives the full horizon.

Industry conventions:

- **90%+** — conservative, "very high confidence"
- **80–90%** — typical target zone for retirees
- **70–80%** — "monitor and adjust" territory
- **Below 70%** — plan likely needs changes (lower spending, more savings, delayed retirement)

Pair success rate with:

- Percentile bands on ending wealth (p5, p10, p25, p50, p75, p90)
- Legacy/bequest distribution
- Worst-case path visualization (5th–10th percentile balances over time)

Worst-case paths matter more than the median: a plan that succeeds on average but fails in 20% of futures isn't really a plan.

---

## 6. Common Refinements (in order of impact)

### 6.1 Dynamic withdrawal rules (highest impact)

Guyton-Klinger guardrails: cut spending after bad years, raise after good ones. Floor-and-ceiling rules also work. Success rates jump materially because the retiree responds to conditions.

Example guardrail logic:
- If current withdrawal rate > 20% above initial — cut spending 10%
- If current withdrawal rate < 20% below initial — raise spending 10%
- Otherwise grow withdrawal with inflation

### 6.2 CAPE / valuation-based return adjustment

Reduce near-term equity returns based on current valuations (Shiller CAPE, equity risk premium), then revert to long-run assumptions over 10 years. Roughly matches Research Affiliates and GMO methodology.

### 6.3 Bond yields anchoring forward returns

Starting yield on the Agg is a strong predictor of 10-year bond returns. Anchor bond returns to current yields rather than long-term averages.

### 6.4 Sequence-of-returns stress test

Layer on a deterministic bad-start scenario: −20% in year 1, −10% in year 2, then average returns. Pure Monte Carlo can under-represent how punishing a bad early sequence is.

### 6.5 Fat tails

Replace normal with Student-t (df ≈ 5–7) or bootstrap from historical returns. Equity tails are demonstrably fatter than Gaussian — 2008 was a ~4σ event under normal assumptions, which should happen roughly never.

### 6.6 Account types and tax modeling

Tax-deferred vs. taxable vs. Roth, with RMDs starting at 73, Social Security claiming decisions, pension income, Medicare/LTC cost shocks. This is where commercial tools like MoneyGuidePro and eMoney earn their license fees.

---

## 7. Common Pitfalls

- **Arithmetic vs. geometric returns.** Don't forget the volatility-drag term (`-0.5*vol²`) when converting between log and arithmetic space.
- **Independent annual draws miss volatility clustering and mean reversion.** A regime-switching model or block-bootstrap addresses this.
- **Normal distributions understate tail risk.** Use Student-t or bootstrap for honest left-tail estimates.
- **Reporting only the average ending balance.** Lead with success rate and the 5th–10th percentile paths.
- **Ignoring inflation correlation with returns.** Real returns and inflation co-move; modeling them independently can understate sequence risk.

---

## 8. Suggested Build Order for Claude Code

1. Start with `simulate()` as-is, verify success rate looks reasonable for 4% rule / 60/40 / 30 years (expect ~85–95%).
2. Add CLI arguments via `argparse` or `typer` for initial balance, withdrawal, years, allocation, n_trials.
3. Add matplotlib output: fan chart of percentile bands over time, histogram of ending wealth.
4. Add Guyton-Klinger withdrawal mode as an alternative to constant-real.
5. Add CAPE-based equity return adjustment as a `regime_adjust=True` flag.
6. Add Social Security and pension income streams (subtract from gross withdrawal need).
7. Add tax-aware account drawdown order (taxable → tax-deferred → Roth).
