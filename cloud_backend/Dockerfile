FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000
# NOTE: ENV=production is NOT baked into the image.
# config.py._req() raises on missing required env when ENV=production.
# Set it via `fly secrets set ENV=production` AFTER the upstream API
# keys (STRIPE_*, ANTHROPIC_API_KEY, etc.) are also set. Until then
# the app boots in "dev tolerant" mode and any endpoint needing a
# missing key returns 503 at call time — healthz stays green.

WORKDIR /app

# Install deps first so they cache across code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code.
COPY . .

# Fly.io / Cloud Run / generic container.
EXPOSE 8000

# SQLite file lives on a mounted volume in production.
VOLUME ["/data"]
ENV DATABASE_URL=/data/archhub_cloud.db

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--access-log", "--log-level", "debug"]
