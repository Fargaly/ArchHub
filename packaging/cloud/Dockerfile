# syntax=docker/dockerfile:1.7
FROM python:3.14.6-slim-bookworm@sha256:86f975aca15cf04a40b399eebede9aea7c82eae084d1f1a0a6ef6bcaae871a30

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=random

RUN groupadd --gid 10001 archhub \
    && useradd --uid 10001 --gid 10001 --no-log-init \
        --home-dir /app --no-create-home archhub

WORKDIR /app

COPY packaging/cloud/requirements.lock /app/requirements.lock
RUN python -m pip install --no-cache-dir --require-hashes -r /app/requirements.lock

COPY --chown=10001:10001 nodelang /app/nodelang

USER 10001:10001
EXPOSE 8482

CMD ["python", "-m", "nodelang.cloud_application_entrypoint"]
