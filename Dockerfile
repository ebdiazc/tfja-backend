FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app.py .

EXPOSE 8080

CMD gunicorn app:app --timeout 180 --workers 1 --bind 0.0.0.0:${PORT:-8080}
