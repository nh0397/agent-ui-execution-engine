FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml ./
COPY engine/ ./engine/
COPY demo/ ./demo/
RUN pip install --no-cache-dir ".[postgres]" \
    && useradd --create-home --uid 10001 app \
    && mkdir -p /app/work && chown app:app /app/work
USER app
EXPOSE 8000
CMD ["uvicorn", "demo.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
