# TerraTrace AI backend — deploy on Render / Railway / Fly.io
FROM python:3.12-slim

WORKDIR /app

# System deps for rasterio, shapely, etc.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gdal-bin libgdal-dev libgeos-dev libproj-dev \
    && rm -rf /var/lib/apt/lists/*

ENV GDAL_CONFIG=/usr/bin/gdal-config

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

# Create data directories
RUN mkdir -p /app/data/artifacts /app/data/datasets /app/data/models

# Environment
ENV DATABASE_URL=sqlite:////app/data/terratrace.db
ENV DATA_DIR=/app/data
ENV ARTIFACTS_DIR=/app/data/artifacts
ENV PORT=8000

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]