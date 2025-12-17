# NBA SGP Engine - Production Dockerfile
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (for caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY .env.example ./.env.example

# Create non-root user for security
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# NOTE: No HEALTHCHECK - this is a cron job, not a long-running service
# Railway cron services don't need healthchecks

# Default command - run the daily orchestrator
# Handles both settlement and SGP generation
CMD ["python", "-m", "scripts.nba_daily_orchestrator"]
