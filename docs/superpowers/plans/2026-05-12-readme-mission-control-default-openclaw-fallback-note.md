# README mission_control_default fallback note Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one README line under `mission_control_default` explaining that when Claude CLI is temporarily unavailable, setting `OPENCLAW_ASSIGN_TRIAGE_LOCAL=openclaw_router` and `OPENCLAW_ASSIGN_REVIEW_LOCAL=openclaw_router` can temporarily move `triage` / `review` to OpenClaw so the default tail chain keeps running.

**Architecture:** This is a documentation-only change in `README.md`. Keep the existing `mission_control_default` description intact and insert a single bullet in the default-pipeline section near the current OpenClaw fallback notes so the guidance is easy to find without changing behavior.

**Tech Stack:** Markdown

---

### Task 1: Locate the insertion point

**Files:**
- Modify: `README.md:86-103`

- [ ] **Step 1: Review the current `mission_control_default` block**
  Verify the note belongs in the list immediately after the ten-step pipeline description, before the OpenClaw variant bullets.

- [ ] **Step 2: Confirm the sentence only adds one bullet**
  Target wording should mention Claude CLI temporarily unavailable, `OPENCLAW_ASSIGN_TRIAGE_LOCAL=openclaw_router`, `OPENCLAW_ASSIGN_REVIEW_LOCAL=openclaw_router`, and that this keeps the default tail chain running.

### Task 2: Apply the README edit

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Insert the new bullet**
  Add one Markdown bullet under the `mission_control_default` explanation with the approved wording; do not change any other bullets or paragraphs.

- [ ] **Step 2: Keep formatting consistent**
  Match the surrounding Chinese prose, inline code style, and bullet punctuation.

### Task 3: Verify the doc-only diff

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Inspect the diff**
  Run: `git diff -- README.md`
  Expected: exactly one added bullet line in the `mission_control_default` section.

- [ ] **Step 2: Sanity-check the rendered text**
  Run: `sed -n '82,108p' README.md`
  Expected: the new note appears once, in the intended section, with no unrelated text changes.
