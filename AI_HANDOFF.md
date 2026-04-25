# AI Handoff

## Project Summary

- Repo: `C:\Users\Lux\SheetGenerator`
- Product: desktop-first piano sight-reading generator
- Primary frontend: `desktop/` (Vite + React + TypeScript)
- Secondary frontend: `mobile/` (Expo React Native, still in repo but not the release driver)
- Backend: `backend/` (FastAPI generator service)
- Shared frontend domain logic: `frontend-shared/`
- Shared static contracts/options: `shared/`

The product direction is explicitly desktop-first. Mobile remains in the repo, but release decisions should favor the browser/desktop experience.

## Deployment Status

- Frontend is deployed on Vercel.
  - Root Vercel project metadata: `.vercel/project.json`
  - Root Vercel build config: `vercel.json`
  - Desktop SPA rewrite config: `desktop/vercel.json`
- Backend is deployed on Render.
  - Live backend URL: `https://sheetmusicgenerator.onrender.com`
- Desktop frontend expects:
  - `VITE_API_BASE_URL`
  - local example: `desktop/.env.example`

## Current Release Shape

- Desktop/browser release comes first.
- No login, no sync, no classroom features.
- Backend generation stays remote.
- Desktop persists presets, exercises, sessions, and settings locally.

## Repo Structure

- `desktop/`
  - current primary UI
  - Vite React app
  - browser-first renderer intended to be wrappable by Tauri later
- `mobile/`
  - older mobile-oriented Expo app
  - still useful as reference, but should not drive architecture decisions
- `backend/`
  - generator logic
  - FastAPI app entrypoint
  - music generation, scoring, MusicXML, SVG, audio
- `frontend-shared/`
  - framework-neutral frontend domain/types/helpers used by both apps
- `shared/`
  - JSON options/contracts consumed by frontends

## Backend Files That Matter Most

- `backend/app/main.py`
  - FastAPI app and API routes
- `backend/app/models.py`
  - request/response models
- `backend/app/generator/_entry.py`
  - top-level `build_exercise` entry
- `backend/app/generator/_builder.py`
  - constructs piano candidates
- `backend/app/generator/_planning.py`
  - phrase plans, top-line plans, bass plans, role/register targets
- `backend/app/generator/_harmony.py`
  - harmonic progression/cadence banks
- `backend/app/generator/_texture.py`
  - melodic realization and target-pitch alignment
- `backend/app/generator/_pitch.py`
  - pitch pools and hand-position range logic
- `backend/app/generator/_scoring.py`
  - evaluation, quality gates, visible-motion checks, validation
- `backend/app/generator/_engraving.py`
  - MusicXML generation / SVG rendering

## Recent Backend History

Latest commits:

- `24eb5c5` `Add backend predeploy regression gate`
- `4ae8692` `Bias beginner openings away from tonic center`
- `f7c9a52` `Broaden low-grade position range`
- `b713cd2` `Tighten low-grade motion selection`
- `0dce069` `Improve phrase contour and bass movement`

What those changes were trying to fix:

- beginner outputs felt too static
- RH often stayed too central in treble
- LH needed to dip below the fixed center more often
- openings became too repetitive
- a later regression made openings over-bias toward `A`

Current state after the latest fix:

- beginner outputs should no longer collapse to "always A"
- openings should vary more while still not defaulting to strict tonic-centered starts
- backend now has a predeploy regression gate to catch this class of issue before pushing

## New Regression Gate

Added files:

- `backend/tests/test_generator_regressions.py`
- `backend/scripts/predeploy_backend_checks.ps1`

Purpose:

- prevent grade-1 opener regressions
- catch cases where openings collapse onto one pitch too often
- verify lower-grade RH/LH range behavior on fixed seed batches

Run before backend deploys:

```powershell
cd C:\Users\Lux\SheetGenerator
powershell -ExecutionPolicy Bypass -File .\backend\scripts\predeploy_backend_checks.ps1
```

Equivalent manual steps:

```powershell
cd C:\Users\Lux\SheetGenerator
python -m compileall backend/app
python -m unittest backend.tests.test_generator_regressions
```

## What Was Verified Recently

Recent deploy flow that passed:

1. local predeploy script passed
2. backend changes were committed and pushed to `master`
3. Render was polled until live output matched local output for fixed seeds
4. live opener sanity sample confirmed openings were no longer dominated by one pitch

## Important Product Constraints

- Desktop-first decisions win over mobile-first habits.
- Do not reintroduce mobile-tab assumptions into desktop UX.
- Keep backend contract stable unless there is a strong reason:
  - `GET /v1/health`
  - `POST /v1/exercises/generate`
- Keep browser/Tauri compatibility in mind:
  - no SSR dependency required for the desktop app
  - env-driven API base URL
  - standard web storage/fetch boundaries

## Current Risk Areas

- beginner music generation still needs musical taste checks, not just type/build checks
- seeded regression coverage is better now, but still narrow compared with full musical possibility space
- frontend/backend verification is still mostly backend-heavy; browser-level regression coverage is lighter
- mobile still exists and can confuse future refactors if someone assumes it is the primary app

## Recommended Starting Point For Another AI

If continuing work, start with:

1. read this file
2. read `README.md`
3. read `backend/README.md`
4. inspect latest backend commits with `git log --oneline -5`
5. if touching generator behavior, run:
   - `powershell -ExecutionPolicy Bypass -File .\backend\scripts\predeploy_backend_checks.ps1`

If the task is about musical output quality, inspect in this order:

1. `backend/app/generator/_planning.py`
2. `backend/app/generator/_harmony.py`
3. `backend/app/generator/_texture.py`
4. `backend/app/generator/_pitch.py`
5. `backend/app/generator/_scoring.py`

If the task is about deployment/config:

1. `vercel.json`
2. `desktop/.env.example`
3. `.vercel/project.json`
4. `backend/app/main.py`

## Good Handoff Prompt Seed

You are taking over `C:\Users\Lux\SheetGenerator`, a desktop-first piano sight-reading generator. Read `AI_HANDOFF.md`, `README.md`, and `backend/README.md` first. Treat `desktop/` as the main release surface, `mobile/` as secondary, and `backend/` as the remote FastAPI generator. Before deploying any backend generator changes, run `powershell -ExecutionPolicy Bypass -File .\backend\scripts\predeploy_backend_checks.ps1`. Be especially careful with beginner-output regressions involving RH opening-note variety, treble range, bass range, and repetitive phrase shapes.
