"""Start the whole app with one command: python run.py

Runs both processes the demo needs and stops them together on Ctrl+C:
  - Voice      http://localhost:7860   (Pipecat voice agent + the dashboard's /api data)
  - Dashboard  http://localhost:5173   (Vite dev server)
"""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = sys.executable
NPM = shutil.which("npm") or "npm"

SERVICES = [
    ("voice", [PY, "-m", "backend.voice", "-t", "webrtc", "--port", "7860"], ROOT),
    ("dashboard", [NPM, "run", "dev"], ROOT / "frontend"),
]


def main():
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    procs = []
    for name, cmd, cwd in SERVICES:
        print(f"[run] starting {name}: {' '.join(map(str, cmd))}")
        procs.append((name, subprocess.Popen(cmd, cwd=cwd, env=env)))
    print("[run] open http://localhost:5173 once the voice server prints 'Uvicorn running'. Ctrl+C stops everything.")
    try:
        while True:
            for name, p in procs:
                if p.poll() is not None:
                    print(f"[run] {name} exited with code {p.returncode}; stopping the rest.")
                    return
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[run] stopping...")
    finally:
        for _, p in procs:
            if p.poll() is None:
                p.terminate()
        for _, p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()


if __name__ == "__main__":
    main()
