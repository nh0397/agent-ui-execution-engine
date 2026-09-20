FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PLAYWRIGHT_BROWSERS_PATH=/opt/browsers
WORKDIR /project
COPY pyproject.toml ./
COPY engine/ ./engine/
COPY demo/ ./demo/
RUN pip install --no-cache-dir . && python -m playwright install --with-deps chromium \
    && useradd --create-home --uid 10001 worker && mkdir -p /project/work/dashboard \
    && chown -R worker:worker /project/work /opt/browsers
COPY config/ ./config/
COPY capabilities/ ./capabilities/
USER worker
EXPOSE 8001
CMD ["uvicorn", "engine.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8001", "--no-access-log"]
