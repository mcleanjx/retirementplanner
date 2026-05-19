# Web Framework Options for Future Consideration

## Current Stack

- **Framework:** Streamlit
- **Charts:** Plotly
- **Computation:** Python (projections.py, taxes.py, montecarlo.py, withdrawals.py)

Streamlit can be deployed to the web (e.g., Streamlit Community Cloud), but has real limits for a production web app: it requires a persistent Python server, has limited UI customization, and doesn't scale well to many concurrent users.

---

## Option 1 — Dash (Plotly) — Recommended

Still pure Python, but gives much more layout control, proper callbacks, and deploys cleanly to any Python host.

**Pros:**
- All existing computation modules (charts.py, projections.py, taxes.py, montecarlo.py) transfer almost unchanged
- Only app.py needs a rewrite
- More UI control than Streamlit
- Scales better for production

**Cons:**
- More verbose than Streamlit
- Callback model takes some getting used to

**Best for:** A polished web app for yourself or a small number of users while staying entirely in Python.

---

## Option 2 — FastAPI Backend + React Frontend

Python computation modules become a REST API; the UI is a proper web app (React, Next.js, etc.).

**Pros:**
- Most scalable and customizable option
- Computation backend (the existing Python modules) translates directly — minimal rewrite needed there
- Full control over UI/UX

**Cons:**
- Significantly more work
- Requires JS/React knowledge or a frontend developer
- Two separate codebases to maintain

**Best for:** Sharing with many users or building a fully custom, polished UI.

---

## Summary

| | Streamlit (current) | Dash | FastAPI + React |
|---|---|---|---|
| Python only | Yes | Yes | Backend only |
| UI customization | Low | Medium | High |
| Scalability | Low | Medium | High |
| Migration effort | — | Low | High |
| Computation reuse | — | Near 100% | Near 100% |
