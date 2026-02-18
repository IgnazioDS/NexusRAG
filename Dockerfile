FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    # Install make so perf-test/perf-report targets can run inside the api container.
    && apt-get install -y --no-install-recommends make \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md /app/
COPY nexusrag /app/nexusrag
COPY scripts /app/scripts
COPY tests /app/tests
COPY Makefile /app/Makefile

RUN pip install --no-cache-dir --upgrade "pip<26" \
    # Install dev extras so pytest is available inside the container.
    && pip install --no-cache-dir -e .[dev]

ENV PYTHONUNBUFFERED=1

CMD ["uvicorn", "nexusrag.apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
