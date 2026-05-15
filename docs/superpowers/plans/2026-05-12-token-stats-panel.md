# Token Stats Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dedicated Token Stats panel to the Mission Control Web UI that makes existing OpenClaw usage data easier to read without introducing cost estimation or backend schema changes.

**Architecture:** Reuse the usage summaries already emitted into bootstrap and recent run insights, and present them in a new dashboard panel alongside the existing Hermes and Run Compare cards. Keep all computation client-side in `openclaw_v2/webui/app.js`; no new server endpoints or config fields are needed.

**Tech Stack:** HTML, vanilla JavaScript, existing Web UI CSS layout, Python unittest-based regression checks.

---

### Task 1: Add the Token Stats panel to the Web UI

**Files:**
- Modify: `openclaw_v2/webui/index.html`
- Modify: `openclaw_v2/webui/app.js`

- [ ] **Step 1: Add the new panel container to the dashboard layout**

Insert a new `<section class="panel">` inside the existing `insight-grid`, next to `Hermes Control` and `Run Compare`, with:
- heading: `Token Stats`
- a short subtitle that says it summarizes OpenClaw usage from the current or latest run
- a dedicated container with `id="token-stats-panel"`

- [ ] **Step 2: Bind the new DOM node and compute the panel payload**

In `openclaw_v2/webui/app.js`, add a new `elements.tokenStatsPanel = document.getElementById("token-stats-panel")` entry and a small helper that selects usage data from the best available source:
- prefer the currently loaded run payload when present
- otherwise fall back to the newest `bootstrap.recentRuns[0]`
- keep using existing `formatOpenClawUsageSummary()` and `formatOpenClawUsageTrend()` helpers

- [ ] **Step 3: Render a structured token summary**

Implement `renderTokenStatsPanel(bootstrap)` so the panel shows:
- a status chip that is `passed` when usage data is present and `warning` when it is missing
- total tokens
- number of results with usage
- last-call sample count
- last-call token total
- a short note for the most recent trend when more than one recent run exists

The implementation should stay purely presentational and must not introduce any cost/rate conversion.

- [ ] **Step 4: Wire the panel into the existing render flow**

Call the new render helper from the same bootstrap/render path that already refreshes the other dashboard cards, and refresh it again when a run is loaded so the panel always reflects the current dashboard context.

- [ ] **Step 5: Verify the UI source still parses**

Run:

```bash
node --check openclaw_v2/webui/app.js
```

Expected: exit 0.

### Task 2: Add regression coverage for the new panel

**Files:**
- Modify: `tests/test_webui_static.py`

- [ ] **Step 1: Add a static source regression for the panel**

Add assertions that the source now contains:
- `id="token-stats-panel"`
- `function renderTokenStatsPanel(bootstrap)`
- `elements.tokenStatsPanel`
- the existing usage helpers, not any new rate/cost logic

Also assert the source does not introduce a cost-estimation string such as `estimatedCost`, `usd`, or `rate`.

- [ ] **Step 2: Verify the static test file catches the new surface**

Run:

```bash
python3 -m unittest tests.test_webui_static
```

Expected: pass.

- [ ] **Step 3: Run the full Python test suite**

Run:

```bash
python3 -m unittest discover -s tests
```

Expected: pass.

### Task 3: Sanity-check the dashboard behavior

**Files:**
- No code changes expected

- [ ] **Step 1: Confirm the dashboard still renders existing usage surfaces**

Verify the updated UI still exposes usage summaries in the places that already relied on them:
- recent runs
- run compare
- run summary output

- [ ] **Step 2: Confirm no backend data model changes were needed**

Check that `openclaw_v2/web.py` and `openclaw_v2/usage_stats.py` remain unchanged, because the panel is built entirely from the data already returned by bootstrap and run insights.

- [ ] **Step 3: Commit once the UI and tests are green**

Use a single commit that covers the dashboard panel and the regression test update.

```bash
git add openclaw_v2/webui/index.html openclaw_v2/webui/app.js tests/test_webui_static.py
git commit -m "feat: add token stats panel to web ui"
```
