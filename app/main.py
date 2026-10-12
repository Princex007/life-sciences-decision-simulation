"""FastAPI application factory."""
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from app.api.routes import router

app = FastAPI(title="Life Sciences Decision Simulation Engine", version="0.1.0")
app.include_router(router)
_static = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=_static), name="static")

@app.get("/", include_in_schema=False)
def simulation_builder_ui():
    return FileResponse(_static / "index.html")
