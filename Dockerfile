FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml README.md /app/
COPY nexusrag /app/nexusrag

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -e .

ENV PYTHONUNBUFFERED=1

CMD ["uvicorn", "nexusrag.apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
