FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ENV=production \
    PORT=8000

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
     "--workers", "2", "--access-log"]
