FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Required env: BACKEND_WS_URL, WORKER_TOKEN, WORKER_ID
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        mecab \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir uv \
    && uv sync --no-dev

COPY . .

ENV PATH="/app/.venv/bin:${PATH}"

CMD ["python", "main.py"]
