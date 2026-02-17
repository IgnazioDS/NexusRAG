.PHONY: up migrate seed test perf-test perf-report sdk-generate frontend-sdk-build frontend-sdk-test

up:
	# Bring up docker compose services for local dev.
	docker compose up --build -d

migrate:
	# Apply database migrations in the api container.
	docker compose exec api alembic upgrade head

seed:
	# Seed demo corpus/chunks for local retrieval checks.
	docker compose exec api python scripts/seed_demo.py

test:
	# Run the test suite inside the api container.
	docker compose exec api pytest -q

perf-test:
	# Run deterministic performance gates and emit JSON diagnostics.
	python tests/perf/assert_perf_gates.py --deterministic --duration "$${PERF_DURATION:-90}"

perf-report:
	# Build a markdown summary from latest perf artifacts.
	python tests/perf/report_summary.py

sdk-generate:
	# Generate TypeScript and Python SDKs from the OpenAPI schema.
	python scripts/generate_sdk.py

frontend-sdk-build:
	# Build the frontend integration SDK for web apps.
	npm --prefix sdk/frontend install
	npm --prefix sdk/frontend run build

frontend-sdk-test:
	# Typecheck the frontend integration SDK.
	npm --prefix sdk/frontend run test
