# Document Intelligence — task runner
# https://just.systems

set dotenv-load := true

api_port := env('API_PORT', '8000')
web_port := env('WEB_PORT', '5173')

# List available recipes
default:
    @just --list

# Install Python and Node dependencies
install:
    uv sync
    cd web && npm install

# First-time setup: .env, dependencies, local services, and the schema
setup: install services-up
    @test -f .env || (cp .env.example .env && echo "Created .env — fill in your credentials")
    @sleep 2 && just migrate

# --- services ---

# Start Postgres
services-up:
    docker compose up -d

# Stop Postgres
services-down:
    docker compose down

# Tail service logs
services-logs:
    docker compose logs -f

# --- development ---

# Run the FastAPI server with reload
api:
    uv run fastapi dev src/api/main.py --port {{ api_port }}

# Run the Vite dev server
web:
    cd web && npm run dev -- --port {{ web_port }}

# Run the BullMQ worker (all queues, or the ones named)
worker *queues:
    uv run python -m jobs.worker {{ queues }}

# Run the API, web, and worker processes together
dev:
    #!/usr/bin/env bash
    set -euo pipefail
    trap 'kill 0' EXIT INT TERM
    just api &
    just web &
    just worker &
    wait

# Open the interactive API docs
docs:
    open http://localhost:{{ api_port }}/docs

# --- database ---

# Apply the application schema (documents, pages, tables, cells)
migrate:
    uv run alembic upgrade head

# Generate a migration from a change to db/models.py
migration message:
    uv run alembic revision --autogenerate -m "{{ message }}"

# Roll back the most recent migration
migrate-down:
    uv run alembic downgrade -1

# Current migration revision
migrate-status:
    uv run alembic current

# --- queues ---

# Apply the BullMQ Postgres schema (queues also do this lazily on first use)
queue-migrate:
    uv run python -m jobs.migrate

# Job counts for a queue
queue-counts queue="filings":
    curl -fsS http://localhost:{{ api_port }}/queues/{{ queue }}

# --- documents ---

# Upload a PDF and queue extraction
upload pdf:
    curl -fsS -X POST http://localhost:{{ api_port }}/documents \
      -F "file=@{{ pdf }}" | python3 -m json.tool

# Extraction summary for a document
document id:
    curl -fsS http://localhost:{{ api_port }}/documents/{{ id }} | python3 -m json.tool

# Tables extracted from a document
tables id:
    curl -fsS http://localhost:{{ api_port }}/documents/{{ id }}/tables | python3 -m json.tool

# Re-run extraction over the stored PDF (after a threshold change, say)
reextract id:
    curl -fsS -X POST http://localhost:{{ api_port }}/documents/{{ id }}/extract | python3 -m json.tool

# --- checks ---

# Run the Python test suite
test *args:
    uv run pytest {{ args }}

# Run the frontend test suite
test-web *args:
    cd web && npm run test -- {{ args }}

# Typecheck and build the frontend
build:
    cd web && npm run build

# Lint the frontend
lint:
    cd web && npm run lint

# Run every check
check: test test-web lint build

# --- maintenance ---

# Regenerate the TanStack Router route tree
routes:
    cd web && npx vite build --logLevel silent && echo "Regenerated web/src/routeTree.gen.ts"

# Remove build output and caches
clean:
    rm -rf web/dist web/node_modules/.tmp web/node_modules/.vite
    find src -type d -name __pycache__ -prune -exec rm -rf {} +
