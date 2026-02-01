FROM python:3.12-alpine

WORKDIR /app

RUN apk add --no-cache git gcc musl-dev libffi-dev

COPY src/ ./src/
COPY scanner-job/ ./scanner-job/
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

ENV PYTHONPATH=/app

CMD ["python", "scanner-job/main.py"]
