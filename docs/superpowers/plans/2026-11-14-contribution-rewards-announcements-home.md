# 题库奖励、公告与备考首页 Implementation Plan

> **For agentic workers:** Execute this plan task by task in this session. Keep all existing user changes. Steps use checkbox syntax for tracking.

**Goal:** Add approval-based interview-credit rewards for question contributions, image-capable announcement management, a published default guidance announcement, and a categorized exam-preparation home page based on the uploaded whitepaper.

**Architecture:** Extend the existing SQLite schema and service layer. Award credits atomically from question moderation using a versioned reward policy and the existing credit ledger. Store announcement records/content blocks in SQLite and validated image assets under the configured upload directory. Render the authenticated home page from a versioned JSON resource catalog and published announcements.

**Tech Stack:** FastAPI, SQLite, Pydantic, vanilla JavaScript ES modules, HTML/CSS, pytest and Node tests.

## Global Constraints

- Preserve all pre-existing worktree modifications; do not reset or checkout files.
- Count only ordinary users' question contributions after administrator approval and publication.
- Initial policy is five approved questions for one interview credit; policy edits apply only to later approvals.
- Question approval, contribution progress, reward grants, and credit ledger updates must commit or roll back together.
- Announcement content uses typed blocks; do not render arbitrary HTML.
- The authenticated home page is the default view; retain existing navigation and mobile behavior.
- Use the provided image as the initial announcement cover and seed the default announcement idempotently.

## File Map

- Modify `app/db.py` and `app/services/training_schema.py` for new schema and idempotent initial content.
- Create `app/services/contribution_rewards.py` for policy, progress, grant, and history operations.
- Modify `app/services/training_catalog.py` and `app/routes/training.py` to apply and expose contribution rewards.
- Create `app/services/announcements.py` and `app/routes/announcements.py` for content, lifecycle, and image persistence.
- Modify `app/main.py` to mount routes and serve the provided announcement image safely.
- Create `app/assets/home-resources-v1.json` and `app/static/home.js`; modify `app/static/index.html`, `app/static/app.js`, and `app/static/style.css` for home and announcement UI.
- Modify `app/static/admin.js` and `app/static/index.html` for reward settings and announcement management.
- Modify `app/static/credits.js` and `app/static/index.html` to expose users' contribution progress and announcement entry points.
- Add focused behavior tests in `tests/test_system.py` or new `tests/test_contribution_rewards.py`, `tests/test_announcements.py`, plus frontend module tests where applicable.
- Update README and implementation docs for administrator workflows, defaults, and deployment image storage.

## Task 1: Contribution Reward Domain and Atomic Moderation

- [ ] Add tests for n-1/n/2n reward boundaries, non-user submissions, repeated approval, rule version changes, and transaction rollback.
- [ ] Add versioned reward policy, approved-contribution records, and unique threshold grant records with foreign keys and indexes.
- [ ] Implement policy validation, per-user progress, threshold calculation, and `credits.adjust` integration.
- [ ] Call reward application from the existing approval transaction after checking owner identity and ordinary-user status.
- [ ] Add authenticated user progress/history endpoint and administrator policy/progress endpoint.
- [ ] Add admin forms for n/m and user profile contribution progress/history.
- [ ] Run the focused reward and moderation tests.

## Task 2: Announcement Storage, Lifecycle, Images, and Default Notice

- [ ] Add tests for draft/published/withdrawn visibility, administrator permissions, block validation, unsafe URLs, image validation, and idempotent seeding.
- [ ] Add announcement and attachment tables with status, actor, timestamp, ordered content, and generated asset identifiers.
- [ ] Implement typed blocks for paragraphs, headings, images, and links; accept only HTTP/HTTPS external URLs.
- [ ] Implement administrator CRUD, preview data, publish/unpublish actions, search, and public published-only list/detail APIs.
- [ ] Implement bounded image upload that verifies content format, stores generated names, and serves only associated attachments.
- [ ] Copy the user-provided image into application-owned public assets and seed one published guidance notice once, with current rules for training check-ins, contribution rewards, shop purchase/redeem, and credit transfer.
- [ ] Run the focused announcement and route tests.

## Task 3: Whitepaper-Inspired Home and Announcement Presentation

- [ ] Create a versioned resource catalog grouped into preparation roadmap, fundamentals and AI, written/computer exams, interview preparation, and mentors/courses; retain star priorities and source URLs from the PDF.
- [ ] Exclude the whitepaper's explicitly retired interview server URL and do not fabricate destinations for unlinked resource titles.
- [ ] Add a default authenticated home view, three primary action links, a stage roadmap, resource sections, and responsive announcement ticker/detail dialog.
- [ ] Preserve current training/interview/contest/profile routes and ensure all links have valid local targets or labeled external targets.
- [ ] Add frontend tests for catalog parsing and route rendering; inspect responsive browser layouts at desktop and mobile sizes.
- [ ] Run JavaScript module tests and browser smoke tests.

## Task 4: Admin UX, Documentation, and Integrated Verification

- [ ] Add announcement management UI for list/search, create/edit, block ordering, image upload, preview, publish, and unpublish.
- [ ] Add reward policy/progress UI and user-visible reward history.
- [ ] Update README and implementation docs with reward policy semantics, announcement management, default notice, and uploaded asset persistence.
- [ ] Run focused tests for rewards, announcements, static routes, and existing training/interview credits.
- [ ] Run the existing project test suite and a local server smoke check; report any dependency or environment limits.
