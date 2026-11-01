# syntax=docker/dockerfile:1
FROM python:3.12-slim

# Mencegah Python membuat file bytecode .pyc dan memastikan output log tidak dibuffer
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Salin file dependensi dan pasang paket yang dibutuhkan
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Salin seluruh kode aplikasi ke container
COPY . .

# Expose port HTTP default
EXPOSE 8000

# Docker Healthcheck menggunakan endpoint /health
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Jalankan server uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
