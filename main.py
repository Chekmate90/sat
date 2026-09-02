from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from engine import find_conjunctions
from fastapi.staticfiles import StaticFiles
from threading import Lock

app = FastAPI()

app.mount(
    "/static",
    StaticFiles(directory="frontend"),
    name="static"
)

latest_results = []
latest_orbit_paths = []
objects_tracked = 0
cache_lock = Lock()
refresh_lock = Lock()


@app.get("/")
def home():
    return {
        "message": "Space Debris Tracking API is running"
    }


@app.get("/status")
def status():
    with cache_lock:
        return {
            "status": "online",
            "analysis_running": refresh_lock.locked(),
            "conjunctions_cached": len(latest_results),
            "objects_tracked": objects_tracked
        }


@app.get("/conjunctions")
def conjunctions():
    with cache_lock:
        return {
            "objects_tracked": objects_tracked,
            "conjunctions": latest_results
        }


@app.post("/refresh")
def refresh(
    objects_scanned: int = Query(500, ge=20, le=500),
    future_hours: int = Query(24, ge=1, le=24),
):

    global latest_results
    global latest_orbit_paths
    global objects_tracked

    if not refresh_lock.acquire(blocking=False):
        raise HTTPException(
            status_code=409,
            detail="A conjunction analysis is already running."
        )

    try:
        result = find_conjunctions(
            object_limit=objects_scanned,
            scan_minutes=future_hours * 60,
        )

        # CelesTrak request failed
        if result is None:
            raise HTTPException(
                status_code=503,
                detail="Unable to retrieve satellite data from CelesTrak or from local data file(sample_data_feb142026.json). Please try again."
            )

        with cache_lock:
            latest_results = result["conjunctions"]
            objects_tracked = result["objects_tracked"]
            latest_orbit_paths = result["orbit_paths"]
    finally:
        refresh_lock.release()

    return {
        "message": "Conjunction analysis completed",
        "objects_tracked": result["objects_tracked"],
        "future_hours": future_hours,
        "events_found": len(result["conjunctions"])
    }


@app.get("/orbits")
def orbits():
    with cache_lock:
        return {
            "orbit_paths": latest_orbit_paths
        }

@app.get("/dashboard")
def dashboard():
    return FileResponse("frontend/index.html")
