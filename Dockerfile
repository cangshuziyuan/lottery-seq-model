FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    LOTTERY_DB=/app/data/lottery.db \
    BACKFILL_LIMIT=60

RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY frontend ./frontend

VOLUME ["/app/data"]
EXPOSE 5179

CMD ["sh", "-c", "python -m backend.backfill_predictions --limit ${BACKFILL_LIMIT} && exec python -m backend.app"]
