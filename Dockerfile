# Stage 1: Builder
FROM python:3.11-slim AS builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /tmp/build

# Copy all necessary files for uv export
COPY pyproject.toml uv.lock README.md ./
COPY pipelines ./pipelines
COPY agents ./agents
COPY analytics ./analytics
COPY api ./api
COPY config ./config
COPY database ./database
COPY models ./models
COPY scripts ./scripts
COPY services ./services
COPY tests ./tests
COPY utils ./utils

RUN apt-get update && apt-get install -y build-essential

# Export locked dependencies and install system-wide
RUN uv export --no-dev --frozen > requirements.txt && \
    uv pip install --system --no-cache -r requirements.txt

# Stage 2: Runner
FROM python:3.11-slim

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY . .

# Expose the application port
EXPOSE 8000

# Run the application
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
