# SheetGenerator

SheetGenerator is a desktop-first sight-reading generator for self-learners.

This MVP is intentionally narrow:

- grand-staff piano reading exercises
- grand-staff piano rhythm exercises with fixed anchor notes
- local-first presets, generated sheets, and practice history
- no login, no sync, no teacher tools, no classroom workflows

The desktop browser app is now the primary release surface. The existing Expo app remains in the repo, but it is no longer the driver for product structure.

## Workspace layout

- `desktop/`
  - Vite React + TypeScript browser app
  - desktop shell for Home, Create, Library, Settings, and Exercise routes
  - IndexedDB persistence with full local history
- `mobile/`
  - Expo React Native app
  - local SQLite persistence
  - tabs: Home, Create, Library
- `backend/`
  - FastAPI generator service
  - music21 MusicXML generation
  - Verovio SVG rendering when available
  - local generated cache artifacts under `backend/cache/` (`.gitkeep` only in Git)
- `frontend-shared/`
  - framework-neutral frontend types, option loading, preset rotation logic, and formatting helpers
- `shared/`
  - shared option and stage JSON contracts

Both frontend apps consume the root shared JSON contracts and the shared TypeScript domain layer.
`mobile/metro.config.js` is configured to watch the parent folder so Expo can import those root modules.

## Desktop app

Requirements:

- Node 20+ recommended
- npm 10+ recommended

Start the desktop app:

```powershell
cd C:\Users\Lux\SheetGenerator\desktop
npm install
npm run typecheck
npm run build
npm run dev
```

Environment:

- `VITE_API_BASE_URL`
  - defaults to `http://127.0.0.1:8000`
  - copy `desktop/.env.example` to `desktop/.env.local` and update if needed

Desktop persistence:

- IndexedDB in the browser
- keeps full local history for presets, generated exercises, practice sessions, and settings
- designed behind a storage adapter so the browser renderer can later be wrapped by Tauri without changing page logic

## Mobile app

Requirements:

- Node 20+ recommended
- npm 10+ recommended

Start the app:

```powershell
cd C:\Users\Lux\SheetGenerator\mobile
npm install
npm run typecheck
npx expo start
```

If you are testing on a physical device, set the backend base URL first:

```powershell
$env:EXPO_PUBLIC_API_BASE='http://YOUR-LAN-IP:8000'
npx expo start
```

Default fallback API base:

- Android emulator: `http://10.0.2.2:8000`
- iOS simulator / web on same machine: `http://127.0.0.1:8000`

The mobile app now reuses the same shared frontend domain layer as desktop for types, options, formatting, and preset rotation behavior.

## Backend API

Requirements:

- Python 3.11+
- pip

Start the backend:

```powershell
cd C:\Users\Lux\SheetGenerator\backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

If `verovio` fails to install, run:

```powershell
python -m pip install --upgrade pip
pip install verovio==6.0.1
pip install -r requirements.txt
```

If that still fails locally, use Python 3.12 or 3.13 for the backend venv.

Health check:

- `GET http://127.0.0.1:8000/v1/health`

Generation endpoint:

- `POST http://127.0.0.1:8000/v1/exercises/generate`

## What the MVP stores locally

Desktop browser stores:

- `settings`
- `exercises`
- `presets`
- `sessions`

Mobile app SQLite tables:

- `presets`
- `generated_exercises`
- `practice_sessions`
- `app_settings`

## Current feature surface

- Home
  - quick start piano reading / piano rhythm
  - resume last setup
  - recent practice
  - recent sheets
- Create
  - configurable piano / rhythm generation
  - ABRSM-aligned Stage 1-5 presets
- Exercise
  - grand-staff notation preview
  - audio preview
  - count-in and pulse support
  - save preset
  - self-rated session completion
- Library
  - presets
  - recent sheets
  - recent sessions
- Settings
  - notation scale
  - metronome default
  - count-in default
  - preferred hand position
  - default stage

## Intentional v1 exclusions

- multiple voices or ensemble parts
- classroom or teacher workflows
- pitch/timing grading
- recording analysis
- cloud accounts / sync
- export/share features beyond local use
