# Monetize360 V2

**One pricing brain, multiple industries, configuration instead of redevelopment.**

A complete-source hackathon prototype: React/Vite/Tailwind UI → real FastAPI routes → deterministic Decimal pricing evaluator → SQLAlchemy persistence. SQLite makes local setup simple; Docker Compose uses PostgreSQL. No mocked API responses or domain-specific branches in the evaluator.

## Verification status — read first

Verified in the build environment: **36 engine tests passed**, including **11 seeded expected-price scenarios**, and the **frontend production build passed**. Python source compilation also passed. FastAPI integration, browser smoke, PostgreSQL/Docker, and the optional Gemini call were **not executed here**: required Python dependency downloads were blocked by the environment. Included integration tests and the verifier below must pass on your computer before calling this fully end-to-end tested. This is a prototype, not production-certified software.

## Windows: install and start without a virtual environment

Use Python 3.11 or 3.12 and Node.js 22. Extract this ZIP separately from your old project, for example to `D:\monetize360-v2`. Open PowerShell **in the folder containing requirements.txt**:

```powershell
cd D:\monetize360-v2
python --version
node --version
python -m pip install -r requirements.txt
Copy-Item .env.example .env
cd frontend
npm.cmd ci
cd ..
python scripts/run_local.py
```

If `.env` already exists, keep it instead of copying over it. `run_local.py` also creates it when absent. No virtual environment is required. Packages install into your selected Python environment and can conflict with other projects; use Python 3.11/3.12 consistently. If Windows only recognizes `py`, replace `python` with `py -3.11` throughout.

Open **http://127.0.0.1:5173**. Swagger API explorer: **http://127.0.0.1:8000/docs**. Leave the terminal open; Ctrl+C stops both services.

Manual two-terminal alternative, both starting in project root:

```powershell
# Terminal 1
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

```powershell
# Terminal 2
cd frontend
npm.cmd run dev -- --port 5173 --strictPort
```

Linux/macOS: use `python3`, `npm` and `cp .env.example .env` for the same sequence.

## How to use the website

1. **Overview:** see the four seeded policies and actual usage counts. Empty history starts at zero, not invented sales.
2. **Pricing studio:** choose Car rental, leave default context, click Calculate price. Expected amount: **₹14,900**. Inspect applied/skipped rules, conditions, bounds and rounding in the trace.
3. **Workspace access:** expand at the top; enter `monetize360-publisher` and click Connect access. This is a local demo credential from `.env`; change it before sharing. `monetize360-editor` can edit, but not approve/publish.
4. **Strategy studio:** select a strategy. Inspect Attributes, Base formula, Rules, Constraints and Tests. Change rules visually. Validate & test, then Save draft version. Update expected tests intentionally if business policy changes. Saving never mutates an earlier version.
5. **Simulation lab:** compare candidate vs baseline on the same scenarios, or disable a rule to see its counterfactual price impact. Simulations do not become transaction history.
6. **Publish:** in Strategy studio select your saved draft, Approve version, then Publish version. Future calculations use it. To roll back, select an earlier published version and Activate / rollback.
7. **New industry:** Clone as new domain; change identity, typed attributes, formulas, rules and scenarios. Save, approve, publish. In Products create a product assigned to that strategy with its base rate/defaults. It now appears in Pricing studio without frontend/backend changes.
8. **Decision history:** Replay a decision. Replay uses its original timestamp, configuration version and product snapshot, even after a product or active strategy changes.

Seed defaults:

| Policy | Example | Expected output |
|---|---|---:|
| Hospitality | 2 nights, 90% occupancy, member | ₹6,480 |
| Tours | 10 people, premium package | ₹28,000 |
| Car rental | 8 days, SUV, airport pickup | ₹14,900 |
| Illustrative rate | Low risk, standard tenure | 9.25% |

These are invented **business-policy test fixtures**, not market observations, forecasts, or financial advice.

## Dataset and AI: what actually exists

V2 does **not** train an ML model, use a GPU, or claim a learned optimal price. The official brief makes AI optional. This build prioritizes configurable rules, lifecycle, explainability and new-domain onboarding. `configs/*.yaml` contains 11 labelled policy scenarios; it is not an ML dataset.

Optional Gemini assistance translates natural-language instructions into a proposed typed strategy. Put your own key in `GEMINI_API_KEY` in `.env` and restart. In Strategy studio → AI assistant, request a draft, review it, load it, validate, then save/approve/publish normally. No key means a clear unavailable error—not a fake response. The provider receives the instruction and current configuration; do not include sensitive information. Provider billing/model availability are your responsibility. No live provider call was tested here.

A future demand model can supply a validated context attribute (e.g. forecast_demand). It would need historical price/exposure/conversion data and evaluation; it must not learn labels generated by these rules and call that independent intelligence.

## Test the complete pipeline

After installing dependencies, from project root:

```powershell
python -m pytest -q
python scripts/verify_pipeline.py
```

The verifier runs Python tests and a frontend build, starts an isolated temporary SQLite backend and Vite on free ports, then sends real HTTP requests through the frontend proxy. It checks four domains, new-domain onboarding, approval, publication, rollback, simulations, counterfactual comparison and replay. Your normal database is not modified. It exits nonzero on failure and writes `verification-report.json` with actual results.

Optional browser verification:

```powershell
cd frontend
npm.cmd install --no-save --package-lock=false playwright@1.51.1
npx.cmd playwright install chromium
cd ..
python scripts/verify_pipeline.py --browser
```

The browser test renders the dashboard, calculates a price through the real API, checks the rendered decision, and replays history. No network mocks. Browser dependencies may require additional OS packages on Linux.

Core tests only:

```powershell
python -m unittest discover -s tests -p test_engine.py -v
```

## Docker + PostgreSQL alternative

Install Docker Desktop, start it, then run from project root:

```powershell
docker compose up --build
```

Website: http://localhost:8080; API docs: http://localhost:8000/docs. PostgreSQL data persists in a named volume. `docker compose down` stops the stack without deleting that volume. Docker and local SQLite are independent databases. Compose is provided but was not executed in the build environment. Do not expose this prototype to the internet with demo tokens.

## API example

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/pricing/calculate -ContentType application/json -Body '{"product_id":"car_rental_standard","context":{"rental_days":8,"vehicle":"SUV","pickup":"Airport","member":false}}'
```

UI uses `/api/*`; Vite (local) or Nginx (Docker) removes `/api` and forwards to FastAPI. Direct API clients use `/pricing/calculate`, not `/api/pricing/calculate`. `VITE_API_BASE` can override the browser base URL; restart/rebuild after changes. `API_TARGET` sets the Vite proxy destination.

## Repository

```text
backend/app/schema.py       Typed config, request validation
backend/app/engine.py       Pure evaluator + explanation + scenarios
backend/app/db.py           SQLAlchemy tables / connection
backend/app/main.py         FastAPI lifecycle and routes
backend/app/copilot.py      Optional real Gemini draft adapter
configs/*.yaml             Four policies, products, expected-price tests
frontend/src/App.jsx        Dashboard, calculator, history, access
frontend/src/Builder.jsx    Visual strategy editor and lifecycle
frontend/src/Editors.jsx    Expressions, conditions, typed inputs, trace
frontend/src/Simulation.jsx Scenario and version/counterfactual comparison
frontend/src/Products.jsx   Product catalog editor
scripts/run_local.py        Starts connected services
scripts/verify_pipeline.py  Isolated real HTTP verification
scripts/browser_smoke.cjs   Optional real browser smoke
tests/                     Engine and API tests
docs/                      Architecture, demo, provenance, limitations
compose.yaml               PostgreSQL + backend + frontend
```

## Troubleshooting

- `ModuleNotFoundError`: run `python -m pip install -r requirements.txt` using the same Python as your launch command.
- PowerShell blocks npm.ps1: use `npm.cmd` as shown above; no execution-policy change needed.
- API offline: inspect backend terminal, visit `/health`, and check port 8000. Do not start two copies on the same port.
- Writes return 403: reconnect with the correct `.env` publisher/editor token; restart backend after editing environment variables.
- Approval returns 422: inspect Tests. At least one expected-price scenario must pass and no configured scenario may fail.
- Old app still appears: use a separate V2 directory, stop V1, and open the exact V2 URL. Do not overwrite your V1 database.
- UI changes vanish: explicitly save a draft before switching strategies or reloading.
- `npm run preview` alone does not supply the API proxy. Use `run_local.py` or Docker for the connected app.

See `docs/ARCHITECTURE.md`, `docs/DEMO.md`, and `docs/PROVENANCE_AND_LIMITS.md` for design decisions and a judge-facing walkthrough.
