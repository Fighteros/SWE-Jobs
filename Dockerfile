FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browser binaries and OS-level deps
RUN playwright install --with-deps chromium

# Copy application code
COPY core/ core/
COPY api/ api/
COPY bot/ bot/
COPY sources/ sources/
COPY main.py server.py ./

EXPOSE 8000

CMD ["python", "server.py"]
