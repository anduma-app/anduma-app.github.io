# Immagine unica per API e worker.
#   API:    docker run <img>                      (migrazioni + uvicorn)
#   Worker: docker run <img> python -m app.worker (scheduler alert + push, UNA replica)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    PATH="/app/.venv/bin:$PATH"

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
WORKDIR /app

# Dipendenze prima del codice: layer riusato finché il lockfile non cambia.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app
RUN uv sync --frozen --no-dev

# Utente non root; il codice resta di root in sola lettura (l'app non scrive in /app).
RUN useradd --create-home --uid 10001 transito
USER transito

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers"]
