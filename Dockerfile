# ── Stage 1: builder ──────────────────────────────────────────────────────────
# Installs all production dependencies into an isolated venv.
# This stage is also the target used by CI to run tests with dev extras.
FROM python:3.11-slim AS builder

WORKDIR /build

RUN pip install --no-cache-dir --upgrade "pip<26"

COPY pyproject.toml README.md ./
COPY nexusrag ./nexusrag

# Install production deps into /venv so the final stage can copy them cleanly.
RUN python -m venv /venv \
    && /venv/bin/pip install --no-cache-dir --upgrade "pip<26" \
    && /venv/bin/pip install --no-cache-dir .

# ── Stage 2: test (CI only) ────────────────────────────────────────────────────
# Extends builder with dev extras (pytest, ruff, mypy). Not deployed.
FROM builder AS test

RUN /venv/bin/pip install --no-cache-dir -e ".[dev]"

COPY scripts ./scripts
COPY tests ./tests
COPY Makefile ./Makefile
COPY alembic.ini ./alembic.ini

ENV PYTHONUNBUFFERED=1 \
    PATH="/venv/bin:$PATH"

# ── Stage 3: production ────────────────────────────────────────────────────────
# Contains only the app code and production dependencies.
# No pytest, ruff, mypy, pip-audit, or other dev tooling.
FROM python:3.11-slim AS production

WORKDIR /app

RUN apt-get update \
    # make is needed for perf-test/perf-report Makefile targets.
    && apt-get install -y --no-install-recommends make \
    && rm -rf /var/lib/apt/lists/*

# Copy the production venv from the builder stage.
COPY --from=builder /venv /venv

# Copy application code and operational scripts only — no test suite.
COPY nexusrag ./nexusrag
COPY scripts ./scripts
COPY Makefile ./Makefile
COPY alembic.ini ./alembic.ini
COPY pyproject.toml README.md ./

ENV PYTHONUNBUFFERED=1 \
    PATH="/venv/bin:$PATH"

CMD ["uvicorn", "nexusrag.apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
