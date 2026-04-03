# SheetGenerator Backend

This is a small stateless FastAPI service for on-demand piano sight-reading generation.

## Endpoints

- `GET /v1/health`
- `POST /v1/exercises/generate`

## Setup

```powershell
cd C:\Users\Lux\SheetGenerator\backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

If `verovio` fails to install, first upgrade pip and retry:

```powershell
python -m pip install --upgrade pip
pip install verovio==6.0.1
pip install -r requirements.txt
```

If pip still tries to build Verovio from source on your local Python version, use Python 3.12 or 3.13 for the backend virtual environment.

## Notes

- `music21` generates grand-staff MusicXML for piano and anchored rhythm exercises.
- `verovio` renders SVG when available.
- If Verovio is unavailable, the API still returns a placeholder SVG so the mobile app can continue working.
- Audio preview is returned as a generated WAV data URI with both hands mixed together.
- Repeated requests with the same config + seed are cached under `backend/cache/`.
