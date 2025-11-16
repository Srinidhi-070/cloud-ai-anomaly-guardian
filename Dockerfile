# Dockerfile
FROM python:3.12-slim

WORKDIR /app

# system deps (if needed for sklearn wheels); keeps image small
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# copy and install python deps
COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# copy app code
COPY api ./api
COPY models ./models

EXPOSE 8000

# run uvicorn
CMD ["uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8000"]
