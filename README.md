# Space Debris Tracking Dashboard

A FastAPI application that retrieves recent orbital element data from CelesTrak, propagates satellite positions with SGP4, and identifies potential conjunctions during the next hour. It includes a browser dashboard for running an analysis and reviewing events by risk level.

## Requirements

- Python 3.10 or newer
- An internet connection for retrieving data from CelesTrak

## Setup

Open a terminal in the project directory and create a virtual environment:

### Windows PowerShell

```powershell
py -m venv .venv
.venv\Scripts\Activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### macOS or Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Run the application

With the virtual environment activated, start the FastAPI development server from the project directory:

```bash
uvicorn main:app --reload
```

Then open the dashboard at [http://127.0.0.1:8000/dashboard](http://127.0.0.1:8000/dashboard).

Choose how many objects to scan and how far into the future to search with the dashboard sliders, then press **Refresh Analysis**. The analysis may take a short while because the application compares many object pairs.

## API endpoints

- `GET /` — API health message
- `GET /status` — service status and cached-result counts
- `GET /conjunctions` — cached conjunction results
- `POST /refresh` — fetch current orbital data and run a new analysis
- `GET /dashboard` — browser dashboard

Interactive API documentation is available at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) while the server is running.

## Notes

- Analysis results are cached in memory and are cleared when the server restarts.
- The dashboard can analyze 20–200 recently added objects over a 1–24 hour window.
- CelesTrak availability is required when starting a new analysis.
