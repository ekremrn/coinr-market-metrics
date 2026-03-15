FROM python:3.12-alpine

WORKDIR /app

RUN apk add --no-cache git gcc musl-dev libffi-dev

COPY src/ ./src/
COPY api/ ./api/
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

ENV PYTHONPATH=/app

CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port 8000 --workers ${API_WORKERS:-3}"]
