FROM python:3.12-slim

WORKDIR /app

# Install git for mgz fork
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install --no-cache-dir \
    flask \
    trueskill \
    gunicorn \
    boto3 \
    pandas \
    git+https://github.com/sanduckhan/aoc-mgz.git@ee49154

# Copy application code
COPY analyzer_lib/ analyzer_lib/
COPY scripts/ scripts/
COPY web/ web/
COPY server/ server/
COPY run_web.py ./

# Data directory (Railway persistent volume mount point)
ENV DATA_DIR=/app/data

# Single worker with threads: all threads share memory so background rebuild
# progress is visible to status endpoint. Timeout kept high for long requests.
CMD gunicorn --bind 0.0.0.0:$PORT --worker-class gthread --workers 1 --threads 4 --timeout 600 web.app:app
