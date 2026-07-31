FROM python:3.12-slim

# ffmpeg is needed for frame sampling + audio extraction.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x entrypoint.sh

# Migrations run on every boot, before the process starts — the schema is owned
# by Alembic in every environment, including production.
ENTRYPOINT ["./entrypoint.sh"]
# sh -c so $PORT expands: managed platforms assign the port at runtime and route
# to it, so a hardcoded 8000 would pass the build and then fail every health
# check. Falls back to 8000 for local docker compose.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
