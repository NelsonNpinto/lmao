.PHONY: install seed seed-refresh report api-types requirements e2e snapshot screenshots up backend frontend dev test lint

install:
	cd backend && uv sync
	cd frontend && npx -y npm@11 install

seed:
	cd backend && uv run python -m app.cli seed

seed-refresh:
	cd backend && uv run python -m app.cli seed --refresh

report:
	cd backend && uv run python -m app.cli report --cutoff 07:00 --cutoff 09:00 --cutoff 11:00

api-types:
	cd backend && uv run python -m app.cli openapi ../frontend/openapi.json
	cd frontend && npm run -s gen:api

# Root requirements.txt is what the Vercel Python function installs.
requirements:
	cd backend && uv export --frozen --no-dev --no-emit-project --no-hashes -o ../requirements.txt

backend:
	cd backend && uv run uvicorn app.main:app --reload --port 8010

frontend:
	cd frontend && npm run dev

# Run both dev servers; Ctrl+C stops both.
dev:
	$(MAKE) -j2 backend frontend

test:
	cd backend && uv run pytest
	cd frontend && npm test

snapshot:
	cd backend && uv run python -m app.cli snapshot ../frontend/public/snapshot

screenshots:
	cd frontend && npm run -s screenshots

up:
	docker compose up --build

e2e:
	cd frontend && npx playwright test

lint:
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app
	cd frontend && npm run lint && npm run typecheck
