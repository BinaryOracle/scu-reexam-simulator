# Course Learning System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the live-classroom feature into an administered course catalog with ordered chapters and lessons that support live sessions, uploaded recordings, documents, enrollment, and learner progress.

**Architecture:** Keep `live_courses` and the live-session tables as the compatibility source for existing courses and LiveKit room IDs. Add course chapters, lessons, ordered content items, uploaded assets, public-enrollment records, and per-user progress; link existing live lessons into the new lesson model through an explicit foreign key. Add authenticated course APIs and a focused course-learning UI while retaining the immersive live-room implementation.

**Tech Stack:** FastAPI, Pydantic, SQLite, private filesystem storage, native ES modules/CSS, pytest, Node's built-in test runner.

## Global Constraints

- Do not add a global teacher role; administrators manage course content and the existing course host remains a course-scoped live role.
- Preserve every existing live course, member, session, material, recording, webhook, and room ID.
- Draft and archived courses are hidden from the public catalog; published public courses allow self-enrollment; roster courses remain restricted to assigned members.
- Course assets remain outside `/static`; every upload, download, video playback, and live-room request checks course membership.
- Preserve the existing live routes, LiveKit room names, chat, moderation, Egress recording, and playback-ticket behavior.
- Validate upload extensions and byte limits while streaming to disk; filenames stored on disk are random and never derived from user input.
- Increment SQLite `SCHEMA_VERSION` monotonically and make migration safe to run repeatedly.
- Keep the existing uncommitted `app/static/index.html` and `app/static/training.css` changes intact.

---

## File Map

- `app/services/course_schema.py`: idempotent course-learning tables and migration of current live sessions into course lessons.
- `app/services/course_learning.py`: course visibility, enrollment, lesson access, course views, and progress calculations.
- `app/routes/courses.py`: catalog, course editing, enrollment, chapters, lessons, content items, files, and progress APIs.
- `app/db.py`: increment the schema version and invoke the course migration after the live schema exists.
- `app/main.py`: register the course router and expose only the public application shell as before.
- `app/config.py` and `config.example.toml`: validated private course storage, document upload, and video upload limits.
- `app/static/course-learning.js`: course catalog, course authoring, chapter/lesson editing, and learner workspace.
- `app/static/course-learning.css`: responsive catalog, editor, and study layout.
- `app/static/app.js`, `app/static/index.html`, and `app/static/live.css`: navigation label/module mount and stylesheet cache version.
- `tests/test_course_learning.py`: migration, access, enrollment, lesson ordering, upload, playback, and progress behavior.
- `tests/course-learning.test.mjs`: frontend state/format/ordering behavior that does not require a browser.
- `docs/live-classroom.md` and `README.md`: course authoring, learner flow, private media, config, migration, and deployment instructions.

## Task 1: Add Backward-Compatible Course Tables

**Files:** create `app/services/course_schema.py`; modify `app/db.py`; test in `tests/test_course_learning.py`.

**Interfaces:** `initialize_course_learning(db)` is called after `initialize_live(db)`. It creates `course_sections`, `course_lessons`, `course_lesson_items`, `course_assets`, `course_self_enrollments`, `course_progress`, and `course_playback_tickets`, adds publication/access fields to `live_courses`, and adds nullable `course_lesson_id` to `live_lessons`.

- [ ] Write tests using a temporary SQLite database containing the current live schema and representative course/lesson/material/recording rows. Assert migration creates a default chapter, one live course lesson per existing live lesson, stable live IDs, and remains unchanged after a second run.
- [ ] Write a test that a pre-migration course is published but roster-only and that no member, file path, recording status, or LiveKit identifier is rewritten.
- [ ] Run `pytest tests/test_course_learning.py -q` and confirm the migration tests fail before the migration exists.
- [ ] Implement tables with foreign keys and checks: section and lesson `position >= 0`; item `kind IN ('live','video','document')`; one `live_lesson_id` per course item; progress has a unique `(user_id, lesson_id)` and nonnegative playback seconds.
- [ ] Add `publication_status` (`draft`, `published`, `archived`) and `access_mode` (`public`, `roster`) to `live_courses`. Existing rows receive `published` and `roster` defaults.
- [ ] For each existing `live_lessons` row without `course_lesson_id`, insert a course lesson under a lazily created `既有直播课` section and one live item pointing to the unchanged live lesson ID. Use `INSERT OR IGNORE` plus explicit relation checks so initialization is idempotent.
- [ ] Increment `SCHEMA_VERSION` by one and invoke `initialize_course_learning` after `initialize_live`.
- [ ] Run `pytest tests/test_course_learning.py -q tests/test_live.py -q` and confirm migration and existing live behavior pass.

## Task 2: Implement Course Access and Learning APIs

**Files:** create `app/services/course_learning.py`, `app/routes/courses.py`; modify `app/main.py`; test in `tests/test_course_learning.py`.

**Interfaces:**

```python
def can_access_course(db, course_id: int, user: dict) -> bool: ...
def course_detail(db, course_id: int, user: dict) -> dict: ...
def lesson_detail(db, lesson_id: int, user: dict) -> dict: ...
def course_progress(db, course_id: int, user_id: int) -> dict: ...
```

- [ ] Test that a learner sees their assigned roster courses and self-enrolled public courses, but cannot see another user's roster course or any draft/archived course in public catalog results.
- [ ] Test public self-enrollment is idempotent, adds the learner to the legacy `live_members` table for existing live authorization, and rejects roster-only, draft, archived, and inactive-account cases.
- [ ] Test a self-enrolled learner can leave a public course while the enrollment record/progress stays available as history but course access is revoked; admin-assigned members cannot self-remove.
- [ ] Test only administrators who manage a course can edit course publication/access fields, sections, lessons, item order, and membership. Preserve current `managed_user` restrictions when assigning roster members.
- [ ] Test chapter/lesson/item IDs are scoped to their parent course and submitted positions are normalized to contiguous order inside a transaction.
- [ ] Test learner progress reads only the current user's records and course completion counts completed lessons, not individual content blocks.
- [ ] Implement `GET /api/courses`, `POST /api/courses`, `GET/PATCH/DELETE /api/courses/{cid}`, `POST /api/courses/{cid}/enroll`, `DELETE /api/courses/{cid}/enroll`, `POST /api/courses/{cid}/sections`, `PATCH/DELETE /api/sections/{sid}`, `POST /api/sections/{sid}/lessons`, `PATCH/DELETE /api/course-lessons/{lid}`, and `PUT /api/course-lessons/{lid}/items`.
- [ ] Ensure live-course routes and new course routes both use the same access helper; expose course `sections`, ordered `lessons`, ordered `items`, `course_progress`, and per-item availability without file paths or playback secrets.
- [ ] Include an explicit link to a live session ID in live content items; `GET /api/course-lessons/{lid}` can return the live lesson view only after course access succeeds.
- [ ] Register the router before the existing live router and run `pytest tests/test_course_learning.py tests/test_live.py -q`.

## Task 3: Add Private Video and Document Assets

**Files:** modify `app/config.py`, `config.example.toml`, and `app/routes/courses.py`; test in `tests/test_course_learning.py`.

**Interfaces:** `POST /api/course-lessons/{lid}/assets` accepts multipart field `file` and query/body kind `video|document`; `GET /api/course-assets/{aid}/file` downloads a document; `POST /api/course-assets/{aid}/playback` returns an opaque, short-lived URL; `GET /api/course-playback/{ticket}` serves video bytes and honors HTTP Range.

- [ ] Test allowed documents `.pdf`, `.txt`, `.md`, `.docx`, `.pptx`, `.xlsx`, `.png`, `.jpg`, `.jpeg`; allowed video `.mp4` and `.webm`; reject unsupported extensions, empty uploads, oversized uploads, and an asset belonging to another course.
- [ ] Test a roster nonmember and an unenrolled public-course visitor cannot upload, download, mint a playback ticket, or read an existing ticket; test that an inactive account and expired ticket are rejected.
- [ ] Test range responses with `Range: bytes=2-5` return status 206 and the requested bytes; test a second range and invalid range behavior against Starlette's `FileResponse` implementation.
- [ ] Add `[course_media]` configuration with `directory`, `document_max_mb`, `video_max_mb`, and `playback_seconds`, validate finite bounds, and add matching defaults to `config.example.toml`.
- [ ] Stream uploads in bounded chunks to `course_media/assets` using `secrets.token_hex`; enforce size while reading, chmod private files, remove partial files on failure, then transactionally persist `course_assets` and ordered item relation.
- [ ] Use `course_playback_tickets` for opaque tickets; on every ticket read recheck account enabled state, expiry, course publication/member access, asset existence, and content kind; return private/no-store and nosniff headers.
- [ ] Ensure asset deletion removes the ordered item and metadata first, then deletes the private file and reports cleanup failure without claiming the stored file was removed.
- [ ] Run `pytest tests/test_course_learning.py -q` and retain all previous live upload tests.

## Task 4: Build the Course Catalog and Authoring UI

**Files:** create `app/static/course-learning.js` and `app/static/course-learning.css`; modify `app/static/app.js`, `app/static/index.html`, `app/static/live.css`; test in `tests/course-learning.test.mjs`.

**Interfaces:** `refreshCourses()` renders the catalog for the `courses` route; `clearCourses()` disposes outstanding renders; use the existing app `state`, route, modal, `api`, and private upload helpers. The current live room remains mounted only by `live.js` after a live item is opened.

- [ ] Add node tests for course route parsing, catalog tab filtering, stable section/lesson/item sorting, and format helpers before rendering code.
- [ ] Build the catalog with tabs `我的课程` / `公开课程`, search, clear status labels, and a single primary `创建课程` command for admins. Public cards expose `加入课程`; enrolled cards expose `继续学习`; roster-only courses never appear in public results.
- [ ] Build course editing for title, description, public/roster access, draft/published/archived state, and existing course roster assignment. New public courses are not discoverable until published.
- [ ] Build chapter and lesson management with add, rename, move up/down, and delete controls; item editing adds a live session, uploaded video, or document in a chosen order. Keep mixed content visible as a compact ordered list and provide explicit removal confirmation for uploaded assets.
- [ ] Build responsive course cards and editor using `course-learning.css`, matching current ivory/red/olive palette, compact 8px-or-less framed elements, and existing dialog/accessibility patterns.
- [ ] Change the app navigation label to `课程` while preserving route key `live` to avoid breaking stored hashes; mount course screens for catalog/course/study routes and retain existing `/live/lesson/{id}` deep links.
- [ ] Update CSS cache version tokens in `index.html` and keep unrelated pending training CSS/index changes.
- [ ] Run `node --test tests/course-learning.test.mjs` and run frontend syntax checks for `app/static/course-learning.js`.

## Task 5: Build the Learner Course Workspace and Progress

**Files:** modify `app/static/course-learning.js` and `app/static/course-learning.css`; modify `app/routes/courses.py`; test in `tests/test_course_learning.py` and `tests/course-learning.test.mjs`.

**Interfaces:** `GET /api/course-lessons/{lid}` returns ordered content metadata and the caller's progress; `PUT /api/course-lessons/{lid}/progress` accepts `position_seconds` and `completed` and returns normalized progress; frontend `openCourseLesson(courseId, lessonId)` renders a course learning view.

- [ ] Test progress updates clamp playback position to a nonnegative value, permit only a lesson in an accessible course, and cannot update another user's progress.
- [ ] Test marking a document-only lesson complete and computing course completion across mixed lesson types.
- [ ] Implement document completion and video progress APIs; update on `timeupdate` at a bounded interval, save on `pause`, `ended`, and page exit, and load the saved position before playback starts.
- [ ] Render a stable two-column workspace: chapter/lesson navigation on the left and lesson content on the right. On narrow screens place navigation in a collapsible drawer above content. Keep section labels, completion status, and current lesson visually distinct.
- [ ] Render ordered items in lesson content: document preview/download controls, video player, and a `进入直播课堂` action that navigates to the existing live detail/room. If a live session has a ready Egress recording, show its playback item without copying the MP4.
- [ ] Provide previous/next lesson navigation with stable positions regardless of whether the current lesson has documents, video, or live content; disable unavailable directions without removing controls.
- [ ] Run `pytest tests/test_course_learning.py -q` and `node --test tests/course-learning.test.mjs`.

## Task 6: Link Existing Live Course Operations and Recording Output

**Files:** modify `app/routes/live.py`, `app/services/live.py`, `app/services/course_learning.py`, and `app/static/course-learning.js`; test in `tests/test_course_learning.py` and `tests/test_live.py`.

- [ ] Test existing `POST /api/live/courses/{cid}/lessons` creates a course lesson and live content item with the same `live_lessons.id`; test editing title/order does not change the live room name.
- [ ] Test deleting a course lesson follows the current live deletion guards and removes linked private assets only after database transaction succeeds; live sessions still in progress cannot be deleted.
- [ ] When Egress webhook changes a recording to `ready`, make it available as a playback item for the associated live course lesson; deduplicate by recording ID and never expose a local path.
- [ ] Preserve course detail and lesson endpoints currently consumed by `live.js`; route the new learner UI to the existing live lesson renderer and immersive room to preserve interaction behavior.
- [ ] Test a user removed from the course roster immediately loses course lesson, material, uploaded-video, recording-ticket, and live-session access.
- [ ] Run `pytest tests/test_course_learning.py tests/test_live.py tests/test_live_local.py -q`.

## Task 7: Documentation, Browser Verification, and Final Checks

**Files:** update `docs/live-classroom.md`, `README.md`, and `docs/superpowers/specs/2026-11-18-course-learning-design.md` only if implementation reveals a necessary contract clarification.

- [ ] Document course authoring, publication, public enrollment, roster-only access, section/lesson ordering, video/document upload limits, local private storage, backups, Range playback, and learner progress.
- [ ] Document that current LiveKit/Egress deployment remains necessary only for live rooms and server-side live recordings; uploaded recordings and documents do not require LiveKit.
- [ ] Add exact migration behavior and rollback/backup advice before running the new schema version against production data.
- [ ] Run `.venv/bin/pytest tests/test_course_learning.py tests/test_live.py tests/test_live_local.py -q` and `node --test tests/course-learning.test.mjs`.
- [ ] Start the existing app only if no project server is already running; use an isolated test database and browser profile. Verify admin draft creation, publish, public enrollment, roster isolation, section/item order, video resume, document completion, live-room entry, and mobile layout.
- [ ] Stop only the test server started for this task and verify `git diff --check`; report the exact test commands and any media behavior that cannot be tested without real LiveKit/Egress.
