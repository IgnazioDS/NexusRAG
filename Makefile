.PHONY: up migrate seed test sdk-generate

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

sdk-generate:
	# Generate TypeScript and Python SDKs from the OpenAPI schema.
	python scripts/generate_sdk.py
