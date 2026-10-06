FROM python:3.12-slim

WORKDIR /app

# System deps for asyncpg, shapely, geoalchemy2
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev libgeos-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Railway sets PORT env var
EXPOSE ${PORT:-8000}

CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
