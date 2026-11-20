# Platform API

FastAPI service for identity, wallet ledger, Paystack payments, tables and tournaments.
See `../docs/platform/ARCHITECTURE.md`.

## Run locally (Docker)
```bash
cp .env.example .env          # optional
docker compose up --build
curl localhost:8000/healthz   # {"status":"ok"}
curl localhost:8000/readyz    # {"postgres":"ok","redis":"ok"}
```
API docs: http://localhost:8000/docs · Mail catcher: http://localhost:58025

## Run tests (no Docker needed)
```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
pytest && ruff check . && mypy app
```

## Migrations
```bash
alembic revision --autogenerate -m "describe change"
alembic upgrade head
```
