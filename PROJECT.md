# ClawFS

> Content-addressed file system for humans and AI agents.
> Built collaboratively by 4 sub-agents (CEO / PM / Designer / Dev) coordinated by Agent008 🌙.

## Repo Layout
- `README.md` — install, run (local / docker / azure)
- `PROJECT.md` — this file (project overview)
- `docs/VISION.md` — CEO: vision, differentiation, KPIs, non-goals
- `docs/SPEC.md` — PM: MoSCoW scope, REST API, CLI, data model, milestones, acceptance criteria
- `docs/DESIGN.md` — Designer: design philosophy + CLI UX
- `design/ui.html` — Designer: dark-theme web UI mockup (open in browser)
- `clawfs/` — Dev: Python implementation (FastAPI + SQLite + local storage, Azure Blob stub)
- `tests/` — unit tests (3 passing)
- `Dockerfile` — single-host container
- `azure/container-app.bicep` — Azure Container App + Blob Storage IaC (v2)

## Quick start
```bash
pip install -e .
uvicorn clawfs.api:app --reload
# or
docker build -t clawfs . && docker run -p 8000:8000 clawfs
```

## Test
```bash
pytest tests/ -v
```
