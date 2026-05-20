FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir -e ".[stt-elevenlabs]" && \
    pip install --no-cache-dir fastapi "uvicorn[standard]"

EXPOSE 8000

CMD ["uvicorn", "examples.fastapi_ws_demo:app", "--host", "0.0.0.0", "--port", "8000"]
