"""Dashboard data API (doctors, slots, appointments).

The routes live on `router`, so they can be served two ways:
  - by the voice server (backend/voice.py includes this router), so a single
    `python -m backend.voice` process serves both the call and the dashboard;
  - standalone: `uvicorn backend.main:app --port 8000`.
"""
import os
from contextlib import asynccontextmanager
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

load_dotenv()
from backend import store

router = APIRouter(prefix="/api")


@router.get("/health")
def health():
    return {"status": "online", "voice_configured": bool(os.getenv("GOOGLE_API_KEY") and os.getenv("ELEVENLABS_API_KEY"))}


@router.get("/doctors")
def get_doctors():
    return store.doctors_with_slots()


@router.get("/appointments")
def get_appointments():
    return store.appointments()


@router.get("/availability")
def get_availability(doctor: str = "", day: str = ""):
    return store.check_availability(doctor, day)


@asynccontextmanager
async def lifespan(app):
    store.initialize()
    yield


app = FastAPI(title="Careline Clinic API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")], allow_methods=["*"], allow_headers=["*"])
app.include_router(router)
app.mount("/", StaticFiles(directory="frontend/dist", html=True, check_dir=False), name="frontend")
