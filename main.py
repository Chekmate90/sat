from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from engine import find_conjunctions
from fastapi.staticfiles import StaticFiles

app = FastAPI()

app.mount(
    "/static",
    StaticFiles(directory="frontend"),
    name="static"
)

latest_results = []
objects_tracked = 0


@app.get("/")
def home():
    return {
        "message": "Space Debris Tracking API is running"
    }


@app.get("/status")
def status():
    return {
        "status": "online",
        "conjunctions_cached": len(latest_results),
        "objects_tracked": objects_tracked
    }


@app.get("/conjunctions")
def conjunctions():
    return {
        "objects_tracked": objects_tracked,
        "conjunctions": latest_results
    }


@app.post("/refresh")
def refresh():

    global latest_results
    global objects_tracked

    result = find_conjunctions()

    # CelesTrak request failed
    if result is None:
        raise HTTPException(
            status_code=503,
            detail="Unable to retrieve satellite data from CelesTrak. Please try again."
        )

    latest_results = result["conjunctions"]
    objects_tracked = result["objects_tracked"]

    return {
        "message": "Conjunction analysis completed",
        "objects_tracked": objects_tracked,
        "events_found": len(latest_results)
    }


@app.get("/dashboard")
def dashboard():
    return FileResponse("frontend/index.html")