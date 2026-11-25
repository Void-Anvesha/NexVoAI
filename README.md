# Careline — voice appointment desk

A browser dashboard and Pipecat voice agent for checking clinic availability, booking and cancelling appointments. Clinic data is stored in SQLite and seeded with demo doctors and slots.

## Run locally

1. Install Python 3.11+ and Node 20+.
2. Copy `.env.example` to `.env` and add `GOOGLE_API_KEY` and `ELEVENLABS_API_KEY` (ElevenLabs also needs a voice ID; the default is configured below).
3. In one terminal: `python -m venv venv`, activate it, `pip install -r requirements.txt`.
4. `cd frontend`, `npm install`, `cd ..` (first time only).
5. Start everything with one command: `python run.py`, then open http://localhost:5173. Ctrl+C stops it all.

   Or run the two parts yourself: `python -m backend.voice -t webrtc --port 7860` (voice agent, and it also serves the dashboard API under `/api`) and `npm run dev` in `frontend`. A standalone API is still available with `uvicorn backend.main:app --port 8000` plus `VITE_API_URL=http://localhost:8000`.

The dashboard data API works without keys. Live voice needs the API keys and an available microphone. The voice service uses Pipecat with ElevenLabs streaming STT/TTS, Google Gemini (`gemini-3.5-flash-lite` by default, override with `GOOGLE_MODEL`) function calling, Silero VAD, and SmallWebRTC. See `backend/voice.py` for the pipeline. Set `VITE_VOICE_URL` / `VITE_API_URL` if the servers are not on localhost:7860.

## Pipeline

Browser microphone audio travels over WebRTC into a Pipecat pipeline. Silero detects turns, ElevenLabs transcribes speech, Gemini streams a response and calls clinic tools when needed, and ElevenLabs speaks the reply back. The tool layer validates the caller's spoken phone number, reads it back for confirmation before booking or cancellation, and updates SQLite. The dashboard reads the same API so changes appear immediately.

## Demo data and privacy

All patient/doctor data is fictional and local. No authentication or caller ID is used; the caller supplies the phone number verbally. Do not use this demo for real patient information.

## Submission checklist

- Repository: this project
- Recording: record one browser booking flow (phone number → availability → confirmation → booking) with the dashboard visible.
- Pipeline description: use the paragraph above as a short starting point and adjust it to reflect your own understanding.
