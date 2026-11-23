FROM python:3.11-slim

ENV TZ=UTC
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright's bundled Node needs libatomic before --with-deps can run.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libatomic1 \
    && rm -rf /var/lib/apt/lists/*

# Install Playwright browser binaries and OS-level deps
RUN playwright install --with-deps chromium

# Copy application code
COPY core/ core/
COPY api/ api/
COPY bot/ bot/
COPY sources/ sources/
COPY scripts/ scripts/
COPY main.py server.py ./

EXPOSE 8000

CMD ["python", "server.py"]
