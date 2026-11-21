FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv

COPY pyproject.toml ./
COPY app ./app
RUN pip install .

COPY alembic.ini ./
COPY alembic ./alembic

RUN useradd --uid 10001 --no-create-home app
USER 10001
EXPOSE 8000
# Trust X-Forwarded-For only from the reverse proxy (Caddy/ingress), so client
# IPs (rate limits, Paystack webhook allowlist) are real. Set it to the
# proxy's address or subnet in deployment.
ENV FORWARDED_ALLOW_IPS=127.0.0.1 PLATFORM_ENV=prod
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
