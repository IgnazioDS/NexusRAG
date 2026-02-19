.PHONY: up migrate seed test notify-e2e perf-test perf-report preflight ga-checklist sdk-generate frontend-sdk-build frontend-sdk-test security-audit security-lint security-secrets-scan compliance-snapshot git-network-diag lint typecheck secrets-scan sca

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

notify-e2e:
	# Keep one target usable from host and from within the api container.
	@if command -v docker >/dev/null 2>&1; then \
		docker compose exec api pytest -q nexusrag/tests/integration/test_notification_receiver_e2e.py; \
	else \
		pytest -q nexusrag/tests/integration/test_notification_receiver_e2e.py; \
	fi

perf-test:
	# Run deterministic performance gates and emit JSON diagnostics.
	python tests/perf/assert_perf_gates.py --deterministic --duration "$${PERF_DURATION:-90}"

perf-report:
	# Build a markdown summary from latest perf artifacts.
	python tests/perf/report_summary.py

preflight:
	# Run deploy preflight checks and emit machine-readable output.
	python scripts/preflight.py --output-json var/ops/preflight.json

ga-checklist:
	# Generate GA readiness checklist artifacts from current runtime state.
	python scripts/ga_checklist.py --output-dir "$${GA_CHECKLIST_OUTPUT_DIR:-var/ops}"

security-audit:
	# Run dependency vulnerability audit and emit machine-readable artifacts.
	mkdir -p var/security
	pip-audit --progress-spinner off --format json --output var/security/pip-audit.json
	pip-audit --progress-spinner off > var/security/pip-audit.txt

security-lint:
	# Run deterministic static checks for security-sensitive modules.
	python -m ruff check nexusrag/services/compliance nexusrag/services/security nexusrag/apps/api/routes/compliance.py nexusrag/apps/api/routes/keys_admin.py nexusrag/apps/api/routes/keyring_admin.py nexusrag/apps/api/routes/api_keys_admin.py scripts/compliance_snapshot.py scripts/security_secrets_scan.py scripts/rotate_api_key.py scripts/rotate_platform_key.py --select E9,F63,F7,F82,F401
	python -m mypy --ignore-missing-imports --follow-imports=skip nexusrag/services/security/keyring.py nexusrag/services/compliance/evidence.py nexusrag/services/compliance/controls.py

security-secrets-scan:
	# Scan tracked files for high-risk secret patterns.
	python scripts/security_secrets_scan.py

compliance-snapshot:
	# Persist a compliance snapshot directly from the service layer.
	python scripts/compliance_snapshot.py --tenant "$${TENANT_ID:-t1}" --actor "$${ACTOR_ID:-system}"

git-network-diag:
	# Run non-destructive GitHub transport diagnostics for push/pull troubleshooting.
	./scripts/git_network_diag.sh

lint:
	# Provide a standard lint entrypoint for CI wrappers and local developer workflows.
	python -m ruff check nexusrag scripts

typecheck:
	# Keep type checks deterministic by targeting security/compliance modules with stable import surfaces.
	python -m mypy --ignore-missing-imports --follow-imports=skip nexusrag/services/security/keyring.py nexusrag/services/compliance/evidence.py nexusrag/services/compliance/controls.py nexusrag/apps/api/routes/api_keys_admin.py nexusrag/apps/api/routes/keyring_admin.py

secrets-scan:
	# Run deterministic tracked-file secret scans while excluding local env/runtime directories.
	python scripts/security_secrets_scan.py

sca:
	# Provide a short alias for dependency vulnerability scanning in pre-release gates.
	mkdir -p var/security
	pip-audit --progress-spinner off > var/security/pip-audit.txt

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
