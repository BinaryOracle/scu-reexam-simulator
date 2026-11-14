# 每日训练 Implementation Plan

> **For agentic workers:** Use subagent-driven-development for isolated source extraction and UI tasks; the controller integrates and verifies. Steps use checkbox syntax.

**Goal:** Deliver card practice with random/sequential modes, reference answers, favorites, private submissions, moderation and streak-based interview credits.

**Architecture:** Independent SQLite training catalog and service/routes; existing authentication and credit ledger are reused. JSON is the portable seed/import format. Frontend uses existing plain ES modules and DOM helpers.

**Tech Stack:** FastAPI, SQLite, Pydantic, PyMuPDF, vanilla JavaScript/CSS.

## Global Constraints

- Work in `/Users/zhandaohong/PycharmProjects/scu-reexam-simulator`; preserve existing changes and credentials.
- Default daily goal is 5 distinct questions; Shanghai calendar date; day7 adds1, day14 adds2, day21 adds3; break resets streak.
- Random and sequential modes support all accessible questions and favorites; per-round duplicates forbidden.
- Private questions stay owner-only until explicit approval; pending edits require version checks.
- Oral cards have no example answers. No new AI/ASR/TTS calls.
- Keep administrator internal numeric allowance hidden.
- Use existing warm ivory/vermilion UI and site dialogs. Do not commit unrelated files or modify live database until migration verification and backup.

### Task 1: Source answer catalog

**Files:** `scripts/extract_training_bank.py`, `app/assets/training/catalog.json`, `app/assets/training/images/`, `tests/test_training_assets.py`.
**Interfaces:** Seed list items `{source_key,collection_id,position,question,answer,source,images}`; `source` has `file,page_start,page_end,number`, images are relative filenames under training assets. Collections `data_structures,operating_systems,computer_networks,translation,oral`.
- [x] Extract exact existing question order, text answers and clipped diagrams from the three uploaded PDFs; pair31 English paragraphs with Chinese source translations; preserve53 oral questions without answers.
- [x] Enforce96+31+53 counts, nonempty reference answers and unique source keys in a focused asset test. Run `.venv/bin/python -m pytest tests/test_training_assets.py -q`.
- [x] Write mapping audit report including fuzzy matches and image/page checks.

### Task 2: Transactional training backend

**Files:** `app/services/training_schema.py`, `app/services/training.py`, `app/services/training_catalog.py`, `app/routes/training.py`, `app/config.py`, `config.example.toml`, `app/db.py`, `app/main.py`, `tests/test_training.py`.
**Interfaces:** See `docs/superpowers/plans/training-api.md` for JSON request/response names shared with frontend.
- [x] Add schema16 with cascading private account data, anonymized public contributions, unique daily events and monotonic question IDs. Idempotently seed only source keys absent from DB.
- [x] Implement catalog authorization, favorites, private/manual/batch creation, versioned moderation, official maintenance.
- [x] Implement random/no-repeat and stable sequential position cursors, idempotent completion, saved round progress.
- [x] Implement day-goal snapshots, distinct completed counts and atomic checkin/reward/credit ledger update using BEGIN IMMEDIATE.
- [x] Run focused API tests for visibility, approval versions, sequential resume,7/14/21 rewards, concurrency and deletion cleanup.

### Task 3: Training and management UI

**Files:** `app/static/training.js`, `app/static/training-admin.js`, `app/static/training.css`, shell integration in `app/static/app.js` and `index.html`.
**Interfaces:** `refreshTraining`, `clearTraining`, `refreshTrainingAdmin`; existing `api`, `state`, `el`, `button`, `confirmAction` helpers.
- [x] Build homepage goal/streak, filters and modes, card/reference answer/favorite completion, progress recovery, private questions and import preview.
- [x] Build admin catalog editor and moderation/reward/settings views; respect account hierarchy and keep passwords/quotas private.
- [x] Integrate shell nav, logout state invalidation, responsive styling and module cache version. Run Node module syntax checks.

### Task 4: Integration and review

**Files:** `README.md`, `docs/daily-training.md`, focused test files and screenshots.
- [x] Run full Python regression once after focused checks pass, then JS syntax and diff whitespace checks.
- [x] Review access control, transaction idempotence, sequential cursor behavior and source audit; fix concrete findings.
- [x] Browser-check desktop and mobile using isolated DB: practice5, reveal answer, favorite, sequential resume, submission approve, checkin and reward UI.
- [x] Back up live DB+paired encryption key; migrate and restart port8000, verify authenticated training and existing pages without creating fake live rewards.

### Additional requirement: Interview-credit transfers

- [x] Add schema17 receipts, exact-username lookup, positive integer quantities, normal-account validation and balance checks.
- [x] Commit debit, credit and both ledger entries atomically; preserve a stable idempotency key on retries.
- [x] Add profile form, site confirmation dialog and private paginated incoming/outgoing records.
- [x] Verify concurrent retries, insufficient funds, rollback, hierarchy and receipt survival after account deletion.
