"""Start both services without requiring a virtual environment."""
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def stop(process):
    if process.poll() is None:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
        else:
            os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def main():
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not npm or not (ROOT / "frontend/node_modules/vite").exists():
        raise SystemExit("Install Node.js, then run: cd frontend && npm ci")
    if not (ROOT / ".env").exists():
        shutil.copyfile(ROOT / ".env.example", ROOT / ".env")
    children = []
    try:
        children.append(subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", "8000"], cwd=ROOT, start_new_session=os.name != "nt"))
        children.append(subprocess.Popen([npm, "run", "dev", "--", "--port", "5173", "--strictPort"], cwd=ROOT / "frontend", start_new_session=os.name != "nt"))
        print("Website: http://127.0.0.1:5173\nAPI docs: http://127.0.0.1:8000/docs\nCtrl+C stops both services.", flush=True)
        while all(p.poll() is None for p in children):
            try:
                children[0].wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                continue
        raise SystemExit("A service stopped. Read its error above; check dependencies and ports 8000/5173.")
    except KeyboardInterrupt:
        print("Stopping services.")
    finally:
        for child in reversed(children):
            stop(child)


if __name__ == "__main__":
    main()
