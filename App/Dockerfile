FROM python:3.11-slim

WORKDIR /srv

# System deps for pdfplumber (pdfminer.six needs zlib/jpeg for some PDFs)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend app + rule/schema configs + sample data
COPY backend/ ./backend/
# Copy frontend (served as static files by FastAPI)
COPY frontend/ ./frontend/

WORKDIR /srv/backend

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

# Railway injects $PORT; default to 8000 for local docker run.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
