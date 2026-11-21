# Course Admin and Learning Experience Implementation Plan

> **For agentic workers:** Execute this plan task-by-task in this session. Each task ends with a focused verification before moving to the next.

**Goal:** Deliver the approved course-management workbench, image or preset course covers, Markdown course descriptions and lesson notes, and a clearer learner course experience without replacing the existing course and live-class data model.

**Architecture:** Extend the existing `live_courses` record with cover metadata through the current schema migration mechanism. Keep course APIs and permission checks in `app/routes/courses.py` and `app/services/course_learning.py`; render the admin and learner interfaces through the existing course module in `app/static/course-learning.js` and its stylesheet. Reuse private asset handling where appropriate and preserve live lesson identifiers and authorization.

**Tech Stack:** FastAPI, SQLite, Python pytest, browser-native ES modules, existing UI helpers, CSS.

## Global Constraints

- Keep existing course, section, lesson, asset, enrollment, live-session, and progress records compatible.
- Course descriptions and lesson notes store Markdown source; learner HTML is sanitized on the server.
- Managers are the only course configurators; do not add a global teacher role.
- Cover uploads use private storage, random server filenames, and validated image content.
- Preserve the existing visual palette: warm white, dark text, brick-red accent, and green progress state.
- Keep the administrator course-management surface separate from learner “My Courses” and “Course Plaza” navigation.

---

## File Map

- `app/services/course_schema.py`: add idempotent cover metadata columns to the existing course table.
- `app/services/course_learning.py`: expose cover data, extract plain-text summaries from Markdown, and render sanitized Markdown for course and lesson descriptions.
- `app/routes/courses.py`: accept and return cover fields, add authorized cover upload/delete handling, and preserve existing course access checks.
- `tests/test_course_learning.py`: cover migration, Markdown rendering, summary, upload validation, authorization, and existing access behavior.
- `app/static/course-learning.js`: separate the admin workbench navigation, provide course rows, cover selection/upload and preview, Markdown editor preview, and learner presentation.
- `app/static/course-learning.css`: implement desktop and narrow layouts, editorial course rows, content lists, cover and Markdown preview styles.
- `app/static/index.html`: bump the course stylesheet cache key when its behavior changes.
- `README.md`: update course-management and Markdown/cover usage notes.

## Task 1: Extend course responses with safe Markdown summaries and cover metadata

**Files:** `app/services/course_schema.py`, `app/services/course_learning.py`, `tests/test_course_learning.py`

- [x] Add nullable `cover_kind`, `cover_value`, and `cover_asset_id` columns to `live_courses` using the project’s idempotent schema initialization pattern. Use `cover_kind` values `preset` or `upload`; preserve old records with a null kind.
- [x] Add focused tests showing repeated initialization is safe and Markdown summaries remove syntax markers while preserving readable text.
- [x] Implement a plain-text Markdown summary helper used by catalog responses; cap summaries at a fixed, documented length.
- [x] Extend managed, enrolled, and public preview course responses with cover fields. Do not include management-only fields in public preview.
- [x] Run `.venv/bin/python -m pytest -q tests/test_course_learning.py` and ensure the new tests and existing course behavior pass.

## Task 2: Add private cover upload and sanitized course Markdown rendering

**Files:** `app/routes/courses.py`, `app/services/course_learning.py`, `tests/test_course_learning.py`

- [x] Add request models for cover selection and course description updates without breaking existing clients that omit cover fields.
- [x] Add authenticated manager-only cover upload endpoint. Accept supported raster image types only, enforce the configured upload limit, decode the image before storing, and save under a random server-generated filename in a private covers directory.
- [x] Return safe course and lesson Markdown HTML from authorized details and public previews; expose a server-rendered Markdown preview endpoint for administrators.
- [x] Add tests for unauthorized cover upload, invalid image bytes/type, successful metadata update, Markdown links/code formatting, and rejection/removal of dangerous HTML or protocols.
- [x] Run `.venv/bin/python -m pytest -q tests/test_course_learning.py`.

## Task 3: Build the separate administrator course workbench

**Files:** `app/static/course-learning.js`, `app/static/course-learning.css`, `tests/test_course_learning.py`

- [x] Change the managed catalog to a dedicated workbench header and search/filter toolbar; omit learner tabs entirely for `scope=managed`.
- [x] Render desktop courses as aligned horizontal rows with cover, title, plain-text summary, status, access mode, section/lesson counts, and primary “编辑课程” action. Keep preview, archive, and delete in the row’s secondary action area.
- [x] On narrow screens, stack row details and keep primary/secondary actions visible without horizontal overflow.
- [x] Keep consistent “课程内容 / 课程信息 / 学员与发布” step navigation visible across existing edit steps.
- [ ] Keep empty, loading, error, no-search-results, saving, and destructive confirmation states clear and visually consistent.
- [x] Run JavaScript syntax checking for `app/static/course-learning.js` and `.venv/bin/python -m pytest -q tests/test_course_learning.py`.

## Task 4: Add cover selection and Markdown editing to course information

**Files:** `app/static/course-learning.js`, `app/static/course-learning.css`, `app/routes/courses.py`, `tests/test_course_learning.py`

- [x] Add a course description Markdown editor with adjacent edit/preview controls; preview through the server rendering endpoint rather than trusting client-provided HTML.
- [x] Add a cover selector with curated preset options and image upload. Show the selected cover preview and allow switching from upload back to preset.
- [x] Persist cover selection and course description alongside existing course fields. Preserve current covers when legacy updates omit cover properties.
- [x] Add backend/API tests for create/update compatibility when old clients omit cover properties and for successful cover and Markdown persistence.
- [x] Run `.venv/bin/python -m pytest -q tests/test_course_learning.py` and JavaScript syntax checking.

## Task 5: Improve learner catalog, course detail, and lesson presentation

**Files:** `app/static/course-learning.js`, `app/static/course-learning.css`, `app/routes/courses.py`, `tests/test_course_learning.py`

- [x] Show selected course covers on learner catalog cards and course detail headers. Use the selected preset when no uploaded cover is configured.
- [x] Render Markdown course descriptions and lesson descriptions in learner views using the authorized server renderer. Catalog and directory summaries remain plain text.
- [x] Keep the existing two-column course navigation and content order while surfacing course identity and rendered lesson descriptions.
- [x] Verify public previews do not expose roster or private cover filenames; verify private course descriptions and draft covers remain inaccessible to nonmembers.
- [x] Run `.venv/bin/python -m pytest -q tests/test_course_learning.py`. Browser automation was unavailable in this checkout, so responsive behavior is validated from CSS and remains unverified in a live browser.

## Task 6: Document behavior and run final focused checks

**Files:** `README.md`, `app/static/index.html`, all modified course files

- [x] Update README and live-class deployment instructions for cover choices, Markdown descriptions, and private cover storage.
- [x] Bump the course stylesheet cache key in `app/static/index.html`.
- [x] Run `.venv/bin/python -m pytest -q tests/test_course_learning.py`, `node --check app/static/course-learning.js`, and `git diff --check`.
- [x] Review the final diff to confirm existing user changes remain intact; no live services or processes were started as part of verification.

## Coverage Review

The plan covers the specification’s admin separation, searchable/status-filtered workbench, three editing steps, image and preset covers, safe Markdown and summaries, mixed lesson content presentation, responsive layout, permissions, error states, compatibility, and focused tests. Real browser desktop/mobile review remains part of verification when the local browser test runtime is available.
