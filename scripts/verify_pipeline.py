"""Real HTTP integration verification, isolated from the user's database."""
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from run_local import stop

ROOT = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def request(base, path, body=None, token=None, expected=200, extra=None):
    headers = {"Content-Type": "application/json", **(extra or {})}
    if token:
        headers["X-Admin-Token"] = token
    req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as error:
        status, raw = error.code, error.read()
    if status != expected:
        raise AssertionError(f"{path}: expected {expected}, got {status}: {raw.decode()[:1000]}")
    return json.loads(raw)


def wait_ready(base, path, child):
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        if child.poll() is not None:
            raise RuntimeError("Service exited during startup; see output above.")
        try:
            request(base, path)
            return
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            time.sleep(0.3)
    raise RuntimeError("Service did not become ready within 40 seconds.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--browser", action="store_true", help="Also run optional Playwright browser smoke tests")
    args = parser.parse_args()
    report = {"checks": [], "status": "failed"}
    children = []
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not npm:
        raise SystemExit("Node.js/npm is required. Install it and run npm ci in frontend first.")
    try:
        subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=ROOT, check=True)
        report["checks"].append("Python unit and API integration tests")
        subprocess.run([npm, "run", "build"], cwd=ROOT / "frontend", check=True)
        report["checks"].append("Frontend production build")
        with tempfile.TemporaryDirectory(prefix="monetize360-verify-") as temporary:
            api_port, ui_port = free_port(), free_port()
            while ui_port == api_port:
                ui_port = free_port()
            base = f"http://127.0.0.1:{api_port}"
            ui = f"http://127.0.0.1:{ui_port}"
            env = {**os.environ, "DATABASE_URL": "sqlite:///" + (Path(temporary) / "verify.db").as_posix(), "ADMIN_TOKEN": "verify-publisher", "EDITOR_TOKEN": "verify-editor", "GEMINI_API_KEY": "", "API_TARGET": base}
            try:
                children.append(subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.app.main:app", "--port", str(api_port), "--host", "127.0.0.1"], cwd=ROOT, env=env, start_new_session=os.name != "nt"))
                wait_ready(base, "/health", children[-1])
                children.append(subprocess.Popen([npm, "run", "dev", "--", "--port", str(ui_port), "--strictPort"], cwd=ROOT / "frontend", env=env, start_new_session=os.name != "nt"))
                wait_ready(ui, "/api/health", children[-1])
                # Every subsequent API request traverses the actual frontend proxy.
                proxy = ui + "/api"
                for product, expected in [("hospitality_standard", 6480), ("tours_standard", 28000), ("car_rental_standard", 14900), ("rate_demo_standard", 9.25)]:
                    result = request(proxy, "/pricing/calculate", {"product_id": product, "context": {}})
                    assert float(result["final_price"]) == expected, result
                    assert request(proxy, f"/pricing/history/{result['decision_id']}/replay", {})["matches"]
                report["checks"].append("Four domain prices and replay through frontend proxy")
                cfg = request(proxy, "/strategies/car_rental/versions")[0]["config"]
                cfg["id"], cfg["name"] = "verifier_new_domain", "New configured domain"
                request(proxy, "/domains", cfg, expected=403)
                request(proxy, "/domains", cfg, "verify-editor", expected=201)
                prefix = "/strategies/" + cfg["id"]
                request(proxy, prefix + "/approve", {"version": 1}, "verify-publisher")
                request(proxy, prefix + "/publish", {"version": 1}, "verify-publisher")
                request(proxy, "/products", {"id": "verifier_product", "name": "Verifier product", "strategy_id": cfg["id"], "base_rate": "2000", "defaults": {}}, "verify-editor", expected=201)
                result = request(proxy, "/pricing/calculate", {"product_id": "verifier_product", "context": {}})
                assert float(result["final_price"]) == 14900
                request(proxy, prefix + "/versions", cfg, "verify-editor", expected=201)
                request(proxy, prefix + "/approve", {"version": 2}, "verify-publisher")
                request(proxy, prefix + "/publish", {"version": 2}, "verify-publisher")
                request(proxy, prefix + "/publish", {"version": 1}, "verify-publisher")
                report["checks"].append("Configuration-only domain creation, approval, publication and rollback")
                before = request(proxy, "/pricing/history")["total"]
                sim = {"strategy_id": cfg["id"], "version": 1, "scenarios": cfg["scenarios"]}
                assert all(x["passed"] for x in request(proxy, "/pricing/simulate", sim)["results"])
                compare = request(proxy, "/pricing/compare", {**sim, "baseline_version": 1, "disabled_rule_ids": ["weekly_suv"]})
                assert compare["changed_count"] > 0
                assert request(proxy, "/pricing/history")["total"] == before
                report["checks"].append("Simulation isolation and rule counterfactual")
                if args.browser:
                    subprocess.run([shutil.which("node"), "../scripts/browser_smoke.cjs", ui], cwd=ROOT / "frontend", check=True)
                    report["checks"].append("Browser renders dashboard, calculates and replays a real API decision")
                report["status"] = "passed"
            finally:
                for child in reversed(children):
                    stop(child)
                children.clear()
    except Exception as error:
        report["error"] = str(error)
        raise
    finally:
        for child in reversed(children):
            stop(child)
        (ROOT / "verification-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
