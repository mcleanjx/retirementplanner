# Performance Improvements

Living document for performance opportunities and decisions. Nothing here is
implemented yet unless explicitly marked **Done**. Update when work lands or new
bottlenecks surface.

---

## Open Opportunities

### Parallelize the optimizer across CPU cores *(deferred — "not that slow" for now)*

**Symptom.** Optimizer runs take noticeable wall-clock time but the machine sits
near-idle (one core busy, the rest cold; e.g. ~1/28 logical CPUs on the dev box).

**Why.** `simulate_retirement` is pure-Python, CPU-bound work, and the optimizer
calls it serially: `n_iterations × len(return_band)` simulations, each running a
per-year loop (and, in fixed-net spending mode, a per-year binary search that is
~5× the SWR cost — see CONSIDERATIONS.md). The standard CPython build has the GIL
enabled (`sys._is_gil_enabled()` → `True`), so **threads cannot parallelize this**.
Only separate **processes** will use more cores. (A free-threaded 3.13+/`t` build
would let threads work, but that's not the build in use.)

**The trials are embarrassingly parallel**, so a process pool should give roughly a
linear speedup up to core count (~6–8× is a safe expectation after overhead).

**Design (keeps results bit-for-bit deterministic):**
1. **Phase 1 — sample sequentially (cheap).** Pre-generate every trial's strategy
   tuple via `_sample_strategy(...)` in order, consuming the single seeded
   `random.Random` exactly as today. This preserves the RNG draw order, so a given
   seed yields the identical set of trials as the serial path.
2. **Phase 2 — simulate in parallel (expensive).** Fan the strategy tuples out to a
   `ProcessPoolExecutor`. Workers call `_evaluate_across_band(...)` and return only
   **lightweight** results (`score`, `band_scores`, `band_metrics`) — *not* the
   `ret_df` DataFrames, to keep inter-process traffic small.
3. **Re-attach plans in the main process.** Sort by robust score, take the top ~10
   (+ baseline), and re-run `_evaluate_across_band` for just those to recover their
   `ret_df`/`summary` for display. That's ≤~10 extra sims — negligible.

**Implementation notes / gotchas:**
- Worker function and its arguments must be **module-level and picklable**
  (define the worker in `optimizer.py`, not as a closure). Pass the shared big data
  (account variants, profile, assumptions) once via the executor `initializer`/
  `initargs` into a module-level context dict, so each task only ships the small
  strategy tuple.
- Add an opt-in `n_workers` (or `parallel`) parameter to `run_optimizer`; default to
  serial so nothing changes unless requested. Surface a "Parallel workers" control
  in the Optimizer tab (v1 path only — see parity note).
- `_sample_strategy`'s dead `min_conv_age > conv_max_end` early-return is a 2-tuple;
  in practice it never fires (`conv_max_end ≥ min_conv_age + 1`), but the pre-sample
  loop should defensively skip any non-3-tuple to match today's "trial failed → skip,
  not counted" behavior.

**Cross-platform.** The above design is portable as-is:
- **macOS** and **Windows** default to the `spawn` start method, which re-imports
  the main module in each worker. `app.py` is guarded by
  `if __name__ == "__main__": main()`, so workers won't re-run the app — they only
  pay a one-time re-import of `app.py` (and thus `streamlit`) at worker startup,
  amortized across the run since the pool is reused.
- **Linux** defaults to `fork` (no re-import; cheaper startup).
- Pin the context explicitly for identical behavior everywhere and test once:
  ```python
  import multiprocessing as mp
  from concurrent.futures import ProcessPoolExecutor
  ctx = mp.get_context("spawn")
  with ProcessPoolExecutor(max_workers=n, mp_context=ctx) as ex:
      ...
  ```

**Parity.** `optimizer.py` (v1) is the natural first target. `optimizer_v2.py`
and `optimizer_v3.py` have their own trial loops and would each need the same
phase-1/phase-2 split; v3's Monte Carlo inner loop is itself a parallelization
candidate.

**Effort.** ~half a day for v1 (driver + worker + UI toggle + a determinism test
asserting serial and parallel produce the same best score for a fixed seed).

**Status.** Deferred by user — current runs are acceptable. Revisit if v2/high-
iteration/wide-band runs become painful.

---

## Done

*(nothing yet)*
