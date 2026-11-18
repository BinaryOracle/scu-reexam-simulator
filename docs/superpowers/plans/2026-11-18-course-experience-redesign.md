# Course Experience Redesign Implementation Plan

> **For agentic workers:** Execute inline in this session. Steps use checkbox syntax and require focused tests after each behavior change.

**Goal:** Replace the confusing dual course/legacy-live library experience with a coherent course center for discovery, authoring, and learning.

**Architecture:** Keep existing course/live tables and room/session services. Add a public-safe preview API and server-side publication validation, then route the course navigation through one course-center UI with learner and administrator workspaces.

**Tech Stack:** FastAPI, SQLite, native ES modules and CSS, pytest, Playwright.

## Constraints

- Preserve existing live lesson IDs, room IDs, recordings, moderation, and membership authorization.
- Public previews expose course outline only; lesson content and media remain membership-protected.
- Draft courses may be incomplete; published courses must pass server-side readiness validation.
- Do not modify unrelated training-page changes in `app/static/index.html` or `app/static/training.css`.

## File Map

- `app/routes/courses.py`: safe catalog projection, public course preview, enrollment, publication validation.
- `app/services/course_learning.py`: preview projection and course readiness checks.
- `app/static/live.js`: route the existing course navigation to the single course center.
- `app/static/course-learning.js`: learner home, course plaza, public preview, management workspace, learning shell.
- `app/static/course-learning.css`: responsive course-center visual system.
- `tests/test_course_learning.py`: API authorization, preview, and publish readiness.
- `docs/live-classroom.md`, `README.md`: authoring and learner workflows.

## Tasks

### Task 1: Public preview and publication readiness

- [ ] Add tests proving unaffiliated users can read only published-public outline metadata, but cannot read lesson bodies, member IDs, progress, media tickets, or join drafts/roster courses.
- [ ] Add tests proving incomplete courses remain saveable as drafts and cannot transition to published; a populated course can publish.
- [ ] Implement a dedicated public preview projection and `GET /api/courses/public/{course_id}`.
- [ ] Implement shared readiness validation in create/update paths whenever status becomes `published`.
- [ ] Run `.venv/bin/pytest -q tests/test_course_learning.py`.

### Task 2: Single course center and discovery flow

- [ ] Make `/live` render the new course center and remove the duplicate legacy course catalog/detail routes; retain live lesson routes and classroom behavior.
- [ ] Add explicit learner tabs for continue-learning and course plaza; add admin-only course management tab.
- [ ] Add public preview route state, preview screen, and join-to-first-lesson transition.
- [ ] Give empty, loading, error, no-search-results, and joined states direct feedback and next actions.
- [ ] Check JavaScript syntax and focused navigation behavior.

### Task 3: Course authoring and learning workspace

- [ ] Replace the modal-first course authoring path with an independent management list and guided information/content/roster-publishing editor.
- [ ] Keep draft save available throughout; show publish readiness errors at the relevant step.
- [ ] Refine course cards and course detail hierarchy; remove decorative ordinal covers and nested-card styling.
- [ ] Preserve the two-column course outline/content learner workspace with fixed previous/next placement and responsive outline disclosure.
- [ ] Ensure progress saves are throttled and final playback position is persisted on pause/page exit.

### Task 4: Verification and documentation

- [ ] Run focused API tests, Python compilation, JavaScript syntax checks, and `git diff --check`.
- [ ] Use the local browser at desktop and narrow viewport for plaza preview/join, course navigation, and admin draft/publish flow.
- [ ] Update docs to describe the course-center entry, preview permissions, draft workflow, and publish checks.
- [ ] Close any server and browser sessions started for verification.
