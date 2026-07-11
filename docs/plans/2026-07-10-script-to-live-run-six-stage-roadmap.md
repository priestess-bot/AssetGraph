# 剧本驱动直播间自动搭建与前后台同步采集 Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task when work is split across agents. Current execution starts with Stage 1 in this session.

**Goal:** Build a reliable pipeline where a user-provided script becomes a Maitu live-room draft, can be explicitly authorized to go live, and has JD backend metrics captured synchronously by scene.

**Architecture:** AssetGraph remains the decision/state layer: script parsing, template matching, asset selection, BuildPlan generation, execution/evidence records, LiveRun orchestration, and metric samples. Browser-use/Maitu/JD workers are execution and observation layers: they perform small verified UI/API actions and write results back. Official go-live remains behind an explicit authorization gate.

**Tech Stack:** FastAPI + PostgreSQL repositories in `backend/`; Browser-use worker package in `workers/browser-use/`; Maitu page-context API calls for draft room/clip mutation; JD live dashboard read-only Browser-use capture; pytest/compileall for verification.

---

## Stage 0 — Livestream script generation and quality gate

**Objective:** Generate the authoritative spoken script from structured verified facts before any scene, asset, layout, or BuildPlan work starts.

**Implemented contract:**

1. `POST /api/maitu/livestream-script-drafts` returns pure spoken text, traceable content sections, duration estimates, and a quality report.
2. `POST /api/maitu/script-driven-build-pipelines` runs script generation through scene planning, content-derived asset needs, real asset selection, gap reporting, layout, and BuildPlan generation.
3. Unknown catalog totals are never inferred from the submitted products.
4. Unverified promotions are excluded from spoken text and recorded as dropped claims.
5. Insufficient verified material never triggers repeated filler; it blocks automatic execution with `script_quality_review_required` while keeping review artifacts.
6. The result always keeps `ready_for_go_live=false`; the generated plan only targets a draft room.

**Acceptance:**

```text
Generated sections are the exact source of downstream write_script operations.
Asset needs are derived from generated scene content and keywords.
No unverified promotion or catalog-size assumption enters spoken text.
Quality failure keeps artifacts but forces build_plan.can_execute=false.
```

---

## Stage 1 — Stable single-scene live draft fill

**Objective:** Convert the already-working single-scene `MT-BUILD-*` plan into a repeatable worker command that fills the default first Maitu clip instead of incorrectly creating an extra first scene.

**Tasks:**

1. Document and test default-clip mapping.
   - First planned scene maps to the room's existing default clip.
   - Only planned scene index >= 1 creates new clips.
2. Add worker module `live_scene_fill.py`.
   - Input: BuildPlan operation plan, target Maitu room state, optional explicit target clip id.
   - Output: execution payload with `mode=live_scene_fill` and per-operation evidence.
3. Add `BrowserUseCliSession.fill_single_scene_from_template(...)` facade.
   - Internally uses Maitu API from page context.
   - Does not expose or persist tokens.
4. Add CLI:
   ```bash
   python -m browser_use_worker \
     --build-plan-code MT-BUILD-* \
     --live-scene-fill \
     --target-live-room-id <room_id>
   ```
5. Verify with fake sessions first, then real smoke only on a draft room.

**Acceptance:**

```text
Default clip is renamed/filled for first planned scene.
No extra clip is created for single-scene BuildPlan.
Visual components are inserted cumulatively and verified.
Script text is written and verified.
MT-EXEC-* is written with mode=live_scene_fill.
正式开播 is not clicked.
```

---

## Stage 2 — Multi-scene script decomposition

**Objective:** Turn a full live script into ordered scene plans with goals, durations, and script blocks.

**Tasks:**

1. Add schemas for `ScriptScenePlan` and `ScriptDecomposition`.
2. Implement a deterministic first-pass splitter with optional LLM refinement later.
3. Add endpoint:
   ```text
   POST /api/maitu/script-scene-plans
   ```
4. Persist decomposition as reusable planning artifact.
5. Add tests for 3–8 scene outputs and low-confidence/manual-review cases.

**Acceptance:**

```text
A multi-paragraph script returns ordered scenes.
Each scene has scene_index, scene_name, scene_goal, duration_seconds, script.
No scene is empty.
Manual-review flag appears for ambiguous segments.
```

---

## Stage 3 — Multi-scene template and asset matching

**Objective:** Match every script scene to a template scene and select replacement assets where appropriate.

**Tasks:**

1. For each scene script, search `TemplateScene` / `script_blocks`.
2. Load `TemplateComponent` rows for the matched scene.
3. Apply selection strategy:
   - product-relevant assets first;
   - scene-theme assets second;
   - template-like fallback third;
   - missing/manual-review if no safe match.
4. Persist `selected_asset_code`, local/UI-friendly codes, match score, and reasons.
5. Add a missing-material report.

**Acceptance:**

```text
Each scene has matched_template_scene_code or manual_review.
Each replaceable component has selected_asset_code or missing reason.
MT-TPL preview assets are never selected as real layer materials.
```

---

## Stage 4 — Multi-scene BuildPlan and draft build

**Objective:** Generate and execute full-room draft BuildPlans.

**Tasks:**

1. Extend BuildPlan generation to multiple scene groups.
2. Enforce default first clip mapping.
3. Create clips only for scene_index >= 1.
4. Fill each scene with components and scripts.
5. Write execution evidence per scene.

**Acceptance:**

```text
clip_count == scene_count.
Scene names match planned scene names.
Each scene has expected visual/text counts.
MT-EXEC-* records per-scene operation results.
No go-live click.
```

---

## Stage 5 — LiveRun orchestration and foreground/background sync

**Objective:** Introduce one LiveRun session binding Maitu build execution and JD metric capture.

**Tasks:**

1. Add `LIVE-RUN-*` schema/table/API.
2. Link:
   - build_plan_code
   - maitu_live_room_id
   - frontend_execution_code
   - jd_metric_session_code
   - scene_schedule
3. Create JD-METRIC session before go-live.
4. Start JD capture when foreground live run starts.
5. Record scene start/end events and align samples to events.

**Acceptance:**

```text
One LIVE-RUN-* can show draft/build/preflight/JD capture status.
JD samples include scene_index and scene_name.
Samples are taken during live execution, not only afterward.
```

---

## Stage 6 — Go-live authorization and scene-level replay report

**Objective:** Add a safe go-live gate and generate post-run scene performance reports.

**Tasks:**

1. Add go-live preflight checks.
2. Require explicit user authorization containing the target liveRoomId.
3. Execute go-live only after preflight + authorization.
4. Capture JD samples during live run.
5. Aggregate metrics by scene and generate recommendations.

**Acceptance:**

```text
Without explicit authorization, go-live is blocked.
After run, report shows scene-level viewers, stay, clicks, conversion, GMV, interactions.
Report identifies drop-off / lift / optimization suggestions.
```

---

## Immediate execution order

1. Stage 1 tests for default-clip mapping and live_scene_fill payload.
2. Stage 1 minimal implementation.
3. Worker/backend test + compileall.
4. Commit Stage 1.
5. Then proceed to Stage 2.
