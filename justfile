# Insurer Public Disclosure — task runner
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

# First-time setup: .env, dependencies, and local services
setup: install services-up
    @test -f .env || (cp .env.example .env && echo "Created .env — fill in your credentials")

# --- services ---

# Start Postgres and Redis
services-up:
    docker compose up -d

# Stop Postgres and Redis
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

# Run the API and web dev servers together
dev:
    #!/usr/bin/env bash
    set -euo pipefail
    trap 'kill 0' EXIT INT TERM
    just api &
    just web &
    wait

# Open the interactive API docs
docs:
    open http://localhost:{{ api_port }}/docs

# --- checks ---

# Typecheck and build the frontend
build:
    cd web && npm run build

# Lint the frontend
lint:
    cd web && npm run lint

# Run every check
check: lint build

# --- maintenance ---

# Regenerate the TanStack Router route tree
routes:
    cd web && npx vite build --logLevel silent && echo "Regenerated web/src/routeTree.gen.ts"

# Remove build output and caches
clean:
    rm -rf web/dist web/node_modules/.tmp web/node_modules/.vite
    find src -type d -name __pycache__ -prune -exec rm -rf {} +
